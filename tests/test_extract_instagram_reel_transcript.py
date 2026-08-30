import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SCRIPT = Path(__file__).parents[1] / "scripts" / "extract_instagram_reel_transcript.py"
spec = importlib.util.spec_from_file_location("reel", SCRIPT)
reel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reel)


class ReelTests(unittest.TestCase):
    def args(self, root, ocr_cmd=""):
        return SimpleNamespace(
            url="https://www.instagram.com/reel/test_1/",
            out_dir=str(root / "out"),
            language="ko,en",
            video="",
            downloader_cmd="download",
            asr_cmd="asr",
            ocr_cmd=ocr_cmd,
        )

    def test_shortcode_validation(self):
        self.assertEqual(reel.shortcode("https://www.instagram.com/reel/DaU9JkRyicw/"), "DaU9JkRyicw")
        self.assertEqual(reel.shortcode("https://www.instagram.com/p/DcI3nc7x-iP/"), "DcI3nc7x-iP")
        self.assertEqual(reel.shortcode("https://www.instagram.com/reels/DcI3nc7x-iP/"), "DcI3nc7x-iP")
        for value in ("http://www.instagram.com/reel/x/", "https://evil.test/reel/x/"):
            with self.assertRaises(ValueError):
                reel.shortcode(value)

    def test_track_rejects_invalid_intervals(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "track.json"
            for start, end in ((0, 0), (1, 0), (-1, 1), (float("nan"), 1), (0, float("inf"))):
                path.write_text(json.dumps([{"start": start, "end": end, "text": "x"}]))
                with self.assertRaisesRegex(RuntimeError, "timestamps"):
                    reel.read_track(path, "speech")

    def test_extract_normalizes_whisper_and_writes_srt(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)

            def fake_run(template, **values):
                if template == "download":
                    Path(values["video"]).write_bytes(b"media")
                else:
                    Path(values["asr_dir"], "reel.json").write_text(
                        json.dumps({"segments": [{"start": 0, "end": 1, "text": "안녕"}]})
                    )

            with patch.object(reel, "run", fake_run):
                result = reel.extract(self.args(root))
            self.assertTrue(Path(result["srt"]).exists())
            self.assertTrue(Path(result["aligned"]).exists())
            self.assertEqual(json.loads(Path(result["speech"]).read_text())[0]["text"], "안녕")
            self.assertEqual(result["screen_text_status"], "not_requested")

    def test_collapse_screen_track_on_text_change(self):
        samples = [
            {"start": 0.0, "end": 0.5, "text": "A", "source": "screen"},
            {"start": 0.5, "end": 1.0, "text": "A", "source": "screen"},
            {"start": 1.0, "end": 1.5, "text": "B", "source": "screen"},
            {"start": 1.5, "end": 2.0, "text": "B  ", "source": "screen"},
            {"start": 2.0, "end": 2.5, "text": "A", "source": "screen"},
        ]
        cues = reel.collapse_screen_track(samples)
        self.assertEqual(
            [(c["start"], c["end"], c["text"]) for c in cues],
            [(0.0, 1.0, "A"), (1.0, 2.0, "B"), (2.0, 2.5, "A")],
        )

    def test_align_tracks_maps_speech_to_active_caption(self):
        speech = [
            {"start": 0.2, "end": 0.8, "text": "안녕", "source": "speech"},
            {"start": 1.2, "end": 1.8, "text": "쿠션", "source": "speech"},
        ]
        screen = reel.collapse_screen_track(
            [
                {"start": 0.0, "end": 1.0, "text": "화면1", "source": "screen"},
                {"start": 1.0, "end": 2.0, "text": "화면2", "source": "screen"},
            ]
        )
        aligned = reel.align_tracks(speech, screen)
        self.assertEqual(aligned[0]["speech"], "안녕")
        self.assertEqual(aligned[0]["screen"], "화면1")
        self.assertEqual(aligned[1]["speech"], "쿠션")
        self.assertEqual(aligned[1]["screen"], "화면2")
        self.assertLess(aligned[0]["start"], aligned[1]["start"])

    def test_srt_is_timestamped_and_sorted(self):
        result = reel.srt(
            [
                {"start": 2, "end": 3, "text": "화면", "source": "screen"},
                {"start": 0, "end": 1.25, "text": "speech", "source": "speech"},
            ]
        )
        self.assertIn("00:00:00,000 --> 00:00:01,250", result)
        self.assertTrue(result.startswith("1\n"))
        self.assertLess(result.index("[speech]"), result.index("[screen]"))

    def test_downloader_missing_is_not_access_error(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(reel, "run", side_effect=FileNotFoundError()):
                with self.assertRaisesRegex(RuntimeError, "Downloader unavailable"):
                    reel.extract(self.args(Path(root)))

    def test_asr_failure_is_explicit(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)

            def fake_run(template, **values):
                if template == "download":
                    Path(values["video"]).write_bytes(b"media")
                else:
                    raise subprocess.CalledProcessError(1, template)

            with patch.object(reel, "run", fake_run):
                with self.assertRaisesRegex(RuntimeError, "Whisper transcription failed"):
                    reel.extract(self.args(root))

    def test_extract_collapses_ocr_and_writes_aligned(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)

            def fake_run(template, **values):
                if template == "download":
                    Path(values["video"]).write_bytes(b"media")
                elif template == "asr":
                    Path(values["asr_dir"], "reel.json").write_text(
                        json.dumps(
                            {
                                "segments": [
                                    {"start": 0.1, "end": 0.9, "text": "안녕"},
                                    {"start": 1.1, "end": 1.8, "text": "쿠션"},
                                ]
                            }
                        )
                    )
                else:
                    Path(values["screen"]).write_text(
                        json.dumps(
                            [
                                {"start": 0.0, "end": 0.5, "text": "화면1"},
                                {"start": 0.5, "end": 1.0, "text": "화면1"},
                                {"start": 1.0, "end": 1.5, "text": "화면2"},
                            ]
                        )
                    )

            with patch.object(reel, "run", fake_run):
                result = reel.extract(self.args(root, ocr_cmd="ocr"))
            screen = json.loads(Path(result["screen"]).read_text())
            aligned = json.loads(Path(result["aligned"]).read_text())
            self.assertEqual([item["text"] for item in screen], ["화면1", "화면2"])
            self.assertEqual(aligned[0]["screen"], "화면1")
            self.assertEqual(aligned[1]["screen"], "화면2")
            self.assertEqual(result["screen_text_status"], "extracted")


if __name__ == "__main__":
    unittest.main()
