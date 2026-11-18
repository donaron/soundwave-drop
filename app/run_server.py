"""Local launcher that picks an open loopback port and opens the browser."""

from __future__ import annotations

import argparse
import os
import socket
import threading
import time
import webbrowser

import uvicorn


def find_available_port(
    host: str = "127.0.0.1",
    preferred: int = 8000,
    max_tries: int = 11,
) -> int:
    """Return the first bindable TCP port starting at preferred."""
    for offset in range(max_tries):
        candidate = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, candidate))
                return candidate
            except OSError:
                continue
    raise RuntimeError(
        f"No free port available on {host} in range {preferred}-{preferred + max_tries - 1}."
    )


def _open_browser_when_ready(host: str, port: int) -> None:
    url = f"http://{host}:{port}"
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.3):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.15)


def main(argv: list[str] | None = None) -> None:
    """Launch the private media downloader server on 127.0.0.1."""
    parser = argparse.ArgumentParser(description="Run Private Media Downloader locally.")
    parser.add_argument("--port", type=int, default=None, help="Specific loopback port")
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open browser")
    args = parser.parse_args(argv)

    host = "127.0.0.1"
    env_port = os.environ.get("PORT", "").strip()
    if args.port is not None:
        port = args.port
    elif env_port.isdigit():
        port = int(env_port)
    else:
        port = find_available_port(host=host, preferred=8000, max_tries=11)

    print(f"Private Media Downloader running at http://{host}:{port}")
    if not args.no_browser:
        threading.Thread(
            target=_open_browser_when_ready,
            args=(host, port),
            daemon=True,
        ).start()

    uvicorn.run("app.main:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
