import asyncio
import threading
import time
from pathlib import Path
import socket
import pytest
from yt_dlp.utils import DownloadError

from app.media_service import (
    DownloadCancelled,
    JobManager,
    MediaInspectError,
    build_ydl_options,
    inspect_media,
)


def _public_resolver(host, port, *args, **kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


def test_inspect_media_returns_filtered_mp4_heights_and_metadata():
    captured_opts = {}

    class FakeYDL:
        def __init__(self, opts):
            captured_opts.update(opts)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            assert download is False
            return {
                "_type": "video",
                "title": "Demo Track",
                "duration": 222,
                "thumbnail": "https://i.ytimg.com/vi/abc/hqdefault.jpg",
                "extractor": "youtube",
                "formats": [
                    {"format_id": "18", "height": 360, "vcodec": "avc1", "acodec": "mp4a"},
                    {"format_id": "135", "height": 480, "vcodec": "avc1", "acodec": "none"},
                    {"format_id": "136", "height": 720, "vcodec": "avc1", "acodec": "none"},
                    {"format_id": "137", "height": 1080, "vcodec": "avc1", "acodec": "none"},
                    {"format_id": "271", "height": 1440, "vcodec": "vp9", "acodec": "none"},
                    {"format_id": "251", "height": None, "vcodec": "none", "acodec": "opus"},
                ],
            }

    result = inspect_media(
        "https://www.youtube.com/watch?v=abc",
        ydl_factory=FakeYDL,
        url_validator=lambda u: u,
    )
    assert captured_opts["noplaylist"] is True
    assert captured_opts["extract_flat"] == "in_playlist"
    assert result == {
        "url": "https://www.youtube.com/watch?v=abc",
        "title": "Demo Track",
        "duration": 222,
        "thumbnail": "https://i.ytimg.com/vi/abc/hqdefault.jpg",
        "extractor": "youtube",
        "is_playlist_url": False,
        "mp3_bitrates": [320, 192, 128],
        "mp4_heights": [1440, 1080, 720, 480, 360],
    }


def test_inspect_media_falls_back_to_best_when_no_heights_present():
    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {
                "title": "Audio Or Unknown Height",
                "duration": None,
                "thumbnail": None,
                "extractor": "generic",
                "formats": [{"format_id": "best", "vcodec": "unknown"}],
            }

    result = inspect_media(
        "https://example.com/media/1",
        ydl_factory=FakeYDL,
        url_validator=lambda u: u,
    )
    assert result["mp4_heights"] == ["best"]


def test_inspect_media_rejects_playlist_only_url():
    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {
                "_type": "playlist",
                "title": "My Playlist",
                "entries": [{"id": "1"}, {"id": "2"}],
            }

    with pytest.raises(MediaInspectError) as exc_info:
        inspect_media(
            "https://www.youtube.com/playlist?list=PL123",
            ydl_factory=FakeYDL,
            url_validator=lambda u: u,
        )
    assert exc_info.value.status_code == 422
    assert "playlist" in exc_info.value.detail.lower()


def test_inspect_media_allows_single_video_with_list_param():
    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {
                "title": "Single Video In List",
                "duration": 180,
                "thumbnail": "https://i.ytimg.com/vi/abc/default.jpg",
                "extractor": "youtube",
                "formats": [{"height": 720, "vcodec": "avc1"}],
            }

    result = inspect_media(
        "https://www.youtube.com/watch?v=abc&list=PL123",
        ydl_factory=FakeYDL,
        url_validator=lambda u: u,
    )
    assert result["is_playlist_url"] is True
    assert result["title"] == "Single Video In List"


def test_inspect_media_maps_download_error_to_friendly_422():
    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            raise DownloadError("\x1b[0;31mERROR:\x1b[0m [youtube] Sign in to confirm you're not a bot")

    with pytest.raises(MediaInspectError) as exc_info:
        inspect_media(
            "https://www.youtube.com/watch?v=abc",
            ydl_factory=FakeYDL,
            url_validator=lambda u: u,
        )
    assert exc_info.value.status_code == 422
    assert "\x1b" not in exc_info.value.detail
    assert "Sign in to confirm" in exc_info.value.detail


def test_build_ydl_options_mp3_and_mp4_resolution_first(tmp_path):
    ffmpeg_dir = tmp_path / "ffmpeg_bin"

    mp3_opts = build_ydl_options("mp3", "320", tmp_path, ffmpeg_dir)
    assert mp3_opts["format"] == "bestaudio/best"
    assert mp3_opts["postprocessors"] == [
        {
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "320",
        }
    ]
    assert mp3_opts["noplaylist"] is True
    assert mp3_opts["ffmpeg_location"] == str(ffmpeg_dir)

    mp4_1440 = build_ydl_options("mp4", "1440", tmp_path, ffmpeg_dir)
    assert mp4_1440["format"] == "bestvideo+bestaudio/best"
    assert mp4_1440["format_sort"] == ["res:1440", "vcodec:h264", "acodec:m4a"]
    assert mp4_1440["merge_output_format"] == "mp4"
    assert mp4_1440["noprogress"] is True

    mp4_best = build_ydl_options("mp4", "best", tmp_path, ffmpeg_dir)
    assert mp4_best["format"] == "bestvideo+bestaudio/best"
    assert mp4_best["format_sort"] == ["res", "vcodec:h264", "acodec:m4a"]
    assert mp4_best["merge_output_format"] == "mp4"


def test_inspect_media_detects_low_res_and_portrait_short_resolutions():
    class LowResAndPortraitYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            if "low" in url:
                return {
                    "title": "Low Res Classic",
                    "duration": 19,
                    "extractor": "youtube",
                    "formats": [
                        {"format_id": "160", "width": 192, "height": 144, "vcodec": "avc1"},
                        {"format_id": "133", "width": 320, "height": 240, "vcodec": "avc1"},
                    ],
                }
            return {
                "title": "Vertical Short",
                "duration": 30,
                "extractor": "youtube",
                "formats": [
                    {"format_id": "s480", "width": 480, "height": 854, "vcodec": "avc1"},
                    {"format_id": "s720", "width": 720, "height": 1280, "vcodec": "avc1"},
                    {"format_id": "s1080", "width": 1080, "height": 1920, "vcodec": "avc1"},
                ],
            }

    low = inspect_media("https://example.com/low", ydl_factory=LowResAndPortraitYDL, url_validator=lambda u: u)
    assert low["mp4_heights"] == [240, 144]

    short = inspect_media("https://example.com/short", ydl_factory=LowResAndPortraitYDL, url_validator=lambda u: u)
    assert short["mp4_heights"] == [1080, 720, 480]


def test_job_manager_lifecycle_ready_and_file_location(tmp_path):
    ffmpeg_dir = tmp_path / "ffmpeg"
    ffmpeg_dir.mkdir()

    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {"_type": "video", "title": "My Track"}

        def download(self, urls):
            outtmpl = Path(self.opts["outtmpl"]).parent
            for hook in self.opts["progress_hooks"]:
                hook({"status": "downloading", "downloaded_bytes": 500, "total_bytes": 1000})
                hook({"status": "finished", "filename": str(outtmpl / "My Track.webm")})
            for phook in self.opts["postprocessor_hooks"]:
                phook({"status": "started", "postprocessor": "FFmpegExtractAudio"})
            output_file = outtmpl / "My Track.mp3"
            output_file.write_bytes(b"ID3-test-audio")

    manager = JobManager(
        base_temp_dir=tmp_path / ".temp_jobs",
        ydl_factory=FakeYDL,
        ffmpeg_resolver=lambda: ffmpeg_dir,
    )
    try:
        job = manager.start_job("https://www.youtube.com/watch?v=abc", "mp3", "320")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            current = manager.get_job(job.job_id)
            if current and current.status in {"ready", "error"}:
                break
            time.sleep(0.02)

        final = manager.get_job(job.job_id)
        assert final is not None
        assert final.status == "ready"
        assert final.progress == 100.0
        assert final.filename == "My Track.mp3"
        assert final.size_bytes == len(b"ID3-test-audio")
        assert final.file_path is not None and final.file_path.is_file()
    finally:
        manager.shutdown()


def test_job_manager_error_on_download_error_and_missing_ffmpeg(tmp_path):
    ffmpeg_dir = tmp_path / "ffmpeg"
    ffmpeg_dir.mkdir()

    class ErrorYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {"_type": "video"}

        def download(self, urls):
            raise DownloadError("ERROR: Video unavailable (DRM protected)")

    manager = JobManager(
        base_temp_dir=tmp_path / ".temp_jobs",
        ydl_factory=ErrorYDL,
        ffmpeg_resolver=lambda: ffmpeg_dir,
    )
    try:
        job = manager.start_job("https://www.youtube.com/watch?v=bad", "mp4", "1080")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            current = manager.get_job(job.job_id)
            if current and current.status in {"ready", "error"}:
                break
            time.sleep(0.02)
        assert current.status == "error"
        assert "DRM protected" in (current.error or "")
    finally:
        manager.shutdown()

    def missing_ffmpeg():
        raise FileNotFoundError("ffmpeg executable was not found.")

    manager2 = JobManager(
        base_temp_dir=tmp_path / ".temp_jobs_missing",
        ydl_factory=ErrorYDL,
        ffmpeg_resolver=missing_ffmpeg,
    )
    try:
        job2 = manager2.start_job("https://www.youtube.com/watch?v=bad", "mp3", "192")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            current2 = manager2.get_job(job2.job_id)
            if current2 and current2.status in {"ready", "error"}:
                break
            time.sleep(0.02)
        assert current2.status == "error"
        assert "ffmpeg" in (current2.error or "").lower()
    finally:
        manager2.shutdown()


def test_job_manager_cancel_removes_temp_dir_and_stops_job(tmp_path):
    ffmpeg_dir = tmp_path / "ffmpeg"
    ffmpeg_dir.mkdir()
    started = threading.Event()
    proceed = threading.Event()

    class BlockingYDL:
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
            proceed.wait(timeout=3.0)
            for hook in self.opts["progress_hooks"]:
                hook({"status": "downloading", "downloaded_bytes": 100, "total_bytes": 1000})

    base_temp = tmp_path / ".temp_jobs"
    manager = JobManager(
        base_temp_dir=base_temp,
        ydl_factory=BlockingYDL,
        ffmpeg_resolver=lambda: ffmpeg_dir,
    )
    try:
        job = manager.start_job("https://www.youtube.com/watch?v=abc", "mp3", "192")
        assert started.wait(timeout=3.0)
        assert manager.cancel_job(job.job_id) is True
        proceed.set()

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            current = manager.get_job(job.job_id)
            if current and current.status == "cancelled":
                break
            time.sleep(0.02)

        assert current.status == "cancelled"
        assert not (base_temp / job.job_id).exists()
    finally:
        manager.shutdown()


def test_job_manager_startup_purge_and_eviction(tmp_path):
    base_temp = tmp_path / ".temp_jobs"
    stale_dir = base_temp / "stale-from-crash"
    stale_dir.mkdir(parents=True)
    (stale_dir / "old.part").write_bytes(b"junk")

    ffmpeg_dir = tmp_path / "ffmpeg"
    ffmpeg_dir.mkdir()
    fake_now = [1000.0]

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
            (out_dir / "sample.mp3").write_bytes(b"mp3")

    manager = JobManager(
        base_temp_dir=base_temp,
        ttl_seconds=60,
        max_cached_completed=3,
        ydl_factory=InstantYDL,
        ffmpeg_resolver=lambda: ffmpeg_dir,
        clock=lambda: fake_now[0],
    )
    try:
        manager.startup_purge()
        assert not stale_dir.exists()

        job_ids = []
        for idx in range(5):
            fake_now[0] = 1000.0 + idx
            job = manager.start_job(f"https://example.com/v{idx}", "mp3", "320")
            job_ids.append(job.job_id)
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                cur = manager.get_job(job.job_id)
                if cur and cur.status == "ready":
                    break
                time.sleep(0.01)

        manager.evict_expired()
        # Only newest 3 completed jobs remain on disk
        assert not (base_temp / job_ids[0]).exists()
        assert not (base_temp / job_ids[1]).exists()
        assert (base_temp / job_ids[2]).exists()
        assert (base_temp / job_ids[3]).exists()
        assert (base_temp / job_ids[4]).exists()

        # Advance past TTL -> remaining completed jobs are evicted
        fake_now[0] = 1200.0
        manager.evict_expired()
        for jid in job_ids:
            assert not (base_temp / jid).exists()
    finally:
        manager.shutdown()


def test_inspect_media_rejects_multi_video_url():
    class FakeYDL:
        def __init__(self, opts):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            return {"_type": "multi_video", "title": "Multi Video Post", "entries": [{"id": "1"}, {"id": "2"}]}

    with pytest.raises(MediaInspectError) as exc_info:
        inspect_media(
            "https://example.com/post/multi",
            ydl_factory=FakeYDL,
            url_validator=lambda u: u,
        )
    assert exc_info.value.status_code == 422


def test_job_manager_single_extraction_and_rejects_multi_video_via_real_ytdlp(tmp_path):
    ffmpeg_dir = tmp_path / "ffmpeg"
    ffmpeg_dir.mkdir()
    call_log = []

    class TrackingYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            call_log.append(("extract_info", download))
            return {"_type": "video"}

        def download(self, urls):
            call_log.append(("download", urls))
            out_dir = Path(self.opts["outtmpl"]).parent
            (out_dir / "single.mp3").write_bytes(b"ok")

    manager = JobManager(
        base_temp_dir=tmp_path / ".temp_jobs",
        ydl_factory=TrackingYDL,
        ffmpeg_resolver=lambda: ffmpeg_dir,
    )
    try:
        job = manager.start_job("https://www.youtube.com/watch?v=abc", "mp3", "320")
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            cur = manager.get_job(job.job_id)
            if cur and cur.status in {"ready", "error"}:
                break
            time.sleep(0.01)

        assert cur.status == "ready"
        # Must NOT run a separate extract_info(download=False) before download()
        assert call_log == [("download", ["https://www.youtube.com/watch?v=abc"])]

        # Real YoutubeDL match_filter check on multi_video/playlist ie_result
        import yt_dlp

        captured_opts = []

        class InspectRealYDL(yt_dlp.YoutubeDL):
            def download(self, url_list):
                captured_opts.append(self.params.get("match_filter"))
                return self.process_ie_result(
                    {"_type": "multi_video", "id": "PL1", "title": "Multi", "entries": []},
                    download=True,
                )

        manager2 = JobManager(
            base_temp_dir=tmp_path / ".temp_jobs_2",
            ydl_factory=InspectRealYDL,
            ffmpeg_resolver=lambda: ffmpeg_dir,
        )
        try:
            job2 = manager2.start_job("https://example.com/multi", "mp4", "1080")
            deadline2 = time.monotonic() + 5.0
            while time.monotonic() < deadline2:
                cur2 = manager2.get_job(job2.job_id)
                if cur2 and cur2.status in {"ready", "error"}:
                    break
                time.sleep(0.01)
            assert cur2.status == "error"
            assert "playlist" in (cur2.error or "").lower()
            assert callable(captured_opts[0])
        finally:
            manager2.shutdown()
    finally:
        manager.shutdown()


def test_job_manager_throttles_progress_and_keeps_mp4_multistream_monotonic(tmp_path):
    ffmpeg_dir = tmp_path / "ffmpeg"
    ffmpeg_dir.mkdir()
    release_download = threading.Event()

    class ChunkyMp4YDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def download(self, urls):
            release_download.wait(timeout=3.0)
            out_dir = Path(self.opts["outtmpl"]).parent
            hook = self.opts["progress_hooks"][0]
            phook = self.opts["postprocessor_hooks"][0]

            # Stream 1: 200 tiny video chunks (rapid fire -> should throttle)
            for i in range(1, 201):
                hook({"status": "downloading", "downloaded_bytes": i * 10, "total_bytes": 2000})
            hook({"status": "finished", "filename": str(out_dir / "video.f137.mp4")})

            # Stream 2: 100 tiny audio chunks (must stay monotonic, never reset to 0%)
            for i in range(1, 101):
                hook({"status": "downloading", "downloaded_bytes": i * 10, "total_bytes": 1000})
            hook({"status": "finished", "filename": str(out_dir / "audio.f140.m4a")})

            phook({"status": "started", "postprocessor": "FFmpegMerger"})
            (out_dir / "merged.mp4").write_bytes(b"mp4-merged")

    manager = JobManager(
        base_temp_dir=tmp_path / ".temp_jobs",
        ydl_factory=ChunkyMp4YDL,
        ffmpeg_resolver=lambda: ffmpeg_dir,
    )
    try:
        job = manager.start_job("https://www.youtube.com/watch?v=demo", "mp4", "1080")
        _, q = manager.subscribe(job.job_id)
        release_download.set()

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            cur = manager.get_job(job.job_id)
            if cur and cur.status == "ready":
                break
            time.sleep(0.01)

        events = []
        while not q.empty():
            item = q.get_nowait()
            if item is not None:
                events.append(item)

        assert cur.status == "ready"
        assert len(events) < 120
        progresses = [e["progress"] for e in events]
        assert progresses == sorted(progresses)
        assert progresses[-1] == 100.0
    finally:
        manager.shutdown()
