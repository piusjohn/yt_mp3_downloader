import os
import re
import time
import json
import asyncio
from datetime import datetime, timedelta
from urllib.parse import urlparse, parse_qs, urlunparse, urlencode

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import yt_dlp

app = FastAPI()

# ----- Config -----
DOWNLOAD_FOLDER = "downloads"
CLEANUP_AGE_MINUTES = 10
COOKIES_FILE = "cookies.txt"  # place your exported cookies here (optional)
# ------------------

progress_store = {}  # download_id -> {status, progress, filename, error}

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# Serve downloads folder
app.mount("/downloads", StaticFiles(directory=DOWNLOAD_FOLDER), name="downloads")


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """Remove unsafe filename characters and trim length."""
    name = re.sub(r"[\\\/\:\*\?\"\<\>\|]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = "".join(ch for ch in name if ch.isprintable())
    if len(name) > max_length:
        name = name[:max_length].rstrip()
    return name or "audio"


def clean_youtube_url(url: str) -> str:
    """Keep only the 'v' query parameter to avoid session noise (si=...) causing extractor loops."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    # handle youtu.be short links
    if parsed.netloc.endswith("youtu.be") and parsed.path:
        vid = parsed.path.lstrip("/")
        return urlunparse((parsed.scheme, "www.youtube.com", "/watch", "", urlencode({"v": vid}), ""))
    if 'v' in query:
        new_q = urlencode({'v': query['v'][0]})
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', new_q, ''))
    return url


async def cleanup_old_files_loop():
    """Background task to remove old files."""
    while True:
        now = datetime.now()
        cutoff = now - timedelta(minutes=CLEANUP_AGE_MINUTES)
        try:
            for fname in os.listdir(DOWNLOAD_FOLDER):
                fpath = os.path.join(DOWNLOAD_FOLDER, fname)
                if os.path.isfile(fpath):
                    if datetime.fromtimestamp(os.path.getmtime(fpath)) < cutoff:
                        try:
                            os.remove(fpath)
                        except Exception:
                            pass
        except Exception:
            pass
        await asyncio.sleep(300)  # run every 5 minutes


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(cleanup_old_files_loop())


@app.get("/", response_class=HTMLResponse)
async def main_page():
    # Full HTML UI with SSE progress handling
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <title>YouTube → MP3</title>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <style>
    :root { font-family: Inter, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial; }
    body { background:#f6f8fb; color:#0f1724; display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; padding:20px; }
    .card { width:100%; max-width:820px; background:white; border-radius:12px; box-shadow: 0 6px 22px rgba(15,23,36,0.08); padding:28px; }
    h1 { margin:0 0 6px 0; font-size:20px; }
    p.lead { margin:0 0 18px 0; color:#475569; }
    .input-row { display:flex; gap:10px; margin-bottom:12px; }
    input[type="text"] { flex:1; padding:12px 14px; border-radius:10px; border:1px solid #e6e9ef; font-size:15px; }
    button { padding:10px 14px; border-radius:10px; border:0; background:#0ea5a4; color:white; font-weight:600; cursor:pointer; }
    button:disabled { opacity:0.6; cursor:not-allowed; }
    .progress-wrap { margin-top:16px; }
    .progress { height:14px; background:#eef2ff; border-radius:999px; overflow:hidden; }
    .progress > div { height:100%; width:0%; background: linear-gradient(90deg,#06b6d4,#0ea5a4); text-align:center; font-size:12px; color:white; line-height:14px; white-space:nowrap; transition:width .2s ease; }
    .status { margin-top:8px; color:#334155; font-size:13px; }
    .result { margin-top:16px; }
    a.download-link { display:inline-block; background:#111827; color:white; padding:8px 12px; border-radius:8px; text-decoration:none; }
    .error { color:#b91c1c; }
    footer { margin-top:18px; color:#94a3b8; font-size:12px; }
    .small { font-size:13px; color:#64748b; }
  </style>
</head>
<body>
  <div class="card">
    <h1>🎵 YouTube → MP3</h1>
    <p class="lead">Paste a YouTube or YouTube Music link and get an MP3 (uses your cookies.txt for paid/region-locked content).</p>

    <form id="dlForm" onsubmit="startDownload(event)">
      <div class="input-row">
        <input id="url" type="text" placeholder="https://www.youtube.com/watch?v=..." required />
        <button id="dlBtn" type="submit">Download MP3</button>
      </div>
    </form>

    <div class="progress-wrap" id="progressWrap" style="display:none;">
      <div class="progress"><div id="progressBar">0%</div></div>
      <div class="status" id="statusText">Waiting...</div>
    </div>

    <div class="result" id="result"></div>
    <footer>Files auto-delete after <span id="cleanupSpan">10</span> minutes. <span class="small">Ensure <code>cookies.txt</code> is present for gated content.</span></footer>
  </div>

<script>
async function startDownload(e) {
  e.preventDefault();
  const url = document.getElementById('url').value.trim();
  if (!url) return;
  document.getElementById('result').innerHTML = '';
  document.getElementById('progressWrap').style.display = 'block';
  document.getElementById('progressBar').style.width = '0%';
  document.getElementById('progressBar').textContent = '0%';
  document.getElementById('statusText').textContent = 'Contacting server...';
  document.getElementById('dlBtn').disabled = true;

  try {
    const res = await fetch('/start_download', {
      method: 'POST',
      body: new URLSearchParams({ url })
    });
    const data = await res.json();
    if (!res.ok) {
      document.getElementById('statusText').innerHTML = '<span class="error">' + (data.error || 'Unknown error') + '</span>';
      document.getElementById('dlBtn').disabled = false;
      return;
    }

    const { download_id, filename } = data;
    // open SSE stream
    const evtSource = new EventSource(`/progress/${encodeURIComponent(download_id)}`);
    evtSource.onmessage = function(event) {
      try {
        const msg = JSON.parse(event.data);
        const pct = (msg.progress !== null && msg.progress !== undefined) ? msg.progress : 0;
        const status = msg.status || '';
        document.getElementById('progressBar').style.width = (pct||0) + '%';
        document.getElementById('progressBar').textContent = (pct||0) + '%';
        document.getElementById('statusText').textContent = status;

        if (msg.status === 'done') {
          evtSource.close();
          const link = document.createElement('a');
          link.href = `/downloads/${encodeURIComponent(msg.filename || filename)}`;
          link.className = 'download-link';
          link.textContent = '⬇ Download MP3';
          link.setAttribute('download', msg.filename || filename);
          document.getElementById('result').innerHTML = '';
          document.getElementById('result').appendChild(link);
          document.getElementById('statusText').textContent = 'Completed ✔';
          document.getElementById('progressBar').style.width = '100%';
          document.getElementById('progressBar').textContent = '100%';
          document.getElementById('dlBtn').disabled = false;
        }

        if (msg.status === 'error') {
          evtSource.close();
          document.getElementById('result').innerHTML = '<div class="error">Error: ' + (msg.error || 'Unknown') + '</div>';
          document.getElementById('statusText').textContent = 'Failed';
          document.getElementById('dlBtn').disabled = false;
        }
      } catch (err) {
        console.error('Failed parsing SSE message', err, event.data);
      }
    };

    evtSource.onerror = function(e) {
      // keep UI informed but don't spam
      document.getElementById('statusText').textContent = 'Connection lost or finished.';
    };

  } catch (err) {
    document.getElementById('statusText').textContent = 'Request failed';
    document.getElementById('result').innerHTML = '<div class="error">' + err.toString() + '</div>';
    document.getElementById('dlBtn').disabled = false;
  }
}
</script>
</body>
</html>
"""


@app.post("/start_download")
async def start_download(url: str = Form(...)):
    """Start a background download and return a download_id and filename."""
    try:
        # Normalize music.youtube.com and clean URL
        url = url.replace("music.youtube.com", "www.youtube.com")
        url = clean_youtube_url(url)

        # Probe for metadata
        ydl_probe_opts = {
            "format": "bestaudio",
            "cookiefile": COOKIES_FILE if os.path.exists(COOKIES_FILE) else None,
            "noplaylist": True,
            "quiet": True,
            "skip_download": True,
        }
        ydl_probe_opts = {k: v for k, v in ydl_probe_opts.items() if v is not None}

        with yt_dlp.YoutubeDL(ydl_probe_opts) as ydl_probe:
            info = ydl_probe.extract_info(url, download=False)

        if not isinstance(info, dict):
            return JSONResponse({"error": "Failed to extract video info. The extractor returned unexpected data."}, status_code=400)

        raw_title = info.get("title") or info.get("alt_title") or "audio"
        safe_title = sanitize_filename(raw_title)
        final_filename = f"{safe_title}.mp3"

        download_id = f"{safe_title}-{int(time.time())}"

        progress_store[download_id] = {
            "status": "queued",
            "progress": 0,
            "filename": final_filename,
            "error": None,
        }

        loop = asyncio.get_event_loop()
        # pass the safe_title base (without .mp3) to the worker
        loop.run_in_executor(None, run_yt_dlp_download, download_id, url, safe_title)

        return JSONResponse({"download_id": download_id, "filename": final_filename})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


def run_yt_dlp_download(download_id: str, url: str, safe_title_base: str):
    """Blocking function executed in a thread to run yt-dlp and update progress_store."""
    try:
        # Template: downloads/<safe_title>.<ext>
        outtmpl = os.path.join(DOWNLOAD_FOLDER, f"{safe_title_base}.%(ext)s")

        def progress_hook(d):
            try:
                status = d.get("status")
                ps = progress_store.get(download_id)
                if not ps:
                    return
                if status == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate")
                    downloaded = d.get("downloaded_bytes", 0)
                    if total and total > 0:
                        pct = int(downloaded / total * 100)
                        ps["status"] = "downloading"
                        ps["progress"] = pct
                    else:
                        ps["status"] = "downloading"
                elif status == "finished":
                    ps["status"] = "processing"
                    ps["progress"] = 95
            except Exception:
                pass

        ydl_opts = {
            "format": "bestaudio",
            "outtmpl": outtmpl,
            "cookiefile": COOKIES_FILE if os.path.exists(COOKIES_FILE) else None,
            "progress_hooks": [progress_hook],
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
            "noplaylist": True,
            "quiet": True,
            "merge_output_format": "mp3",
        }
        ydl_opts = {k: v for k, v in ydl_opts.items() if v is not None}

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        final_name = f"{safe_title_base}.mp3"
        ps = progress_store.get(download_id)
        if ps is not None:
            ps["status"] = "done"
            ps["progress"] = 100
            ps["filename"] = final_name
    except Exception as e:
        ps = progress_store.get(download_id)
        if ps is not None:
            ps["status"] = "error"
            ps["error"] = str(e)
            ps["progress"] = ps.get("progress", 0)


@app.get("/progress/{download_id}")
async def progress_stream(download_id: str):
    """SSE stream of progress updates for the given download_id."""
    async def event_generator():
        last_sent = None
        for _ in range(0, 3600 * 24):  # safety break after a long time (~24h)
            ps = progress_store.get(download_id)
            if ps is None:
                payload = {"status": "error", "error": "No such download ID."}
                yield f"data: {json.dumps(payload)}\n\n"
                return
            payload = {
                "status": ps.get("status"),
                "progress": ps.get("progress"),
                "filename": ps.get("filename"),
                "error": ps.get("error"),
            }
            if json.dumps(payload) != last_sent:
                last_sent = json.dumps(payload)
                yield f"data: {json.dumps(payload)}\n\n"
            if ps.get("status") in ("done", "error"):
                return
            await asyncio.sleep(0.5)
    return StreamingResponse(event_generator(), media_type="text/event-stream")

