def test_dependencies_importable():
    import fastapi
    import uvicorn
    import yt_dlp

    assert fastapi.__version__
    assert uvicorn.__version__
    assert yt_dlp.version.__version__
