# Soundwave Drop

A private, zero-cost (`$0`) localhost web app for Windows to inspect permitted media links and download standard **MP3** or **MP4** files without ads, popups, or trackers.

## Features

- **Paste & Preview:** Inspects single media links (title, thumbnail, duration, and detected video resolutions from `144p` up to `2160p` / `4K`, including vertical video).
- **MP3 & MP4 Output:** Choose MP3 bitrate (`320`, `192`, `128` kbps) or any available MP4 resolution (resolution-first selection with H.264/AAC preference at `1080p` and below).
- **Live Progress & Repeat Workflow:** Streams real-time progress via Server-Sent Events (SSE), saves straight to your browser's **Downloads** folder, keeps a **Recent Downloads** session list, and stays ready for your next link via **Download another**.
- **10 Built-In Color Designs:** Switch instantly between 10 light and dark studio themes (saved locally in `localStorage`).
- **Automatic Cleanup:** Temporary working files live in `.temp_jobs/` and clean up automatically after 15 minutes (max 5 cached recent jobs) and on server startup.

## Prerequisites (Windows)

Install these tools once before setting up the repository:

1. **Git** (if not installed):
   ```powershell
   winget install Git.Git
   ```
2. **uv** (manages Python and the project's isolated `.venv` automatically):
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
3. **ffmpeg** (used for MP3 extraction and MP4 merging):
   ```powershell
   winget install Gyan.FFmpeg
   ```
   *(The app automatically detects `ffmpeg` on `PATH`, inside WinGet Packages, or via the `FFMPEG_PATH` environment variable.)*

## Installation & Quick Start

1. **Clone the repository:**
   ```powershell
   git clone https://github.com/donaron/soundwave-drop.git
   cd soundwave-drop
   ```
2. **Install dependencies into an isolated environment:**
   ```powershell
   uv sync
   ```
3. **Start the app:**
   - Double-click **`start.bat`**, or run:
     ```powershell
     uv run python -m app.run_server
     ```
4. **Use in your browser:**
   - Your browser opens `http://127.0.0.1:8000` automatically (falling back to `8001–8010` if port `8000` is busy).
   - Paste a link, click **Fetch**, pick **MP3** or **MP4**, and click **Download**.
   - Files save directly to your browser **Downloads** folder, and you can paste another link or click **Download another** immediately.

## Maintenance & Tests

- **Run the automated test suite:**
  ```powershell
  uv run pytest -v
  ```
- **Update `yt-dlp` when supported sites change formats:**
  ```powershell
  uv lock --upgrade-package yt-dlp
  uv sync
  ```

## Scope & Permitted Use

Intended for personal offline use with permitted, royalty-free, Creative Commons, or user-owned media. Soundwave Drop binds strictly to `127.0.0.1`, accepts public `http`/`https` links only, rejects playlists/channels, and does not bypass DRM, logins, paywalls, or anti-bot protections.
