# Private Local MP3/MP4 Media Downloader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a private, zero-cost Windows localhost web app where the user pastes a permitted media URL, previews metadata, selects MP3 (bitrate) or MP4 (any detected resolution up to 4K), watches live progress, saves the file, and immediately downloads another file.

**Architecture:** A local FastAPI server (managed in an isolated `uv` virtual environment) serves a static vanilla HTML/CSS/JS single-page UI on `127.0.0.1` and coordinates background `yt-dlp` + local `ffmpeg` jobs inside `.temp_jobs/<job_id>/`. Real-time progress streams to the browser via Server-Sent Events (SSE), triggers automatic browser file saving when ready, and cleans up temporary folders automatically via startup purge and a 15-minute / max-5 completed-job retention policy.

**Tech Stack:** Python 3.12+ (via `uv`), FastAPI, Uvicorn, `yt-dlp` (Python API), local `ffmpeg`, Vanilla HTML/CSS/JS, `pytest` + `httpx` (for tests).

**Spec:** `docs/superpowers/specs/2026-11-18-private-media-downloader-design.md`

---

## Global Constraints

- Operating System: Windows, server binds strictly to `127.0.0.1` (`port 8000` with fallback `8001`–`8010`).
- Zero cost (`$0`) and isolated dependencies via `uv` (`pyproject.toml` + `uv.lock`); never run global `pip install`.
- Reuse local `ffmpeg` via `FFMPEG_PATH` -> `shutil.which("ffmpeg")` -> recursive scan of `%LOCALAPPDATA%\Microsoft\WinGet\Packages`.
- Accept only `http://` and `https://` URLs; block `file://`, `localhost`, loopback, link-local, and private RFC1918 IP addresses (SSRF guard).
- Single-item only (`noplaylist=True`, `extract_flat="in_playlist"`); reject pure playlist/channel links (`_type == "playlist"`) with HTTP `422`.
- Never inject browser cookies or bypass DRM, logins, paywalls, or CAPTCHAs.
- Store working files strictly under `.temp_jobs/<job_id>/`, purge `.temp_jobs/` on server startup, and evict completed jobs after 15 minutes or >5 recent completed jobs.

## Review Focus

- **Windows-illegal / non-ASCII / long filenames:** A video title like `Song: Live / 2026? ★ | Official` must not crash `yt-dlp` on Windows or break `Content-Disposition`; `build_content_disposition` must emit a sanitized ASCII fallback + valid RFC 5987 `filename*=UTF-8''...` (covered in Task 2 and Task 4).
- **SSRF via scheme or local/private DNS resolution:** URLs like `file:///C:/...`, `http://127.0.0.1:8000`, `http://localhost/`, or hostnames resolving to private IPs must be rejected before invoking `yt-dlp` (covered in Task 2).
- **Playlist-only URL vs single-video URL with `&list=`:** `youtube.com/playlist?list=...` (`_type == "playlist"`) must fail fast with HTTP `422`, whereas `watch?v=abc&list=xyz` must inspect the single video with `is_playlist_url=True` (covered in Task 2, Task 3, and Task 4).
- **SSE reconnect or fast-completing job race:** Connecting to `GET /api/jobs/{job_id}/events` after a job already finished (`ready` or `error`) must immediately send the terminal snapshot and close without hanging, and unknown `job_id` must return `404` (covered in Task 4).
- **Missing `ffmpeg` or `yt-dlp` `DownloadError` (DRM / geo-block / unavailable):** Must transition background jobs cleanly to `"error"` with a readable message (never stall at 0% or crash silently) and return `422`/`502` from `/api/inspect` (covered in Task 2, Task 3, and Task 4).

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml`, `.gitignore`, `README.md` | Project metadata, `uv` dependencies, ignore `.venv`/`.temp_jobs`, usage notes |
| `app/__init__.py`, `tests/__init__.py` | Package markers |
| `app/validators.py` | URL & SSRF validation, playlist parameter detection, format/quality allowlists, `Content-Disposition` builder |
| `app/ffmpeg_locator.py` | Locates `ffmpeg.exe` via env var, `PATH`, or WinGet packages directory |
| `app/media_service.py` | `inspect_media`, `yt-dlp` MP3/MP4 option builders, `JobManager` (thread pool, SSE queues, cancellation, `.temp_jobs/` cleanup) |
| `app/main.py` | FastAPI factory, lifespan cleanup, API routes, static mount |
| `app/run_server.py`, `start.bat` | Free-port discovery (`8000`–`8010`), health wait, browser launch |
| `app/static/index.html`, `styles.css`, `app.js` | Single-page UI: paste/fetch, preview card, MP3/MP4 + resolution selector, SSE progress, auto-save, repeat downloads, session history |
| `tests/test_validators.py`, `tests/test_media_service.py`, `tests/test_api.py` | Unit and API test suites mocking `yt-dlp` and `ffmpeg` |

---

### Task 1: Project Scaffolding & `uv` Environment

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `app/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/test_smoke.py`

**Interfaces:**
- Produces: runnable `uv` environment with `fastapi`, `uvicorn[standard]`, `yt-dlp`, `pytest`, `httpx`, and initialized Git repo.

- [ ] **Step 1: Create `.gitignore`, `pyproject.toml`, and empty package markers**

Write `.gitignore` ignoring `.venv/`, `.temp_jobs/`, `__pycache__/`, `.pytest_cache/`, `*.pyc`, and `.env`.
Write `pyproject.toml`:
```toml
[project]
name = "media-downloader"
version = "0.1.0"
description = "Private local MP3/MP4 web downloader"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.115.0",
  "uvicorn[standard]>=0.32.0",
  "yt-dlp>=2025.1.0",
]

[dependency-groups]
dev = [
  "pytest>=8.3.0",
  "httpx>=0.28.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
```
Create empty `app/__init__.py` and `tests/__init__.py`.

- [ ] **Step 2: Write smoke test in `tests/test_smoke.py`**

```python
def test_dependencies_importable():
    import fastapi
    import uvicorn
    import yt_dlp

    assert fastapi.__version__
    assert uvicorn.__version__
    assert yt_dlp.version.__version__
```

- [ ] **Step 3: Initialize Git repository and sync `uv` environment**

Run:
```powershell
git init
uv sync
```
Expected: `.venv/` and `uv.lock` created with exit code 0.

- [ ] **Step 4: Run smoke test to verify environment passes**

Run: `uv run pytest tests/test_smoke.py -v`
Expected: `1 passed`

- [ ] **Step 5: Commit**

```powershell
git add .gitignore pyproject.toml uv.lock app/__init__.py tests/__init__.py tests/test_smoke.py
git commit -m "chore: scaffold project and uv environment"
```

---

### Task 2: URL Safety Guard, Filename Sanitizer & FFmpeg Discovery

**Files:**
- Create: `app/validators.py`
- Create: `app/ffmpeg_locator.py`
- Test: `tests/test_validators.py`

**Interfaces:**
- Produces in `app/validators.py`:
  - `class ValidationError(ValueError)`
  - `validate_public_url(url: str, resolver: Callable = socket.getaddrinfo) -> str`
  - `has_playlist_context(url: str) -> bool`
  - `validate_download_request(fmt: str, quality: str) -> tuple[str, str]`
  - `build_content_disposition(filename: str) -> str`
- Produces in `app/ffmpeg_locator.py`:
  - `resolve_ffmpeg_dir(env: Mapping[str, str] | None = None, which_fn: Callable = shutil.which, winget_root: Path | None = None) -> Path`

- [ ] **Step 1: Write failing tests in `tests/test_validators.py`**

```python
from pathlib import Path
import socket
import pytest

from app.ffmpeg_locator import resolve_ffmpeg_dir
from app.validators import (
    ValidationError,
    build_content_disposition,
    has_playlist_context,
    validate_download_request,
    validate_public_url,
)


def _public_resolver(host, port, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


def test_validate_public_url_accepts_https_and_trims():
    assert (
        validate_public_url("  https://www.youtube.com/watch?v=abc123  ", resolver=_public_resolver)
        == "https://www.youtube.com/watch?v=abc123"
    )


@pytest.mark.parametrize(
    "bad_url",
    [
        "",
        "not-a-url",
        "file:///C:/Windows/System32/drivers/etc/hosts",
        "javascript:alert(1)",
        "http://localhost:8000/test",
        "http://127.0.0.1/test",
        "http://[::1]/test",
        "http://169.254.169.254/latest/meta-data",
        "http://192.168.1.10/video",
        "http://10.0.0.5/video",
    ],
)
def test_validate_public_url_rejects_unsafe_schemes_and_private_hosts(bad_url):
    with pytest.raises(ValidationError):
        validate_public_url(bad_url, resolver=_public_resolver)


def test_validate_public_url_rejects_dns_resolving_to_loopback():
    def local_resolver(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    with pytest.raises(ValidationError):
        validate_public_url("https://rebind.example.com/watch?v=1", resolver=local_resolver)


def test_has_playlist_context():
    assert has_playlist_context("https://www.youtube.com/watch?v=abc&list=PL123") is True
    assert has_playlist_context("https://www.youtube.com/playlist?list=PL123") is True
    assert has_playlist_context("https://www.youtube.com/watch?v=abc") is False


def test_validate_download_request_allowlists():
    assert validate_download_request("MP3", "320") == ("mp3", "320")
    assert validate_download_request("mp4", "2160") == ("mp4", "2160")
    assert validate_download_request("mp4", "best") == ("mp4", "best")
    with pytest.raises(ValidationError):
        validate_download_request("wav", "320")
    with pytest.raises(ValidationError):
        validate_download_request("mp3", "1080")
    with pytest.raises(ValidationError):
        validate_download_request("mp4", "9999")


def test_build_content_disposition_sanitizes_windows_illegal_and_unicode():
    header = build_content_disposition('Song: Live / 2026? ★ | "Official".mp3')
    assert "attachment;" in header
    assert 'filename="' in header
    assert "filename*=UTF-8''" in header
    ascii_part = header.split('filename="')[1].split('"')[0]
    for ch in '<>:"/\\|?*':
        assert ch not in ascii_part
    assert ascii_part.endswith(".mp3")


def test_resolve_ffmpeg_dir_precedence_and_missing(tmp_path):
    custom_exe = tmp_path / "custom" / "ffmpeg.exe"
    custom_exe.parent.mkdir(parents=True)
    custom_exe.write_bytes(b"")

    winget_exe = tmp_path / "winget" / "Gyan.FFmpeg" / "bin" / "ffmpeg.exe"
    winget_exe.parent.mkdir(parents=True)
    winget_exe.write_bytes(b"")

    assert resolve_ffmpeg_dir(env={"FFMPEG_PATH": str(custom_exe)}, which_fn=lambda _: None, winget_root=tmp_path / "winget") == custom_exe.parent
    assert resolve_ffmpeg_dir(env={}, which_fn=lambda _: str(custom_exe), winget_root=tmp_path / "winget") == custom_exe.parent
    assert resolve_ffmpeg_dir(env={}, which_fn=lambda _: None, winget_root=tmp_path / "winget") == winget_exe.parent

    with pytest.raises(FileNotFoundError):
        resolve_ffmpeg_dir(env={}, which_fn=lambda _: None, winget_root=tmp_path / "missing")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_validators.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ffmpeg_locator'` / `app.validators`.

- [ ] **Step 3: Implement `app/validators.py` and `app/ffmpeg_locator.py`**

Implement:
- `app/validators.py`:
  - `validate_public_url(url: str, resolver: Callable = socket.getaddrinfo) -> str`: strip whitespace, enforce `http`/`https`, require `parsed.hostname`, block literal `"localhost"` / `*.localhost` / `*.local`, validate literal IP with `ipaddress.ip_address` (if IP literal), else resolve via `resolver(host, port or 80, type=socket.SOCK_STREAM)` and reject any resolved address where `ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified`. Note: if DNS resolution raises `socket.gaierror`, raise `ValidationError("Could not resolve URL hostname")`.
  - `has_playlist_context(url: str) -> bool`: check `parse_qs(parsed.query)` for `"list"` or path ending in `"/playlist"`.
  - `validate_download_request(fmt: str, quality: str) -> tuple[str, str]`: normalize `fmt.strip().lower()`, `quality.strip().lower()`; validate `mp3` in `{"320", "192", "128"}` and `mp4` in `{"2160", "1440", "1080", "720", "480", "360", "best"}`.
  - `build_content_disposition(filename: str) -> str`: strip control chars and Windows illegal characters `<>:"/\|?*`, collapse spaces, clamp stem so total filename length <= 120 preserving extension, build ASCII-only fallback (`ascii_name`) and RFC 5987 UTF-8 encoded `urllib.parse.quote(utf8_name, safe="")` returning `f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quoted}'`.
- `app/ffmpeg_locator.py`:
  - `resolve_ffmpeg_dir(env: Mapping[str, str] | None = None, which_fn: Callable = shutil.which, winget_root: Path | None = None) -> Path`: check `FFMPEG_PATH` (accept file or directory containing `ffmpeg.exe`/`ffmpeg`), then `which_fn("ffmpeg")`, then `winget_root` (default `Path(env.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"`) searching `rglob("ffmpeg.exe")` sorted deterministically; raise `FileNotFoundError("ffmpeg executable was not found. Install ffmpeg or set FFMPEG_PATH.")` if absent.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_validators.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add app/validators.py app/ffmpeg_locator.py tests/test_validators.py
git commit -m "feat: add URL safety validation, filename header sanitization, and ffmpeg locator"
```

---

### Task 3: `yt-dlp` Inspector, Job Manager & Temp Cleanup Engine

**Files:**
- Create: `app/media_service.py`
- Test: `tests/test_media_service.py`

**Interfaces:**
- Consumes: `app/validators.py` (`ValidationError`, `validate_public_url`, `has_playlist_context`, `validate_download_request`), `app/ffmpeg_locator.py` (`resolve_ffmpeg_dir`)
- Produces in `app/media_service.py`:
  - `class MediaInspectError(Exception)` (`status_code: int`, `detail: str`)
  - `class DownloadCancelled(Exception)`
  - `inspect_media(url: str, ydl_factory: Callable = YoutubeDL) -> dict`
  - `build_ydl_options(fmt: str, quality: str, job_dir: Path, ffmpeg_dir: Path) -> dict`
  - `@dataclass class JobState`: `job_id: str`, `url: str`, `fmt: str`, `quality: str`, `status: str`, `progress: float`, `stage_label: str`, `filename: str | None`, `file_path: Path | None`, `size_bytes: int | None`, `error: str | None`, `created_at: float`, `completed_at: float | None`, `cancelled: bool` (plus `.to_event_dict() -> dict`)
  - `class JobManager` with `startup_purge()`, `evict_expired()`, `start_job(url, fmt, quality, loop=None) -> JobState`, `get_job(job_id) -> JobState | None`, `subscribe(job_id) -> tuple[JobState | None, asyncio.Queue]`, `unsubscribe(job_id, queue)`, `cancel_job(job_id) -> bool`, `shutdown()`

- [ ] **Step 1: Write failing tests in `tests/test_media_service.py`**

Write tests verifying:
1. `test_inspect_media_returns_filtered_mp4_heights_and_metadata`: mock `YoutubeDL` returning `title`, `duration`, `thumbnail`, `extractor`, `formats` with heights `[360, 480, 720, 1080, 1440]`; verify `mp4_heights == [1440, 1080, 720, 480, 360]`, `mp3_bitrates == [320, 192, 128]`, and `noplaylist=True`, `extract_flat="in_playlist"` passed to `YoutubeDL`.
2. `test_inspect_media_falls_back_to_best_when_no_heights_present`: mock formats lacking `height`; verify `mp4_heights == ["best"]`.
3. `test_inspect_media_rejects_playlist_only_url`: mock `extract_info` returning `{"_type": "playlist", "entries": [...]}`; assert raises `MediaInspectError` with `status_code == 422`.
4. `test_inspect_media_allows_single_video_with_list_param`: mock single video result for `https://www.youtube.com/watch?v=abc&list=PL123`; assert `is_playlist_url is True` and returns video metadata.
5. `test_build_ydl_options_mp3_and_mp4_resolution_first`:
   - MP3 `320`: `format == "bestaudio/best"`, `FFmpegExtractAudio` with `preferredcodec == "mp3"`, `preferredquality == "320"`.
   - MP4 `1440`: `format == "bestvideo[height<=1440]+bestaudio/best[height<=1440]/best"`, `format_sort == ["res:1440", "vcodec:h264", "acodec:m4a"]`, `merge_output_format == "mp4"`.
   - MP4 `best`: `format == "bestvideo+bestaudio/best"`, `format_sort == ["res", "vcodec:h264", "acodec:m4a"]`, `merge_output_format == "mp4"`.
6. `test_job_manager_lifecycle_ready_and_file_location(tmp_path)`: fake `YoutubeDL` fires `progress_hooks` (`downloading` 50%, `finished`), `postprocessor_hooks` (`started`), and writes `track.mp3` in `job_dir`; verify `JobState` reaches `status == "ready"`, `progress == 100.0`, `filename == "track.mp3"`, and `file_path.exists()`.
7. `test_job_manager_error_on_download_error_or_missing_ffmpeg(tmp_path)`: fake `YoutubeDL` raising `DownloadError("Sign in to confirm")` and separately `ffmpeg_resolver` raising `FileNotFoundError`; verify job ends cleanly with `status == "error"` and readable `error` message.
8. `test_job_manager_cancel_removes_temp_dir_and_stops_job(tmp_path)`: fake `YoutubeDL` blocks on an event inside hook, `cancel_job(job_id)` is called -> hook raises `DownloadCancelled` -> temp job directory is cleaned up.
9. `test_job_manager_startup_purge_and_eviction(tmp_path)`: create stale directory in `.temp_jobs/stale/`, verify `startup_purge()` deletes it; create 6 completed jobs or 1 expired job past `ttl_seconds`, verify `evict_expired()` trims down to <= `max_cached_completed` (5) and removes expired directories.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_media_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.media_service'`.

- [ ] **Step 3: Implement `app/media_service.py`**

Key implementation details (beyond what tests already pin):
- `STANDARD_MP4_HEIGHTS = [2160, 1440, 1080, 720, 480, 360]`
- `inspect_media`: runs `validate_public_url(url)` first (catching `ValidationError` -> `MediaInspectError(400, str(exc))`). Calls `ydl_factory({"quiet": True, "no_warnings": True, "noplaylist": True, "extract_flat": "in_playlist", "socket_timeout": 15}).extract_info(clean_url, download=False)`. If `info is None` or `info.get("_type") == "playlist"`, raise `MediaInspectError(422, "Please paste a single video or track link — playlists and channels aren't supported.")`. Catch `DownloadError` -> raise `MediaInspectError(422, _friendly_yt_dlp_error(exc))` (stripping raw ANSI escape codes and prefix noise).
- `JobManager._run_job(job_id)`:
  - Resolves `ffmpeg_dir` using `self._ffmpeg_resolver()`.
  - Creates `.temp_jobs/<job_id>/` and checks `_type == "playlist"` in `extract_info(..., download=False)` or via `progress_hooks` + `postprocessor_hooks` during `ydl.download([job.url])`.
  - Maps `downloading` bytes ratio `0.0..1.0` -> `0.0..90.0`; `finished` -> `91.0`; `postprocessor_hooks` `started` -> `"converting"`, `95.0`.
  - After `ydl.download` succeeds, selects the output `.mp3` / `.mp4` file inside `job_dir` (ignoring `.part`/`.ytdl`/temp fragments; falling back to largest non-temp file if extension differs), records `filename`, `file_path`, `size_bytes`, `completed_at`, sets `status="ready"`, `progress=100.0`, notifies subscribers, and closes SSE sentinel (`None`). If `DownloadCancelled` is raised, removes `.temp_jobs/<job_id>/`, sets `status="cancelled"`, notifies subscribers, and pushes `None`.
  - Thread safety: protect `self._jobs` and `self._subscribers` with `threading.Lock`, and push events onto subscriber `asyncio.Queue` via `loop.call_soon_threadsafe(q.put_nowait, snapshot)`!

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_media_service.py -v`
Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add app/media_service.py tests/test_media_service.py
git commit -m "feat: add yt-dlp media inspector, job manager, and temp cleanup"
```

---

### Task 4: FastAPI Routes, SSE Stream & Windows Launcher

**Files:**
- Create: `app/main.py`
- Create: `app/run_server.py`
- Create: `start.bat`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `app/validators.py`, `app/media_service.py`
- Produces in `app/main.py`:
  - `create_app(manager: JobManager | None = None, inspector: Callable = inspect_media) -> FastAPI`
  - `app = create_app()`
  - Endpoints:
    - `GET /` -> HTML page
    - `POST /api/inspect` -> `200` metadata or `400`/`422`/`502`
    - `POST /api/download` -> `202` `{"job_id": "..."}` or `400`/`422`
    - `GET /api/jobs/{job_id}/events` -> SSE `text/event-stream` or `404`
    - `GET /api/jobs/{job_id}/file` -> `FileResponse` with `Content-Disposition` or `404`/`409`
    - `POST /api/jobs/{job_id}/cancel` -> `200` `{"status": "cancelled"}` or `404`
- Produces in `app/run_server.py`:
  - `find_available_port(host: str = "127.0.0.1", preferred: int = 8000, max_tries: int = 11) -> int`

- [ ] **Step 1: Write failing tests in `tests/test_api.py`**

Write API tests using FastAPI `TestClient` + injected mock `inspector` / `JobManager`:
1. `test_post_inspect_success_and_error_mapping`: verify `200` JSON shape, `400` on invalid URL, `422` on playlist URL error.
2. `test_post_download_validates_and_returns_202`: valid `mp3`/`320` and `mp4`/`1080` return `202` with `job_id`; invalid `mp4`/`9999` or private URL returns `422`/`400`.
3. `test_sse_events_immediately_emits_terminal_state_on_finished_job(tmp_path)`: pre-populate a completed `ready` job in `JobManager`, `GET /api/jobs/{id}/events`, assert `text/event-stream`, receives `status == "ready"` JSON event and closes cleanly without hanging; test `404` on unknown `job_id`.
4. `test_get_file_streams_with_sanitized_rfc5987_header_and_blocks_traversal(tmp_path)`: verify `FileResponse` returns file bytes + `Content-Disposition` with ASCII fallback & `filename*=UTF-8''...`; verify `409` if job not yet `ready`; verify `404` if `file_path` points outside `job_dir` (path confinement guard).
5. `test_cancel_endpoint_marks_job_cancelled`: `POST /api/jobs/{id}/cancel` returns `200`, and `404` for unknown `job_id`.
6. `test_find_available_port_skips_bound_port`: bind an ephemeral socket on a port, verify `find_available_port("127.0.0.1", preferred=bound_port, max_tries=5)` returns `bound_port + 1`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`.

- [ ] **Step 3: Implement `app/main.py`, `app/run_server.py`, and `start.bat`**

- In `app/main.py`:
  - `lifespan`: calls `manager.startup_purge()` on startup and `manager.shutdown()` on exit.
  - Mount `/static` -> `app/static` (creating directory safely if invoked before Task 5 UI assets are added, or returning `index.html` cleanly in `GET /`).
  - `POST /api/inspect`: runs `inspector(payload.url)` via `run_in_threadpool`; maps `MediaInspectError` -> `HTTPException(status_code=exc.status_code, detail=exc.detail)`.
  - `POST /api/download`: runs `validate_public_url(payload.url)` + `validate_download_request(payload.format, payload.quality)` (mapping `ValidationError` -> `HTTPException(422, ...)`), then calls `manager.start_job(clean_url, fmt, quality, loop=asyncio.get_running_loop())`, returns `JSONResponse({"job_id": job.job_id}, status_code=202)`.
  - `GET /api/jobs/{job_id}/events`: calls `manager.subscribe(job_id)` -> `404` if missing; `StreamingResponse` yielding `f"data: {json.dumps(event)}\n\n"` lines until terminal state (`ready`/`error`/`cancelled`).
  - `GET /api/jobs/{job_id}/file`: verifies job exists (`404`), `job.status == "ready"` (`409` otherwise), `job.file_path.resolve().is_relative_to((base_temp_dir / job_id).resolve())` (`404` if outside), returns `FileResponse(job.file_path, media_type=..., headers={"Content-Disposition": build_content_disposition(job.filename)})`.
- In `app/run_server.py`:
  - Respects `PORT` env var if set; otherwise calls `find_available_port("127.0.0.1", 8000, 11)`.
  - Spawns daemon thread polling `http://127.0.0.1:<port>/` (or TCP connect) briefly and opening `webbrowser.open(url)` unless `--no-browser` is passed, then starts `uvicorn.run("app.main:app", host="127.0.0.1", port=port, log_level="info")`.
- In `start.bat`:
  - `@echo off`
  - `cd /d "%~dp0"`
  - `uv run python -m app.run_server`
  - `pause` on non-zero exit so errors remain readable if launched from Explorer.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add app/main.py app/run_server.py start.bat tests/test_api.py
git commit -m "feat: add FastAPI routes, SSE progress streaming, and launcher"
```

---

### Task 5: Single-Page Web UI, Repeat-Download Flow & End-to-End Verification

**Files:**
- Create: `app/static/index.html`
- Create: `app/static/styles.css`
- Create: `app/static/app.js`
- Create: `README.md`
- Test: `tests/test_ui_assets.py`

**Interfaces:**
- Consumes: `GET /`, `POST /api/inspect`, `POST /api/download`, `GET /api/jobs/{job_id}/events`, `GET /api/jobs/{job_id}/file`, `POST /api/jobs/{job_id}/cancel`

- [ ] **Step 1: Write failing UI integration test in `tests/test_ui_assets.py`**

```python
from fastapi.testclient import TestClient
from app.main import create_app


def test_root_serves_ui_with_expected_controls():
    client = TestClient(create_app())
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="url-input"' in html
    assert 'id="fetch-btn"' in html
    assert 'id="format-mp3"' in html
    assert 'id="format-mp4"' in html
    assert 'id="quality-select"' in html
    assert 'id="download-btn"' in html
    assert 'id="download-another-btn"' in html
    assert 'id="history-list"' in html
    assert '/static/app.js' in html
    assert '/static/styles.css' in html

    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/styles.css").status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ui_assets.py -v`
Expected: FAIL (`404` or `FileNotFoundError` because `app/static/index.html` does not exist yet).

- [ ] **Step 3: Implement `app/static/index.html`, `app/static/styles.css`, `app/static/app.js`, and `README.md`**

- `index.html`:
  - Semantic, accessible single-page layout: header, URL paste form (`autofocus`), dismissible error alert, preview card (`<img referrerpolicy="no-referrer">` with inline SVG data-URI / hidden SVG fallback on error, title, duration, single-video playlist note), **MP3 (Audio)** / **MP4 (Video)** toggle buttons, quality/resolution `<select>`, subtle `>1080p` remux hint (`hidden` unless MP4 `1440`/`2160` selected), primary **Download MP3/MP4** button, **Cancel** button, live progress bar + status label, **"Download another"** button, and **Recent Downloads (this session)** list.
- `styles.css`:
  - Clean adaptive dark/light palette (`prefers-color-scheme`), crisp spacing, accessible focus outlines, responsive layout (works cleanly on desktop and narrower windows).
- `app.js`:
  - `fetchMetadata(url)` -> calls `POST /api/inspect`, populates preview & dynamic quality options (`mp3_bitrates` `[320, 192, 128]` vs detected `mp4_heights` like `2160p (4K)`, `1440p`, `1080p`, `720p`, `480p`, `360p` or `Best available`).
  - Switching **MP3 / MP4** updates dropdown options, CTA label, and `>1080p` hint visibility.
  - `startDownload()` -> calls `POST /api/download`, opens `EventSource('/api/jobs/' + jobId + '/events')`, updates progress bar/stage text, handles `ready` by triggering hidden `<a href="/api/jobs/${jobId}/file" download>` click, adding entry to **Recent Downloads** with a `Save again` link, and showing **"Download another"** (which resets input, clears preview, and focuses `#url-input`).
  - Also unlocks `#url-input` so pasting a new URL at any time after completion works immediately without needing to click **"Download another"** first; and cleanly closes any prior `EventSource` on cancel/error/reset.
- `README.md`:
  - Short instructions: double-click `start.bat` (or run `uv run python -m app.run_server`), paste a permitted media URL, choose MP3/MP4 + quality, download, and repeat; plus how to update `yt-dlp` via `uv lock --upgrade-package yt-dlp && uv sync`.

- [ ] **Step 4: Run full test suite and JS syntax + live server smoke check**

Run:
```powershell
uv run pytest -v
node --check app/static/app.js
```
Expected: All tests PASS and `node --check` exits 0.
Also run a single-command live server probe (starts `uvicorn` briefly in-process/subshell, probes `GET /` and `POST /api/inspect` with `http://127.0.0.1/invalid` expecting `400`, then stops it cleanly).

- [ ] **Step 5: Commit**

```powershell
git add app/static/index.html app/static/styles.css app/static/app.js README.md tests/test_ui_assets.py
git commit -m "feat: add single-page web UI and repeat-download workflow"
```
