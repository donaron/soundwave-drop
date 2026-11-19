"""Media inspection, yt-dlp download execution, and temporary job management."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
import logging
from pathlib import Path
import re
import shutil
import threading
import time
from typing import Any, Callable
import uuid

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from app.ffmpeg_locator import resolve_ffmpeg_dir
from app.validators import has_playlist_context, validate_public_url

logger = logging.getLogger(__name__)

STANDARD_MP4_HEIGHTS: tuple[int, ...] = (2160, 1440, 1080, 720, 480, 360, 240, 144)
MP3_BITRATES: tuple[int, ...] = (320, 192, 128)
TERMINAL_STATUSES = frozenset({"ready", "error", "cancelled"})
PLAYLIST_TYPES = frozenset({"playlist", "multi_video"})

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


class MediaInspectError(Exception):
    """Raised when URL metadata inspection cannot produce a single media item."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class DownloadCancelled(Exception):
    """Raised inside yt-dlp hooks when a user cancels an active download job."""


def _clean_yt_dlp_error(exc: Exception) -> str:
    raw = _ANSI_ESCAPE_RE.sub("", str(exc)).strip()
    if raw.startswith("ERROR:"):
        raw = raw[len("ERROR:") :].strip()
    return raw or "Failed to process this media URL."


def _extract_mp4_heights(formats: list[dict[str, Any]] | None) -> list[int | str]:
    if not formats:
        return ["best"]
    detected: set[int] = set()
    for fmt in formats:
        vcodec = fmt.get("vcodec")
        height = fmt.get("height")
        width = fmt.get("width")
        if vcodec == "none" or not isinstance(height, int) or height <= 0:
            continue
        resolution = min(width, height) if isinstance(width, int) and width > 0 else height
        detected.add(resolution)
    matched: list[int | str] = [h for h in STANDARD_MP4_HEIGHTS if h in detected]
    return matched if matched else ["best"]


def inspect_media(
    url: str,
    ydl_factory: Callable[[dict[str, Any]], Any] = YoutubeDL,
    url_validator: Callable[[str], str] = validate_public_url,
) -> dict[str, Any]:
    """Inspect a public media URL without downloading and return clean metadata."""
    try:
        clean_url = url_validator(url)
    except ValueError as exc:
        raise MediaInspectError(400, str(exc)) from exc

    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "extract_flat": "in_playlist",
        "socket_timeout": 15,
    }
    try:
        with ydl_factory(opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)
    except DownloadError as exc:
        raise MediaInspectError(422, _clean_yt_dlp_error(exc)) from exc
    except Exception as exc:
        raise MediaInspectError(502, f"Unable to inspect media link: {exc}") from exc

    if not info or info.get("_type") in PLAYLIST_TYPES:
        raise MediaInspectError(
            422,
            "Please paste a single video or track link — playlists and channels aren't supported.",
        )

    return {
        "url": clean_url,
        "title": info.get("title") or "Untitled media",
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "extractor": info.get("extractor") or "unknown",
        "is_playlist_url": has_playlist_context(clean_url),
        "mp3_bitrates": list(MP3_BITRATES),
        "mp4_heights": _extract_mp4_heights(info.get("formats")),
    }


def build_ydl_options(
    fmt: str,
    quality: str,
    job_dir: Path,
    ffmpeg_dir: Path,
) -> dict[str, Any]:
    """Build deterministic yt-dlp options for MP3 extraction or resolution-first MP4."""
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "noplaylist": True,
        "extract_flat": "in_playlist",
        "socket_timeout": 20,
        "ffmpeg_location": str(ffmpeg_dir),
        "outtmpl": str(job_dir / "%(title).100B.%(ext)s"),
        "windowsfilenames": True,
        "restrictfilenames": False,
    }

    if fmt == "mp3":
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": quality,
            }
        ]
        return opts

    opts["format"] = "bestvideo+bestaudio/best"
    if quality == "best":
        opts["format_sort"] = ["res", "vcodec:h264", "acodec:m4a"]
    else:
        opts["format_sort"] = [f"res:{quality}", "vcodec:h264", "acodec:m4a"]
    opts["merge_output_format"] = "mp4"
    return opts


@dataclass
class JobState:
    """Mutable state snapshot for an individual download job."""

    job_id: str
    url: str
    fmt: str
    quality: str
    status: str = "queued"
    progress: float = 0.0
    stage_label: str = "Queued..."
    filename: str | None = None
    file_path: Path | None = None
    size_bytes: int | None = None
    error: str | None = None
    created_at: float = 0.0
    completed_at: float | None = None
    cancelled: bool = False

    def to_event_dict(self) -> dict[str, Any]:
        """Serialize public status fields for SSE event payloads."""
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress": round(self.progress, 1),
            "stage_label": self.stage_label,
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "error": self.error,
        }


def _find_output_file(job_dir: Path, expected_ext: str) -> Path | None:
    candidates = [
        p
        for p in job_dir.iterdir()
        if p.is_file() and not p.name.endswith((".part", ".ytdl", ".temp"))
    ]
    preferred = [p for p in candidates if p.suffix.lower() == f".{expected_ext}"]
    pool = preferred if preferred else candidates
    if not pool:
        return None
    return max(pool, key=lambda p: p.stat().st_size)


class JobManager:
    """Manages background yt-dlp download jobs, SSE listeners, and temp storage cleanup."""

    def __init__(
        self,
        base_temp_dir: Path,
        ttl_seconds: int = 900,
        max_cached_completed: int = 5,
        max_workers: int = 2,
        ydl_factory: Callable[[dict[str, Any]], Any] = YoutubeDL,
        ffmpeg_resolver: Callable[[], Path] = resolve_ffmpeg_dir,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.base_temp_dir = base_temp_dir
        self._ttl_seconds = ttl_seconds
        self._max_cached_completed = max_cached_completed
        self._ydl_factory = ydl_factory
        self._ffmpeg_resolver = ffmpeg_resolver
        self._clock = clock
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        self._jobs: dict[str, JobState] = {}
        self._subscribers: dict[str, list[tuple[asyncio.AbstractEventLoop | None, asyncio.Queue]]] = {}

    def startup_purge(self) -> None:
        """Delete leftover job directories from previous server runs."""
        if self.base_temp_dir.exists():
            for child in self.base_temp_dir.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
        self.base_temp_dir.mkdir(parents=True, exist_ok=True)

    def evict_expired(self) -> None:
        """Remove completed temp folders past TTL or exceeding max_cached_completed."""
        now = self._clock()
        dirs_to_remove: list[Path] = []
        with self._lock:
            completed = [
                job
                for job in self._jobs.values()
                if job.status == "ready" and job.completed_at is not None and job.file_path is not None
            ]
            completed.sort(key=lambda j: j.completed_at or 0.0, reverse=True)
            for idx, job in enumerate(completed):
                expired = (now - (job.completed_at or now)) >= self._ttl_seconds
                over_limit = idx >= self._max_cached_completed
                if expired or over_limit:
                    dirs_to_remove.append(self.base_temp_dir / job.job_id)
                    job.file_path = None
                    job.status = "expired"

        for directory in dirs_to_remove:
            shutil.rmtree(directory, ignore_errors=True)

    def start_job(
        self,
        url: str,
        fmt: str,
        quality: str,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> JobState:
        """Create and schedule a new download job."""
        self.evict_expired()
        self.base_temp_dir.mkdir(parents=True, exist_ok=True)
        job_id = uuid.uuid4().hex
        job = JobState(
            job_id=job_id,
            url=url,
            fmt=fmt,
            quality=quality,
            created_at=self._clock(),
        )
        with self._lock:
            self._jobs[job_id] = job
            self._subscribers[job_id] = []
        self._executor.submit(self._run_job, job_id, loop)
        return replace(job)

    def get_job(self, job_id: str) -> JobState | None:
        """Return a snapshot copy of the requested job, or None if unknown."""
        with self._lock:
            job = self._jobs.get(job_id)
            return replace(job) if job is not None else None

    def subscribe(
        self,
        job_id: str,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> tuple[JobState | None, asyncio.Queue]:
        """Attach an SSE subscriber queue and return the current job snapshot."""
        queue: asyncio.Queue = asyncio.Queue()
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None, queue
            snapshot = replace(job)
            if job.status not in TERMINAL_STATUSES and job.status != "expired":
                self._subscribers.setdefault(job_id, []).append((loop, queue))
            return snapshot, queue

    def unsubscribe(self, job_id: str, queue: asyncio.Queue) -> None:
        """Remove an SSE subscriber queue on client disconnect."""
        with self._lock:
            entries = self._subscribers.get(job_id)
            if not entries:
                return
            self._subscribers[job_id] = [item for item in entries if item[1] is not queue]

    def cancel_job(self, job_id: str) -> bool:
        """Mark an active job cancelled so hooks abort and clean temp storage."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return False
            if job.status in TERMINAL_STATUSES or job.status == "expired":
                return False
            job.cancelled = True
            job.stage_label = "Cancelling..."
        self._notify(job_id, close_stream=False)
        return True

    def shutdown(self) -> None:
        """Cancel pending work and wait cleanly for worker threads to finish."""
        with self._lock:
            for job in self._jobs.values():
                if job.status not in TERMINAL_STATUSES and job.status != "expired":
                    job.cancelled = True
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _notify(self, job_id: str, close_stream: bool = False) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            payload = job.to_event_dict()
            listeners = list(self._subscribers.get(job_id, []))
            if close_stream:
                self._subscribers[job_id] = []

        for loop, queue in listeners:
            self._push_to_queue(loop, queue, payload)
            if close_stream:
                self._push_to_queue(loop, queue, None)

    @staticmethod
    def _push_to_queue(
        loop: asyncio.AbstractEventLoop | None,
        queue: asyncio.Queue,
        item: Any,
    ) -> None:
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(queue.put_nowait, item)
                return
            except RuntimeError:
                pass
        queue.put_nowait(item)

    def _update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress: float | None = None,
        stage_label: str | None = None,
        close_stream: bool = False,
        **fields: Any,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = progress
            if stage_label is not None:
                job.stage_label = stage_label
            for key, value in fields.items():
                setattr(job, key, value)
        self._notify(job_id, close_stream=close_stream)

    def _is_cancelled(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            return bool(job and job.cancelled)

    def _run_job(self, job_id: str, loop: asyncio.AbstractEventLoop | None) -> None:
        del loop  # Listeners register their own loops on subscribe().
        job_dir = self.base_temp_dir / job_id
        job = self.get_job(job_id)
        if job is None:
            return

        if self._is_cancelled(job_id):
            self._update_job(job_id, status="cancelled", stage_label="Cancelled", close_stream=True)
            return

        try:
            ffmpeg_dir = self._ffmpeg_resolver()
            job_dir.mkdir(parents=True, exist_ok=True)
            opts = build_ydl_options(job.fmt, job.quality, job_dir, ffmpeg_dir)

            stream_index = 0
            highest_progress = 1.0
            last_emit_progress = 1.0
            last_emit_time = 0.0

            def reject_playlists(info_dict: dict[str, Any], incomplete: bool = False) -> None:
                if info_dict.get("_type") in PLAYLIST_TYPES or (
                    incomplete and "playlist_id" in info_dict and "id" not in info_dict
                ):
                    raise MediaInspectError(
                        422,
                        "Please paste a single video or track link — playlists and channels aren't supported.",
                    )
                return None

            def on_progress(data: dict[str, Any]) -> None:
                nonlocal stream_index, highest_progress, last_emit_progress, last_emit_time
                if self._is_cancelled(job_id):
                    raise DownloadCancelled("Download cancelled by user.")
                state = data.get("status")
                if state == "downloading":
                    total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                    downloaded = data.get("downloaded_bytes") or 0
                    ratio = min(1.0, max(0.0, downloaded / total)) if total > 0 else 0.0
                    pct_int = int(round(ratio * 100))
                    if job.fmt == "mp4":
                        if stream_index == 0:
                            mapped = ratio * 75.0
                            label = f"Downloading video stream... {pct_int}%"
                        else:
                            mapped = 75.0 + (ratio * 15.0)
                            label = f"Downloading audio stream... {pct_int}%"
                    else:
                        mapped = ratio * 90.0
                        label = f"Downloading stream... {pct_int}%"

                    effective_pct = max(highest_progress, mapped)
                    now = time.monotonic()
                    if (
                        effective_pct >= 90.0
                        or (effective_pct - last_emit_progress) >= 1.0
                        or (now - last_emit_time) >= 0.1
                    ):
                        highest_progress = effective_pct
                        last_emit_progress = effective_pct
                        last_emit_time = now
                        self._update_job(
                            job_id,
                            status="downloading",
                            progress=effective_pct,
                            stage_label=label,
                        )
                elif state == "finished":
                    if job.fmt == "mp4" and stream_index == 0:
                        stream_index += 1
                        effective_pct = max(highest_progress, 75.0)
                        highest_progress = effective_pct
                        last_emit_progress = effective_pct
                        last_emit_time = time.monotonic()
                        self._update_job(
                            job_id,
                            status="downloading",
                            progress=effective_pct,
                            stage_label="Video downloaded, fetching audio stream...",
                        )
                    else:
                        effective_pct = max(highest_progress, 91.0)
                        highest_progress = effective_pct
                        last_emit_progress = effective_pct
                        last_emit_time = time.monotonic()
                        self._update_job(
                            job_id,
                            status="converting",
                            progress=effective_pct,
                            stage_label="Download finished, processing file...",
                        )

            def on_postprocessor(data: dict[str, Any]) -> None:
                nonlocal highest_progress, last_emit_progress, last_emit_time
                if self._is_cancelled(job_id):
                    raise DownloadCancelled("Download cancelled by user.")
                if data.get("status") == "started":
                    label = "Converting to MP3..." if job.fmt == "mp3" else "Finalizing MP4..."
                    effective_pct = max(highest_progress, 95.0)
                    highest_progress = effective_pct
                    last_emit_progress = effective_pct
                    last_emit_time = time.monotonic()
                    self._update_job(
                        job_id,
                        status="converting",
                        progress=effective_pct,
                        stage_label=label,
                    )

            opts["match_filter"] = reject_playlists
            opts["progress_hooks"] = [on_progress]
            opts["postprocessor_hooks"] = [on_postprocessor]

            self._update_job(
                job_id,
                status="downloading",
                progress=1.0,
                stage_label="Starting download...",
            )

            with self._ydl_factory(opts) as ydl:
                if self._is_cancelled(job_id):
                    raise DownloadCancelled("Download cancelled by user.")
                ydl.download([job.url])

            if self._is_cancelled(job_id):
                raise DownloadCancelled("Download cancelled by user.")

            output_file = _find_output_file(job_dir, job.fmt)
            if output_file is None or not output_file.is_file():
                raise RuntimeError("Conversion completed, but no output file was produced.")

            self._update_job(
                job_id,
                status="ready",
                progress=100.0,
                stage_label="Ready — saving file...",
                filename=output_file.name,
                file_path=output_file,
                size_bytes=output_file.stat().st_size,
                completed_at=self._clock(),
                close_stream=True,
            )
        except DownloadCancelled:
            shutil.rmtree(job_dir, ignore_errors=True)
            self._update_job(
                job_id,
                status="cancelled",
                stage_label="Cancelled",
                file_path=None,
                close_stream=True,
            )
        except MediaInspectError as exc:
            shutil.rmtree(job_dir, ignore_errors=True)
            self._update_job(
                job_id,
                status="error",
                stage_label="Failed",
                error=exc.detail,
                file_path=None,
                close_stream=True,
            )
        except DownloadError as exc:
            shutil.rmtree(job_dir, ignore_errors=True)
            self._update_job(
                job_id,
                status="error",
                stage_label="Failed",
                error=_clean_yt_dlp_error(exc),
                file_path=None,
                close_stream=True,
            )
        except Exception as exc:
            logger.exception("Download job %s failed", job_id)
            shutil.rmtree(job_dir, ignore_errors=True)
            self._update_job(
                job_id,
                status="error",
                stage_label="Failed",
                error=str(exc) or "Download failed unexpectedly.",
                file_path=None,
                close_stream=True,
            )
