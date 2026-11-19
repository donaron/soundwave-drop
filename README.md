# Soundwave Drop

A private, zero-cost (`$0`) localhost web app for Windows to inspect permitted media links and download standard **MP3** or **MP4** files without ads, popups, or external trackers.

## Features

- **Paste & Preview:** Inspects single media links (title, thumbnail, duration, and detected video resolutions from `144p` up to `2160p` / `4K`, including vertical video).
- **MP3 & MP4 Output:** Choose MP3 bitrate (`320`, `192`, `128` kbps) or any available MP4 resolution (resolution-first selection with H.264/AAC preference at `1080p` and below).
- **Live Progress & Repeat Workflow:** Streams real-time progress via Server-Sent Events (SSE), saves straight to your browser's **Downloads** folder, keeps a **Recent Downloads** session list, and stays ready for your next link via **Download another**.
- **10 Built-In Color Designs:** Switch instantly between 10 light and dark studio themes (persisted in `localStorage`).
- **Automatic Cleanup:** Working files live strictly in `.temp_jobs/` and clean up automatically after 15 minutes (max 5 cached recent jobs) and on server startup.

## Prerequisites (Windows)

- **[uv](https://docs.astral.sh/uv/)** (handles Python and isolated `.venv` dependencies automatically)
- **ffmpeg** (installed on `PATH`, installed via `winget install Gyan.FFmpeg`, or set via the `FFMPEG_PATH` environment variable)

## Setup & Quick Start

1. Clone this repository and install dependencies into an isolated `.venv`:
   ```powershell
   git clone <your-repo-url>
   cd media-downloader
   uv sync
   ```
2. Double-click `start.bat` (or run `uv run python -m app.run_server`).
3. Your browser opens `http://127.0.0.1:8000` (or the next free port in `8001–8010`).
4. Paste a link, click **Fetch**, pick **MP3** or **MP4**, and click **Download**.

## Maintenance & Tests

- Run the automated test suite:
  ```powershell
  uv run pytest -v
  ```
- Update `yt-dlp` when supported sites change formats:
  ```powershell
  uv lock --upgrade-package yt-dlp
  uv sync
  ```

## Scope & Permitted Use

Intended for personal use with permitted, royalty-free, Creative Commons, or user-owned media. Soundwave Drop binds strictly to `127.0.0.1`, validates public `http`/`https` links only, rejects playlists/channels, and does not bypass DRM, logins, paywalls, or anti-bot protections.
