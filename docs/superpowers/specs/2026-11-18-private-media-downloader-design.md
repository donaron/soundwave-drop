# Private Local MP3/MP4 Media Downloader — Design Document

**Date:** 2026-11-18  
**Target Directory (post-approval):** `<workspace>/media-downloader`  
**Chosen Approach:** Option 1 — Local Python (`FastAPI` via `uv`) + native `yt-dlp` + local `ffmpeg` + clean vanilla HTML/CSS/JS web UI

---

## 1. Intent & Why

The user wants to stop using ad-heavy, popup-filled public downloader websites (like MP3Juice clones) and instead run a clean, private, zero-cost (`$0`) personal website on their Windows PC (`localhost`) where they can paste a media link (such as a YouTube URL for permitted, Creative Commons, royalty-free, or personal media), choose **MP3** or **MP4** (picking from available resolutions), download the file manually through their browser, and immediately download another file right afterward.

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
- **Private local web UI** served at `http://127.0.0.1:8000` (with a one-click `start.bat` launcher that starts the local server and opens the browser).
- **Paste-link workflow:** Paste an `http`/`https` media URL, inspect metadata (title, thumbnail, duration, and actual available MP4 resolutions), pick **MP3** or **MP4** + quality/resolution, and trigger download.
- **Live feedback:** Real-time progress updates (downloading percentage, converting/remuxing stage, completion, or clear error messages) streamed to the page.
- **Seamless repeat downloads:** Once a download finishes, the user can immediately clear/paste the next link and download another file without refreshing, while keeping a compact **Session Downloads** list below.
- **Zero cost & clean setup:** `$0` (no paid APIs or cloud servers), isolated dependencies via `uv`, and reuses the existing WinGet-installed `ffmpeg` on the user's PC.

### Non-Goals
- **No search engine / music discovery portal:** Users paste a URL directly; there is no keyword search, trending feed, or catalog scraping.
- **No accounts, public hosting, or remote access in v1:** Loopback-only (`127.0.0.1`).
- **No batch playlist or channel downloading in v1 *(clarified call)*:**
  - If a pasted URL points to a specific video that also carries playlist parameters (e.g., `watch?v=...&list=...`), `noplaylist=True` downloads only that single item and shows a small UI note.
  - If a pasted URL points **only** to a playlist, album, or channel (`_type == "playlist"` with no single item), `/api/inspect` detects it quickly via `extract_flat="in_playlist"` and rejects it with a clear message (`"Please paste a single video or track link — playlists and channels aren't supported"`).
- **No persistent server-side media library or database:** Files save to the user's normal browser Downloads folder; server temp storage is strictly transient.

### Anti-Goals (Failure Modes to Avoid)
- Any ads, popups, redirects, or multi-step fake download buttons.
- Modifying global Python packages or requiring manual CLI flags each time the user wants to run the app.
- Leaving large partial/converted media files accumulating indefinitely on disk.
- Bypassing DRM, paywalls, login walls, or CAPTCHA/bot gates (must fail transparently with a readable error instead).

---

## 3. Constraints & Environment Reality

- **Operating System:** Windows (verified local environment).
- **Verified Installed Tools:** `uv`, `winget`, `node`/`npm`, and `ffmpeg` (e.g., installed via WinGet under `%LOCALAPPDATA%\Microsoft\WinGet\Packages\...\bin\ffmpeg.exe`).
- **Dependency Isolation:** `yt-dlp` is not installed globally and must be managed inside the project's `uv` `.venv` (via `pyproject.toml` / `uv.lock`) alongside `fastapi` and `uvicorn[standard]`.
- **FFmpeg Discovery:** Server startup resolves `ffmpeg` in order: `FFMPEG_PATH` env var -> `shutil.which("ffmpeg")` -> recursive scan of `%LOCALAPPDATA%\Microsoft\WinGet\Packages` for `ffmpeg.exe`. If still not found, startup or inspect/download returns an explicit, actionable error instead of failing cryptically.
- **Security & Legal Boundaries:**
  - Server binds strictly to `127.0.0.1`.
  - Only `http://` and `https://` URLs are accepted; reject `file://`, `localhost`, loopback, link-local, and private RFC1918 IP targets before passing to `yt-dlp` (SSRF guard).
  - Never inject cookies/credentials from user browsers or attempt CAPTCHA/DRM/anti-bot circumvention.

---

## 4. Approaches Considered

1. **Option 1 — Local Python (`FastAPI` via `uv`) + native `yt-dlp` + local `ffmpeg` + Vanilla Web UI *(Chosen)***
   - *Why chosen:* `yt-dlp` is natively Python, giving direct structured metadata extraction, clean `progress_hooks`, reliable `ffmpeg` integration, zero Node frontend build toolchain, and trivial updates (`uv lock --upgrade-package yt-dlp && uv sync`) when platforms change.
   - *Tradeoff:* Requires starting the local server (mitigated by a double-click `start.bat` launcher).
2. **Option 2 — Node.js (`Express`) + standalone `yt-dlp.exe` + local `ffmpeg` *(Rejected)***
   - *Why rejected:* Requires installing and updating an external `yt-dlp.exe` separately and parsing CLI stdout strings for progress bars, which is more brittle.
3. **Option 3 — Prebuilt open-source container (e.g., MeTube via Docker) *(Rejected)***
   - *Why rejected:* Heavy Docker Desktop/WSL2 requirement on Windows and does not provide the user's requested minimal paste -> MP3/MP4 custom website.

---

## 5. Architecture & Technical Decisions

### 5.1 Project Structure
```text
media-downloader/
├── pyproject.toml
├── start.bat
├── app/
│   ├── __init__.py
│   ├── main.py          # FastAPI app, routes, static files, lifespan cleanup
│   ├── downloader.py    # URL validation, ffmpeg lookup, yt-dlp inspect & job runner
│   └── static/
│       ├── index.html   # Single-page UI
│       ├── styles.css   # Responsive light/dark styling
│       └── app.js       # Paste/fetch, MP3/MP4 toggle, SSE progress, auto-save, repeat flow
└── tests/
    └── test_api.py      # FastAPI + downloader unit/API tests (mocking yt-dlp/ffmpeg)
```

### 5.2 Backend API Contract
- `GET /` -> Serves `app/static/index.html` (and static assets under `/static/`).
- `POST /api/inspect`
  - **Request:** `{ "url": "<string>" }`
  - **Behavior:** Validates URL scheme/host; runs `yt-dlp` `extract_info(url, download=False)` with `noplaylist=True`, `extract_flat="in_playlist"`, `socket_timeout=15`, `quiet=True` inside a worker thread. If extracted result has `_type == "playlist"`, immediately returns HTTP `422` rejecting playlist/channel URLs.
  - **Response (`200`):**
    ```json
    {
      "url": "https://...",
      "title": "Video Title",
      "duration": 222,
      "thumbnail": "https://...",
      "extractor": "youtube",
      "is_playlist_url": false,
      "mp3_bitrates": [320, 192, 128],
      "mp4_heights": [2160, 1440, 1080, 720, 480, 360]
    }
    ```
    *Note on `mp4_heights`:* Derived from the video's actual detected format heights, matching standard tiers `[2160, 1440, 1080, 720, 480, 360]` that are available on the source (with `"best"` fallback if extractor metadata omits per-format heights).
  - **Errors (`400` / `422` / `502`):** JSON `{ "detail": "<human-readable reason>" }` (invalid URL, playlist/channel URL, unsupported site, unavailable/private/DRM-protected/bot-gated video).
- `POST /api/download`
  - **Request:** `{ "url": "<string>", "format": "mp3" | "mp4", "quality": "<string>" }`
    - Validates `quality` against `{"320", "192", "128"}` for `mp3` and `{"2160", "1440", "1080", "720", "480", "360", "best"}` for `mp4`.
  - **Behavior:** Creates a unique `job_id` (UUID4) and dedicated temp directory `.temp_jobs/<job_id>/`, enqueues background execution on a bounded `ThreadPoolExecutor(max_workers=2)`, and returns immediately.
  - **Response (`202`):** `{ "job_id": "<uuid>" }`
- `GET /api/jobs/{job_id}/events`
  - **Behavior:** `text/event-stream` (SSE) endpoint. Immediately emits the job's current state snapshot, then streams updates (`queued`, `downloading`, `converting`, `ready`, `error`) bridged thread-safely via `loop.call_soon_threadsafe` into an `asyncio.Queue` until terminal state (`ready` or `error`).
  - **Payload per event:**
    ```json
    {
      "job_id": "...",
      "status": "downloading",
      "progress": 64.5,
      "stage_label": "Downloading stream... 64%",
      "filename": null,
      "size_bytes": null,
      "error": null
    }
    ```
- `GET /api/jobs/{job_id}/file`
  - **Behavior:** Validates `job_id` exists and is `ready`, verifies resolved file path stays strictly inside `.temp_jobs/<job_id>/`, and returns `FileResponse` with `Content-Disposition` carrying both sanitized ASCII filename and RFC 5987 `filename*=UTF-8''...` so browser saves directly to Downloads.
- `POST /api/jobs/{job_id}/cancel`
  - **Behavior:** Marks job cancelled so `progress_hooks` raises `DownloadCancelled` cleanly and removes `.temp_jobs/<job_id>/`.

### 5.3 yt-dlp & FFmpeg Execution Rules
- **MP3:**
  - `format`: `"bestaudio/best"`
  - `postprocessors`: `[{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": quality}]`
- **MP4 (Resolution-First + H.264 Preference, Fast Remux):**
  - When `quality != "best"` (integer height `h`):
    - `format`: `f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"`
    - `format_sort`: `[f"res:{h}", "vcodec:h264", "acodec:m4a"]`
  - When `quality == "best"`:
    - `format`: `"bestvideo+bestaudio/best"`
    - `format_sort`: `["res", "vcodec:h264", "acodec:m4a"]`
  - `merge_output_format`: `"mp4"`
  - *Result:* User gets the exact resolution they chose (including true `1440p` / `2160p` 4K when available) without slow CPU re-encoding, while `1080p` and below still automatically prefer universally playable H.264 + AAC when available.
- **Common options:** `noplaylist=True`, `extract_flat="in_playlist"` (plus explicit check rejecting `_type == "playlist"` before downloading), `ffmpeg_location=<resolved_ffmpeg_dir>`, `outtmpl=str(job_dir / "%(title).100B.%(ext)s")`, `windowsfilenames=True`, `restrictfilenames=False`.
- **Progress Hook & Postprocessor Hook:**
  - During `downloading`: compute `downloaded_bytes / total_bytes` (or `total_bytes_estimate`), map to `0..90%`, emit status `"downloading"`.
  - During `finished` / `postprocessor_hooks` (`started`): emit status `"converting"`, progress `92..98%`, label `"Converting to MP3..."` / `"Finalizing MP4..."`.
  - On completion: locate the single resulting `.mp3`/`.mp4` output file in `job_dir`, record size and sanitized filename, emit `"ready"` at `100%`.

### 5.4 Temp Storage & Auto-Cleanup Policy
- All job artifacts live under `<project_root>/.temp_jobs/<job_id>/`.
- **On server startup (lifespan):** purge everything inside `.temp_jobs/` left over from any previous run.
- **During runtime:** keep completed job files for **15 minutes** (or maximum 5 most recent completed jobs, evicting older completed job folders) so `Save again` from the current session history works without leaking disk space. Run eviction whenever a new job starts and on periodic check.

### 5.5 Frontend UX & Repeat-Download Flow
- **Initial State:** Clean centered downloader card with URL input (`autofocus`), **Fetch** button (plus `Enter` key support), and hidden preview until a link is fetched.
- **Preview & Format Selection:**
  - Shows thumbnail (`referrerpolicy="no-referrer"`, falling back cleanly to an inline SVG artwork if thumbnail fails to load), title, duration (`MM:SS` or `HH:MM:SS`), and a small note if the URL had playlist params (`Downloading single video only`).
  - Toggle buttons: **MP3 (Audio)** vs **MP4 (Video)** — switching updates the quality/resolution dropdown (`320 / 192 / 128 kbps` for MP3; actual detected resolutions like `2160p (4K)`, `1440p`, `1080p`, `720p`, `480p`, `360p` for MP4) and button text (`Download MP3` / `Download MP4`).
  - When the user picks an MP4 resolution above `1080p` (`1440p` / `2160p`), display a brief subtle note below the selector (`"1440p/4K downloads quickly via remux (uses VP9/AV1 if H.264 isn't available)"`).
- **Download & Auto-Save:**
  - Clicking **Download** opens the SSE connection to `/api/jobs/{id}/events`, updates the progress bar and status message, and shows a **Cancel** action while active.
  - When `status === "ready"`, the frontend automatically triggers the browser download via `/api/jobs/{id}/file` (without navigating away from the SPA!), appends the entry to the **Recent Downloads (this session)** list below (with format/quality badge, size, and `Save again` link while still cached), and displays a **"Download another"** button while keeping the URL input unlocked so the user can immediately paste another link and download the next file.
- **Errors:** Inline dismissible error banner showing readable messages (e.g., invalid URL, playlist link rejected, site unavailable, protected/DRM stream).

### 5.6 Launcher (`start.bat`)
- Double-clicking `start.bat` starts `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000` (or finds the next available port `8001-8010` if `8000` is occupied, or uses `PORT` env var) and opens the matching URL in the user's default browser once healthy.

---

## 6. Decisions Made During Review (For Your Quick Check)

- **Playlist-only URLs rejected cleanly (`422`):** Pure playlist/channel links (e.g. `youtube.com/playlist?list=...`) return a friendly message asking for a single video/track URL instead of stalling or picking arbitrarily; single-video links that happen to carry `&list=...` still work and download just that one video.
- **MP4 resolution behavior (`format_sort`):** You can choose any available resolution detected on the video (`360p` through `2160p`); `1080p` and below automatically prefer standard H.264/AAC for maximum player compatibility, while `1440p`/`2160p` deliver full high-res MP4 quickly via remux (without slow CPU re-encoding).
- **Temp cleanup TTL:** Completed files stay cached in `.temp_jobs/` for up to 15 minutes (max 5 recent jobs) so `Save again` works, and clear automatically afterward and on startup.

---

## 7. What Is Left to the Builder

- Visual polish in `styles.css` (responsive spacing, clean adaptive dark/light palette, accessible focus states, button/badge styling).
- Exact implementation of thread-safe job state store, SSE queue fan-out (handling multiple readers or reconnects cleanly), and browser auto-save trigger (`<a download>` click or hidden iframe so SSE/DOM stay intact).
- Port-conflict handling strategy in `start.bat` / `app/main.py` (e.g., small Python launcher helper or `--port` probing).
- Comprehensive `pytest` coverage (`tests/test_api.py`) mocking `yt_dlp.YoutubeDL` and `ffmpeg` lookup so all routes, SSRF guards, format selection, SSE events, file streaming, cancellation, and cleanup are verified without live network calls.
