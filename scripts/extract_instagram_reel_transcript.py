#!/usr/bin/env python3
"""Instagram Reel speech + on-screen caption extractor.

Speech is transcribed with Whisper. On-screen captions are OCR'd on a dense
interval, then collapsed to a cue only when the visible text changes. The
aligned track maps each spoken line to the caption that was on screen at
that time, sorted by start time.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shlex
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlparse

SHORTCODE = re.compile(r"^/(?:reel|reels|p)/([A-Za-z0-9_-]+)/?$")
WHITESPACE = re.compile(r"\s+")


def shortcode(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.netloc not in {"instagram.com", "www.instagram.com"}:
        raise ValueError("Expected an https://www.instagram.com/reel/<shortcode>/ URL")
    match = SHORTCODE.fullmatch(parsed.path)
    if not match:
        raise ValueError("Expected an Instagram Reel URL, not a profile or query URL")
    return match.group(1)


def command(template: str, **values: str) -> list[str]:
    return [part.format(**values) for part in shlex.split(template)]


def run(template: str, **values: str) -> None:
    subprocess.run(command(template, **values), check=True, capture_output=True, text=True)


def normalize_caption(text: str) -> str:
    return WHITESPACE.sub(" ", str(text).replace("\n", " ")).strip()


def read_track(path: Path, name: str) -> list[dict]:
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{name} did not produce valid JSON") from exc
    if not isinstance(raw, list):
        raise RuntimeError(f"{name} output must be a JSON list")
    track = []
    for item in raw:
        if not isinstance(item, dict) or not all(key in item for key in ("start", "end", "text")):
            raise RuntimeError(f"{name} entries require start, end, and text")
        try:
            start, end = float(item["start"]), float(item["end"])
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"{name} timestamps must be numeric") from exc
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise RuntimeError(f"{name} timestamps must satisfy 0 <= start < end")
        text = normalize_caption(item["text"])
        if text:
            track.append({"start": start, "end": end, "text": text, "source": name})
    return track


def read_whisper_track(path: Path) -> list[dict]:
    try:
        payload = json.loads(path.read_text())
        segments = payload["segments"] if isinstance(payload, dict) else payload
        if not isinstance(segments, list):
            raise TypeError("segments")
        normalized = []
        for item in segments:
            if not isinstance(item, dict):
                raise TypeError("segment")
            normalized.append({"start": item["start"], "end": item["end"], "text": item["text"]})
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Whisper did not produce valid segment JSON") from exc
    scratch = path.with_suffix(".track.json")
    scratch.write_text(json.dumps(normalized))
    try:
        return read_track(scratch, "speech")
    finally:
        scratch.unlink(missing_ok=True)


def collapse_screen_track(samples: list[dict], min_hold: float = 0.0) -> list[dict]:
    """Merge consecutive OCR samples until the visible caption text changes."""
    cues: list[dict] = []
    for sample in sorted(samples, key=lambda item: (item["start"], item["end"])):
        text = normalize_caption(sample["text"])
        if not text:
            continue
        if cues and cues[-1]["text"] == text:
            cues[-1]["end"] = max(cues[-1]["end"], sample["end"])
            continue
        cues.append(
            {
                "start": sample["start"],
                "end": sample["end"],
                "text": text,
                "source": "screen",
            }
        )
    if min_hold <= 0:
        return cues
    return [cue for cue in cues if cue["end"] - cue["start"] >= min_hold]


def caption_at(screen: list[dict], t: float) -> dict | None:
    active = None
    for cue in screen:
        if cue["start"] <= t < cue["end"]:
            return cue
        if cue["start"] <= t:
            active = cue
    return active


def align_tracks(speech: list[dict], screen: list[dict]) -> list[dict]:
    aligned = []
    for line in sorted(speech, key=lambda item: item["start"]):
        cue = caption_at(screen, line["start"])
        mid = caption_at(screen, (line["start"] + line["end"]) / 2)
        if mid is not None:
            cue = mid
        aligned.append(
            {
                "start": line["start"],
                "end": line["end"],
                "speech": line["text"],
                "screen": None if cue is None else cue["text"],
                "screen_start": None if cue is None else cue["start"],
                "screen_end": None if cue is None else cue["end"],
            }
        )
    return aligned


def timestamp(seconds: float) -> str:
    millis = max(0, round(seconds * 1000))
    hours, millis = divmod(millis, 3_600_000)
    minutes, millis = divmod(millis, 60_000)
    secs, millis = divmod(millis, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def srt(track: list[dict]) -> str:
    blocks = []
    for index, item in enumerate(sorted(track, key=lambda x: (x["start"], x["source"], x["end"])), 1):
        blocks.append(
            f"{index}\n{timestamp(item['start'])} --> {timestamp(item['end'])}\n[{item['source']}] {item['text']}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def aligned_text(rows: list[dict]) -> str:
    blocks = []
    for row in rows:
        screen = row["screen"] or "(화면 자막 없음)"
        blocks.append(
            f"{timestamp(row['start'])} --> {timestamp(row['end'])}\n"
            f"음성: {row['speech']}\n"
            f"화면: {screen}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def extract(args: argparse.Namespace) -> dict:
    code = shortcode(args.url)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="instagram-reel-") as temp:
        temp_path = Path(temp)
        video = str(temp_path / "reel.mp4")
        asr_dir = temp_path / "whisper"
        asr_dir.mkdir()
        screen_tmp = temp_path / "screen.json"
        values = {
            "url": args.url,
            "video": video,
            "asr_dir": str(asr_dir),
            "screen": str(screen_tmp),
            "language": args.language,
        }
        if args.video:
            source = Path(args.video)
            if not source.is_file():
                raise RuntimeError(f"Local video not found: {source}")
            Path(video).write_bytes(source.read_bytes())
        else:
            try:
                run(args.downloader_cmd, **values)
            except FileNotFoundError as exc:
                raise RuntimeError("Downloader unavailable: install uvx or provide --downloader-cmd") from exc
            except subprocess.CalledProcessError as exc:
                raise RuntimeError("Reel media is not anonymously accessible") from exc
        try:
            run(args.asr_cmd, **values)
            whisper_json = next(asr_dir.glob("*.json"))
            speech = read_whisper_track(whisper_json)
        except FileNotFoundError as exc:
            raise RuntimeError("Whisper unavailable: install uvx/mlx-whisper or provide --asr-cmd") from exc
        except (StopIteration, subprocess.CalledProcessError) as exc:
            raise RuntimeError("Local Whisper transcription failed") from exc
        screen_samples = []
        if args.ocr_cmd:
            try:
                run(args.ocr_cmd, **values)
                screen_samples = read_track(screen_tmp, "screen")
            except (subprocess.CalledProcessError, FileNotFoundError) as exc:
                raise RuntimeError("Local OCR command failed") from exc
        screen = collapse_screen_track(screen_samples)
        aligned = align_tracks(speech, screen)
        paths = {
            "speech": out_dir / f"{code}.speech.json",
            "screen": out_dir / f"{code}.screen.json",
            "aligned": out_dir / f"{code}.aligned.json",
            "srt": out_dir / f"{code}.srt",
            "aligned_txt": out_dir / f"{code}.aligned.txt",
            "metadata": out_dir / f"{code}.metadata.json",
        }
        paths["speech"].write_text(json.dumps(speech, ensure_ascii=False, indent=2) + "\n")
        paths["screen"].write_text(json.dumps(screen, ensure_ascii=False, indent=2) + "\n")
        paths["aligned"].write_text(json.dumps(aligned, ensure_ascii=False, indent=2) + "\n")
        paths["srt"].write_text(srt(speech + screen))
        paths["aligned_txt"].write_text(aligned_text(aligned))
        metadata = {
            "source_url": args.url,
            "shortcode": code,
            "speech": str(paths["speech"]),
            "screen": str(paths["screen"]),
            "aligned": str(paths["aligned"]),
            "aligned_txt": str(paths["aligned_txt"]),
            "srt": str(paths["srt"]),
            "screen_text_status": (
                "not_requested"
                if not args.ocr_cmd
                else ("extracted" if screen else "no_text_recognized")
            ),
        }
        paths["metadata"].write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
        return metadata


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--out-dir", default=".instagram-reel-transcripts")
    parser.add_argument("--language", default="ko,en")
    parser.add_argument("--video", default="", help="Skip download and transcribe this local mp4.")
    parser.add_argument(
        "--downloader-cmd",
        default="uvx --from yt-dlp yt-dlp --no-playlist --no-warnings -o {video} {url}",
    )
    parser.add_argument(
        "--asr-cmd",
        default="uvx --from openai-whisper whisper {video} --model base --language Korean --output_format json --output_dir {asr_dir}",
    )
    parser.add_argument(
        "--ocr-cmd",
        default=f"swift {Path(__file__).with_name('ocr_reel_frames.swift')} {{video}} ko-KR,en-US {{screen}} 0.5",
        help="Command that writes JSON OCR samples to {screen}.",
    )
    args = parser.parse_args()
    try:
        print(json.dumps(extract(args), ensure_ascii=False))
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
