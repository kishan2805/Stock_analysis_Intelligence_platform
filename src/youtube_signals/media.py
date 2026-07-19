"""Locate an ffmpeg executable from the system or the Python dependency."""
from __future__ import annotations
import shutil


def get_ffmpeg_path() -> str | None:
    if path := shutil.which("ffmpeg"):
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None
