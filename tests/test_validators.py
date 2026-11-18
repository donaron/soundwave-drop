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
        "   ",
        "not-a-url",
        "file:///C:/Windows/System32/drivers/etc/hosts",
        "ftp://example.com/file.mp3",
        "javascript:alert(1)",
        "http://localhost:8000/test",
        "http://api.localhost/test",
        "http://nas.local/test",
        "http://127.0.0.1/test",
        "http://0.0.0.0/test",
        "http://[::1]/test",
        "http://169.254.169.254/latest/meta-data",
        "http://192.168.1.10/video",
        "http://10.0.0.5/video",
        "http://172.16.0.1/video",
    ],
)
def test_validate_public_url_rejects_unsafe_schemes_and_private_hosts(bad_url):
    with pytest.raises(ValidationError):
        validate_public_url(bad_url, resolver=_public_resolver)


def test_validate_public_url_rejects_dns_resolving_to_loopback_or_private():
    def local_v4(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    def local_v6(host, port, *args, **kwargs):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::1", 0, 0, 0))]

    with pytest.raises(ValidationError):
        validate_public_url("https://rebind.example.com/watch?v=1", resolver=local_v4)
    with pytest.raises(ValidationError):
        validate_public_url("https://rebind6.example.com/watch?v=1", resolver=local_v6)


def test_validate_public_url_rejects_unresolvable_host():
    def failing_resolver(host, port, *args, **kwargs):
        raise socket.gaierror("name resolution failed")

    with pytest.raises(ValidationError):
        validate_public_url("https://nonexistent.invalid/video", resolver=failing_resolver)


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


def test_build_content_disposition_handles_long_and_all_illegal_names():
    long_header = build_content_disposition(("A" * 200) + ".mp4")
    ascii_long = long_header.split('filename="')[1].split('"')[0]
    assert len(ascii_long) <= 120
    assert ascii_long.endswith(".mp4")

    fallback_header = build_content_disposition('???***""".mp3')
    ascii_fallback = fallback_header.split('filename="')[1].split('"')[0]
    assert ascii_fallback == "download.mp3"


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
