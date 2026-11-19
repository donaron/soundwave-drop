from fastapi.testclient import TestClient

from app.main import create_app


def test_root_serves_ui_with_expected_controls(tmp_path):
    from app.media_service import JobManager

    manager = JobManager(base_temp_dir=tmp_path / ".temp_jobs")
    with TestClient(create_app(manager=manager)) as client:
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
        assert '<div id="thumb-fallback"' in html
        assert 'id="theme-bar"' in html
        assert 'id="active-theme-name"' in html
        import re
        assert len(re.findall(r'data-theme="[^"]+"', html)) >= 10
        assert "<title>Soundwave Drop</title>" in html
        assert "<h1>Soundwave Drop</h1>" in html
        assert "/static/favicon.svg" in html
        assert "/static/app.js" in html
        assert "/static/styles.css" in html

        svg_resp = client.get("/static/favicon.svg")
        assert svg_resp.status_code == 200
        assert "svg" in svg_resp.headers["content-type"].lower()

        js_resp = client.get("/static/app.js")
        assert js_resp.status_code == 200
        assert "javascript" in js_resp.headers["content-type"].lower()

        css_resp = client.get("/static/styles.css")
        assert css_resp.status_code == 200
        assert "text/css" in css_resp.headers["content-type"].lower()


def test_frontend_inspect_abort_and_expired_save_again_behavior():
    import shutil
    import subprocess

    node_bin = shutil.which("node")
    assert node_bin is not None
    proc = subprocess.run(
        [node_bin, "tests/test_frontend_behavior.mjs"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
