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
        assert "/static/app.js" in html
        assert "/static/styles.css" in html

        js_resp = client.get("/static/app.js")
        assert js_resp.status_code == 200
        assert "javascript" in js_resp.headers["content-type"].lower()

        css_resp = client.get("/static/styles.css")
        assert css_resp.status_code == 200
        assert "text/css" in css_resp.headers["content-type"].lower()
