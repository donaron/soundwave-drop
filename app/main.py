"""FastAPI application factory, REST endpoints, SSE progress stream, and static UI mount."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.media_service import (
    TERMINAL_STATUSES,
    JobManager,
    MediaInspectError,
    inspect_media,
)
from app.validators import (
    ValidationError,
    build_content_disposition,
    validate_download_request,
    validate_public_url,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(__file__).resolve().parent / "static"
DEFAULT_TEMP_DIR = PROJECT_ROOT / ".temp_jobs"


class InspectRequest(BaseModel):
    """Request payload for /api/inspect."""

    url: str


class DownloadRequest(BaseModel):
    """Request payload for /api/download."""

    url: str
    format: str
    quality: str


def create_app(
    manager: JobManager | None = None,
    inspector: Callable[[str], dict[str, Any]] = inspect_media,
    url_validator: Callable[[str], str] = validate_public_url,
) -> FastAPI:
    """Create and configure the local media downloader FastAPI application."""
    active_manager = manager or JobManager(base_temp_dir=DEFAULT_TEMP_DIR)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        active_manager.startup_purge()
        try:
            yield
        finally:
            active_manager.shutdown()

    app = FastAPI(title="Private Media Downloader", lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR), check_dir=False), name="static")

    @app.get("/", response_model=None)
    async def serve_index() -> FileResponse | HTMLResponse:
        index_path = STATIC_DIR / "index.html"
        if not index_path.is_file():
            return HTMLResponse("UI assets are not installed.", status_code=404)
        return FileResponse(index_path)

    @app.post("/api/inspect")
    async def inspect_endpoint(payload: InspectRequest) -> dict[str, Any]:
        try:
            return await run_in_threadpool(inspector, payload.url)
        except MediaInspectError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    @app.post("/api/download")
    async def download_endpoint(payload: DownloadRequest) -> JSONResponse:
        try:
            clean_url = await run_in_threadpool(url_validator, payload.url)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        try:
            fmt, quality = validate_download_request(payload.format, payload.quality)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        job = active_manager.start_job(
            clean_url,
            fmt,
            quality,
            loop=asyncio.get_running_loop(),
        )
        return JSONResponse({"job_id": job.job_id}, status_code=202)

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str) -> StreamingResponse:
        loop = asyncio.get_running_loop()
        snapshot, queue = active_manager.subscribe(job_id, loop=loop)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Download job not found.")

        async def event_stream():
            try:
                yield f"data: {json.dumps(snapshot.to_event_dict())}\n\n"
                if snapshot.status in TERMINAL_STATUSES or snapshot.status == "expired":
                    return
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if event is None:
                        break
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("status") in TERMINAL_STATUSES:
                        break
            finally:
                active_manager.unsubscribe(job_id, queue)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/jobs/{job_id}/file")
    async def download_file(job_id: str) -> FileResponse:
        job = active_manager.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Download job not found.")
        if job.status != "ready" or job.file_path is None or job.filename is None:
            raise HTTPException(status_code=409, detail="File is not ready for download.")

        job_root = (active_manager.base_temp_dir / job_id).resolve()
        resolved = job.file_path.resolve()
        if not resolved.is_relative_to(job_root) or not resolved.is_file():
            raise HTTPException(status_code=404, detail="Downloaded file is no longer available.")

        media_type = "audio/mpeg" if job.fmt == "mp3" else "video/mp4"
        return FileResponse(
            path=resolved,
            media_type=media_type,
            headers={"Content-Disposition": build_content_disposition(job.filename)},
        )

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str) -> dict[str, str]:
        job = active_manager.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Download job not found.")
        if not active_manager.cancel_job(job_id):
            raise HTTPException(status_code=409, detail=f"Job already {job.status}.")
        return {"status": "cancelled"}

    return app


app = create_app()
