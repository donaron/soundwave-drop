"""Locate the ffmpeg executable directory across env, PATH, and WinGet."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Callable, Mapping


def resolve_ffmpeg_dir(
    env: Mapping[str, str] | None = None,
    which_fn: Callable[[str], str | None] = shutil.which,
    winget_root: Path | None = None,
) -> Path:
    """Return the directory containing ffmpeg, or raise FileNotFoundError."""
    active_env = os.environ if env is None else env

    explicit = active_env.get("FFMPEG_PATH", "").strip()
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return candidate.parent
        if candidate.is_dir() and (
            (candidate / "ffmpeg.exe").is_file() or (candidate / "ffmpeg").is_file()
        ):
            return candidate

    on_path = which_fn("ffmpeg")
    if on_path:
        path_candidate = Path(on_path)
        if path_candidate.is_file():
            return path_candidate.parent

    if winget_root is None:
        local_appdata = active_env.get("LOCALAPPDATA", "").strip()
        if local_appdata:
            winget_root = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages"

    if winget_root is not None and winget_root.is_dir():
        matches = sorted(winget_root.rglob("ffmpeg.exe"))
        if matches:
            return matches[0].parent

    raise FileNotFoundError(
        "ffmpeg executable was not found. Install ffmpeg or set FFMPEG_PATH."
    )
