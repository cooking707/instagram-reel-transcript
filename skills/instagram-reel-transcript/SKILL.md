---
name: "instagram-reel-transcript"
description: "Extract Instagram Reel spoken audio with Whisper and on-screen captions on text-change, then emit a time-ordered speech/screen alignment. Use when the user gives an Instagram Reel/post URL and asks for 대본, transcript, subtitles, SRT, speech, or visible captions."
use_when:
  - "Instagram Reel URL에서 자막·대본·SRT·대사·화면 텍스트를 추출"
---

# Instagram Reel Transcript

Always extract **speech** and **on-screen captions** as two tracks, then align them **in time order**. Never treat OCR frames, post captions, or comments as the spoken script.

## Required pipeline

1. Resolve media
   - Accept `/reel/`, `/reels/`, or `/p/` URLs.
   - If a local mp4 already exists, pass `--video`.
   - Else download. Public `yt-dlp` first. If Instagram is login-gated, use a logged-in Aside/browser session: read `script[type="application/json"]` for `code` + `video_versions[0].url`, cookie-authenticated fetch to mp4. Do not invent speech from the landing-page caption.
2. Speech (Whisper)
   - Transcribe the audio timeline with timestamps.
   - Prefer `mlx-whisper` on Apple Silicon (`mlx-community/whisper-large-v3-turbo`, `language=ko` for Korean reels). Fallback: `uvx --from openai-whisper whisper`.
   - Output is the spoken track. Do not shuffle segments.
3. Screen captions (OCR on change)
   - Sample the **bottom caption band** densely (default 0.5s).
   - Keep a new cue only when normalized on-screen text **changes**. Identical consecutive samples merge into one cue.
   - Do not group by visual cut, and do not emit one line per sampled frame.
4. Align in time order
   - For each spoken segment, attach the screen cue active at that timestamp.
   - Sort every delivered list by `start`.
   - Deliver speech, screen-change cues, and `음성`/`화면` pairs. Never a screen-only dump as “대본”.

## Command

```bash
python3 scripts/extract_instagram_reel_transcript.py \
  "https://www.instagram.com/reel/SHORTCODE/" \
  --out-dir artifacts/instagram-reel-transcripts
```

Local file:

```bash
python3 scripts/extract_instagram_reel_transcript.py \
  "https://www.instagram.com/reel/SHORTCODE/" \
  --video /path/to/reel.mp4 \
  --out-dir artifacts/instagram-reel-transcripts
```

Apple Silicon ASR override:

```bash
--asr-cmd '/tmp/whisper-venv/bin/python -c "from mlx_whisper import transcribe; import json,sys; r=transcribe(\"{video}\", path_or_hf_repo=\"mlx-community/whisper-large-v3-turbo\", language=\"ko\"); json.dump(r, open(\"{asr_dir}/reel.json\",\"w\"), ensure_ascii=False)"'
```

OCR helper writes raw 0.5s samples; Python collapses them on text change.

## Output

- `<shortcode>.speech.json` — spoken segments, time order
- `<shortcode>.screen.json` — caption cues, one row per **text change**
- `<shortcode>.aligned.json` / `.aligned.txt` — each spoken line + the caption shown at that time
- `<shortcode>.srt` — speech and screen cues, sorted by start
- `<shortcode>.metadata.json`

## Delivery

Return the time-ordered aligned script first. Do not send frames, screenshots, or downloaded media to Telegram. Post captions and comments are not a transcript.

## Failure

- Invalid URLs fail before download.
- Anonymous download failure: try logged-in media fetch, then stop. Do not substitute comments.
- ASR/OCR errors name the failed stage.
- If only screen OCR exists, label it `화면 자막` and say speech was not recovered.
