# YouTube → MP3 Downloader (FastAPI + yt-dlp)

A web-based MP3 extractor built with FastAPI, yt-dlp, and ffmpeg.  
Provides a clean browser UI, live download progress, filename metadata, cookies support for gated content, and automatic cleanup of old downloads.

---

## Features

- Paste a YouTube or YouTube Music link to download MP3.
- Live progress updates via **Server-Sent Events (SSE)**.
- Supports login/region-restricted content via `cookies.txt`.
- Filenames automatically generated from video metadata (title/artist) and sanitized.
- Automatic cleanup: deletes downloads older than 10 minutes.
- Run normally in development or as a **background service** using `systemd` or `nohup`.
- AI-assisted development: backend scaffolding, frontend UI, and documentation.

---

## Prerequisites

- Python 3.10+  
- `ffmpeg` installed and accessible in your PATH  
- Optional: `cookies.txt` exported from your browser (for gated/region-restricted content)

---

## Installation / Setup

```bash
# Clone repo
git clone https://github.com/yourusername/yt-mp3-downloader.git
cd yt-mp3-downloader

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

Usage
Run normally (development
uvicorn main:app --host 0.0.0.0 --port 8080 --reload

yt-mp3-downloader/
├─ main.py            # FastAPI backend and frontend
├─ README.md          # This file
├─ downloads/         # Temporary MP3 downloads (auto-cleaned)
├─ cookies.txt        # Optional cookies for gated content (DO NOT commit)

How AI Was Used

Backend scaffolding: FastAPI endpoints, SSE progress, background worker logic.

Frontend: HTML/CSS layout, progress bar behavior, SSE integration.

Documentation: README, systemd service instructions, .gitignore.

Slides & presentation: Generated slide text, speaker notes, demo flow.

Problem-solving: Filename sanitization, handling yt-dlp quirks, DRM workarounds.

Screenshots

UI Ready: input field to paste YouTube link.

Downloading (Live Progress): SSE-driven progress bar updates in real time.

Download Complete: Download link appears; MP3 saved in downloads/.

License

MIT License — free to use, modify, and distribute.
