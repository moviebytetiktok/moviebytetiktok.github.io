# Open Shorts (OpusClip-style) – Starter Kit

An open-source starter that replicates the *core workflow* of OpusClip’s **YouTube Shorts Maker**:

- Paste a video URL (YouTube, etc.) or upload a file
- Transcribe audio with Whisper (local model)
- Auto-select highlight segments (heuristic scoring)
- Cut into 15s vertical clips (1080x1920)
- Burn styled subtitles
- Download generated shorts

> This is a clean-room implementation. It does **not** copy any code, brand, or assets from OpusClip and is provided for educational use. You are responsible for API keys, licensing, and model downloads.

## Quick Start

### 1) Python backend
```bash
cd server
python -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# (First run will download a Whisper model – set WHISPER_MODEL if you want e.g. small.en/base/tiny)
# Start the API:
uvicorn main:app --reload --port 8000
```

### 2) Frontend
Open `web/index.html` in your browser (or serve with any static server). Set `API_BASE` in `web/app.js` if you run on a different host/port.

### 3) Workflow
1. Paste a URL (uses `yt-dlp`) **or** upload a file.
2. Click **Process** to start a job.
3. Poll the job and list clips; download .mp4 files from the browser.

## Features implemented in this starter
- URL/file ingest, stored under `./server/data/projects/<project_id>/`.
- Transcription via OpenAI Whisper (`openai-whisper` package, local inference).
- Highlighting heuristic (keyword/sentiment-ish scoring + speech density).
- 9:16 vertical format, center-crop (simple; pluggable auto-reframe hook included).
- Burn-in captions using ffmpeg + ASS (basic animation presets).
- Exports H.264 MP4 at 1080x1920 30fps (configurable).

## Not included (left as TODOs)
- Team workspace, billing, accounts.
- True AI “Virality Score” model; we provide a transparent heuristic placeholder.
- Generative B‑roll: a stub that you can back with stock APIs or generative video.
- Auto-post to YouTube/TikTok/IG (wire up their official APIs + OAuth).
- Full template system and brand kits (we include a simple theme config).

## Environment variables
- `WHISPER_MODEL` (default: `base`) – one of: tiny, base, small, medium, large, or the `.en` variants.
- `FFMPEG_PATH` – optional path to ffmpeg if not in PATH.

## Folder layout
```
server/
  main.py            # FastAPI app & routes
  processing.py      # video pipeline
  requirements.txt
  data/              # auto-created per project
web/
  index.html
  style.css
  app.js
```

## Legal
This project is an independent reimplementation of common video tooling features inspired by public marketing claims of OpusClip’s YouTube Shorts Maker. It does not reuse their code or assets. Respect third-party terms when ingesting URLs. Only process content you have rights to use.
