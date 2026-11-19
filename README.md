# Soundwave Drop

A private, zero-cost localhost web app running on your Windows PC to inspect permitted/personal media links and download MP3 audio or MP4 video without ads or popups.

## Quick Start

1. Double-click `start.bat` (or run `uv run python -m app.run_server` in this folder).
2. Your browser opens `http://127.0.0.1:8000` (or the next free port in `8001–8010`).
3. Paste a link, click **Fetch**, pick **MP3** (bitrate) or **MP4** (resolution), and click **Download**.
4. Once saved to your browser Downloads folder, paste another link or click **Download another**.

## Maintenance

- Run tests: `uv run pytest -v`
- Update `yt-dlp` when sites change formats:
  ```powershell
  uv lock --upgrade-package yt-dlp
  uv sync
  ```
