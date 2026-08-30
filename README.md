# Instagram Reel Transcript

Instagram Reel 음성(Whisper)과 화면 자막(OCR, 텍스트 변경 시점에만 큐)을 두 트랙으로 뽑은 뒤, 시간순으로 정렬해 `음성`/`화면` 대본을 만듭니다.

에이전트 스킬(`SKILL.md`)과 CLI 스크립트가 같이 들어 있습니다.

## 설치

```bash
cp -R skills/instagram-reel-transcript ~/.gjc/agent/skills/
```

OCR는 macOS Vision(`ocr_reel_frames.swift`)을 씁니다. 음성은 Apple Silicon이면 `mlx-whisper`, 아니면 `uvx --from openai-whisper whisper`가 기본입니다. 다운로드는 `yt-dlp`입니다.

## CLI

```bash
python3 scripts/extract_instagram_reel_transcript.py \
  "https://www.instagram.com/reel/SHORTCODE/" \
  --out-dir artifacts/instagram-reel-transcripts
```

로컬 mp4:

```bash
python3 scripts/extract_instagram_reel_transcript.py \
  "https://www.instagram.com/reel/SHORTCODE/" \
  --video /path/to/reel.mp4 \
  --out-dir artifacts/instagram-reel-transcripts
```

Apple Silicon ASR:

```bash
python3 scripts/extract_instagram_reel_transcript.py \
  "https://www.instagram.com/reel/SHORTCODE/" \
  --out-dir artifacts/instagram-reel-transcripts \
  --asr-cmd '/tmp/whisper-venv/bin/python -c "from mlx_whisper import transcribe; import json; r=transcribe(\"{video}\", path_or_hf_repo=\"mlx-community/whisper-large-v3-turbo\", language=\"ko\"); json.dump(r, open(\"{asr_dir}/reel.json\",\"w\"), ensure_ascii=False)"'
```

## 출력

- `<shortcode>.speech.json` — 말한 구간
- `<shortcode>.screen.json` — 화면 자막, 텍스트가 바뀔 때만 한 줄
- `<shortcode>.aligned.json` / `.aligned.txt` — 각 음성 줄 + 그 시각의 화면 자막
- `<shortcode>.srt`
- `<shortcode>.metadata.json`

랜딩 페이지 캡션이나 댓글은 대본이 아닙니다.

## 테스트

```bash
python3 tests/test_extract_instagram_reel_transcript.py
```
