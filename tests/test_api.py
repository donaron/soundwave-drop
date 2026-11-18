import json
from pathlib import Path
import socket
import threading
import time
from fastapi.testclient import TestClient

from app.main import create_app
from app.media_service import JobManager, MediaInspectError
from app.run_server import find_available_port
from app.validators import validate_public_url


def _public_resolver(host, port, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


def test_post_inspect_success_and_error_mapping(tmp_path):
    def fake_inspector(url: str):
        if "playlist" in url:
            raise MediaInspectError(422, "Please paste a single video or track link — playlists and channels aren't supported.")
        if "bad" in url:
            raise MediaInspectError(400, "Only http:// and https:// URLs are supported.")
        return {
            "url": url,
            "title": "Sample Track",
            "duration": 125,
            "thumbnail": "https://i.ytimg.com/vi/demo/hqdefault.jpg",
            "extractor": "youtube",
            "is_playlist_url": False,
            "mp3_bitrates": [320, 192, 128],
            "mp4_heights": [1080, 720, 480],
        }

    manager = JobManager(base_temp_dir=tmp_path / ".temp_jobs")
    with TestClient(create_app(manager=manager, inspector=fake_inspector)) as client:
        ok = client.post("/api/inspect", json={"url": "https://www.youtube.com/watch?v=demo"})
        assert ok.status_code == 200
        assert ok.json()["title"] == "Sample Track"
        assert ok.json()["mp4_heights"] == [1080, 720, 480]

        bad = client.post("/api/inspect", json={"url": "file:///bad"})
        assert bad.status_code == 400
        assert "supported" in bad.json()["detail"].lower()

        pl = client.post("/api/inspect", json={"url": "https://www.youtube.com/playlist?list=PL1"})
        assert pl.status_code == 422
        assert "playlist" in pl.json()["detail"].lower()


def test_post_download_validates_and_returns_202(tmp_path):
    ffmpeg_dir = tmp_path / "ffmpeg"
    ffmpeg_dir.mkdir()

    class InstantYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {"_type": "video"}

        def download(self, urls):
            out_dir = Path(self.opts["outtmpl"]).parent
            (out_dir / "track.mp3").write_bytes(b"mp3data")

    manager = JobManager(
        base_temp_dir=tmp_path / ".temp_jobs",
        ydl_factory=InstantYDL,
        ffmpeg_resolver=lambda: ffmpeg_dir,
    )
    app = create_app(
        manager=manager,
        url_validator=lambda u: validate_public_url(u, resolver=_public_resolver),
    )
    with TestClient(app) as client:
        resp = client.post(
            "/api/download",
            json={"url": "https://www.youtube.com/watch?v=demo", "format": "mp3", "quality": "320"},
        )
        assert resp.status_code == 202
        assert "job_id" in resp.json()

        bad_quality = client.post(
            "/api/download",
            json={"url": "https://www.youtube.com/watch?v=demo", "format": "mp4", "quality": "9999"},
        )
        assert bad_quality.status_code == 422

        ssrf = client.post(
            "/api/download",
            json={"url": "http://127.0.0.1:8000/secret", "format": "mp3", "quality": "320"},
        )
        assert ssrf.status_code == 400


def test_sse_events_immediately_emits_terminal_state_on_finished_job(tmp_path):
    ffmpeg_dir = tmp_path / "ffmpeg"
    ffmpeg_dir.mkdir()

    class InstantYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {"_type": "video"}

        def download(self, urls):
            out_dir = Path(self.opts["outtmpl"]).parent
            (out_dir / "done.mp4").write_bytes(b"mp4bytes")

    manager = JobManager(
        base_temp_dir=tmp_path / ".temp_jobs",
        ydl_factory=InstantYDL,
        ffmpeg_resolver=lambda: ffmpeg_dir,
    )
    app = create_app(
        manager=manager,
        url_validator=lambda u: validate_public_url(u, resolver=_public_resolver),
    )
    with TestClient(app) as client:
        unknown = client.get("/api/jobs/does-not-exist/events")
        assert unknown.status_code == 404

        job_id = client.post(
            "/api/download",
            json={"url": "https://www.youtube.com/watch?v=demo", "format": "mp4", "quality": "1080"},
        ).json()["job_id"]

        # Wait for job completion BEFORE opening /events to exercise the fast-finish race
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            cur = manager.get_job(job_id)
            if cur and cur.status == "ready":
                break
            time.sleep(0.01)

        with client.stream("GET", f"/api/jobs/{job_id}/events") as sse:
            assert sse.status_code == 200
            assert "text/event-stream" in sse.headers["content-type"]
            lines = [line for line in sse.iter_lines() if line.startswith("data: ")]

        assert len(lines) == 1
        payload = json.loads(lines[0][len("data: ") :])
        assert payload["status"] == "ready"
        assert payload["filename"] == "done.mp4"


def test_get_file_streams_with_rfc5987_header_and_blocks_traversal(tmp_path):
    ffmpeg_dir = tmp_path / "ffmpeg"
    ffmpeg_dir.mkdir()
    unicode_name = "Canción ★ Live.mp3"

    class UnicodeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {"_type": "video"}

        def download(self, urls):
            out_dir = Path(self.opts["outtmpl"]).parent
            (out_dir / unicode_name).write_bytes(b"audio-payload")

    base_temp = tmp_path / ".temp_jobs"
    manager = JobManager(
        base_temp_dir=base_temp,
        ydl_factory=UnicodeYDL,
        ffmpeg_resolver=lambda: ffmpeg_dir,
    )
    app = create_app(
        manager=manager,
        url_validator=lambda u: validate_public_url(u, resolver=_public_resolver),
    )
    with TestClient(app) as client:
        assert client.get("/api/jobs/unknown/file").status_code == 404

        job_id = client.post(
            "/api/download",
            json={"url": "https://www.youtube.com/watch?v=demo", "format": "mp3", "quality": "320"},
        ).json()["job_id"]

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            cur = manager.get_job(job_id)
            if cur and cur.status == "ready":
                break
            time.sleep(0.01)

        dl = client.get(f"/api/jobs/{job_id}/file")
        assert dl.status_code == 200
        assert dl.content == b"audio-payload"
        disp = dl.headers["content-disposition"]
        assert "filename*=UTF-8''" in disp
        assert ".mp3" in disp

        # Path confinement check: simulate corrupted file_path outside job_dir
        outside = tmp_path / "secret.txt"
        outside.write_text("secret", encoding="utf-8")
        with manager._lock:
            manager._jobs[job_id].file_path = outside
        assert client.get(f"/api/jobs/{job_id}/file").status_code == 404


def test_cancel_endpoint_marks_job_cancelled(tmp_path):
    ffmpeg_dir = tmp_path / "ffmpeg"
    ffmpeg_dir.mkdir()
    started = threading.Event()
    release = threading.Event()

    class SlowYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {"_type": "video"}

        def download(self, urls):
            started.set()
            release.wait(timeout=3.0)
            for hook in self.opts["progress_hooks"]:
                hook({"status": "downloading", "downloaded_bytes": 10, "total_bytes": 100})

    manager = JobManager(
        base_temp_dir=tmp_path / ".temp_jobs",
        ydl_factory=SlowYDL,
        ffmpeg_resolver=lambda: ffmpeg_dir,
    )
    app = create_app(
        manager=manager,
        url_validator=lambda u: validate_public_url(u, resolver=_public_resolver),
    )
    with TestClient(app) as client:
        assert client.post("/api/jobs/missing/cancel").status_code == 404

        job_id = client.post(
            "/api/download",
            json={"url": "https://www.youtube.com/watch?v=demo", "format": "mp3", "quality": "192"},
        ).json()["job_id"]
        assert started.wait(timeout=3.0)

        cancel_resp = client.post(f"/api/jobs/{job_id}/cancel")
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["status"] == "cancelled"
        release.set()


def test_find_available_port_skips_bound_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        busy_port = sock.getsockname()[1]

        chosen = find_available_port("127.0.0.1", preferred=busy_port, max_tries=5)
        assert chosen > busy_port
        assert chosen < busy_port + 5
