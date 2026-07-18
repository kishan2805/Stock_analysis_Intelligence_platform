from __future__ import annotations
from datetime import date, datetime, timedelta
import re
import shutil
from .media import get_ffmpeg_path
from .schemas import VideoMeta


def is_video_url(url: str) -> bool:
    return bool(re.search(r"(?:youtu\.be/|[?&]v=|/shorts/|/live/)", url))


def scan_url(url: str, lookback_days: int, max_videos: int, include_shorts: bool = True) -> tuple[list[VideoMeta], list[str]]:
    """Read public metadata only. Returns useful skip/errors rather than failing a scan."""
    try:
        import yt_dlp
    except ImportError:
        return [], ["yt-dlp is not installed. Run pip install -r requirements.txt."]
    opts = {"quiet": True, "skip_download": True, "extract_flat": "in_playlist", "playlistend": max_videos if not is_video_url(url) else 1}
    node = shutil.which("node")
    if node:
        # Newer yt-dlp releases enable only Deno by default. Node is already
        # installed on many developer machines and is sufficient for EJS.
        opts["js_runtimes"] = {"node": {"path": node}}
    if ffmpeg := get_ffmpeg_path():
        opts["ffmpeg_location"] = ffmpeg
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        return [], [f"Could not access {url}: {exc}"]
    entries = info.get("entries") or [info]
    cutoff = date.today() - timedelta(days=lookback_days)
    videos, skipped = [], []
    for entry in entries:
        if not entry:
            continue
        raw_date = entry.get("upload_date")
        published = datetime.strptime(raw_date, "%Y%m%d").date() if raw_date else date.today()
        duration = int(entry.get("duration") or 0)
        if not is_video_url(url) and published < cutoff:
            continue
        if not include_shorts and duration and duration < 60:
            continue
        video_id = entry.get("id")
        if not video_id:
            skipped.append(f"Skipped an item without a video ID from {url}")
            continue
        videos.append(VideoMeta(video_id=video_id, channel_name=entry.get("channel") or info.get("channel") or "Unknown channel", channel_url=entry.get("channel_url") or url, title=entry.get("title") or "Untitled", publish_date=published, url=f"https://www.youtube.com/watch?v={video_id}", duration_seconds=duration))
    return videos[:max_videos], skipped
