"""Persistent saved-channel monitoring and artifact storage for the YouTube scanner."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from .channel_scanner import scan_url
from .service import YouTubeScannerService


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class SavedChannel:
    id: int
    url: str
    label: str
    enabled: bool
    last_processed_video_id: str | None


class ChannelStore:
    """SQLite repository for saved channels, processed videos, runs, and artifacts."""

    def __init__(self, path: str = ".cache/youtube_monitoring.sqlite3"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY,
                    url TEXT NOT NULL UNIQUE,
                    label TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_processed_video_id TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS videos (
                    video_id TEXT PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    processed_at TEXT,
                    FOREIGN KEY(channel_id) REFERENCES channels(id)
                );
                CREATE TABLE IF NOT EXISTS scan_runs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    result_json TEXT,
                    errors_json TEXT
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(run_id) REFERENCES scan_runs(id)
                );
                """
            )

    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def add_channel(self, url: str, label: str = "") -> SavedChannel:
        url = url.strip()
        if not url:
            raise ValueError("Channel URL is required.")
        with self._connect() as db:
            db.execute(
                "INSERT INTO channels (url, label, created_at) VALUES (?, ?, ?)",
                (url, label.strip() or url, _now()),
            )
        return next(channel for channel in self.list_channels() if channel.url == url)

    def list_channels(self) -> list[SavedChannel]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM channels ORDER BY id DESC").fetchall()
        return [SavedChannel(row["id"], row["url"], row["label"], bool(row["enabled"]), row["last_processed_video_id"]) for row in rows]

    def set_enabled(self, channel_id: int, enabled: bool) -> None:
        with self._connect() as db:
            db.execute("UPDATE channels SET enabled = ? WHERE id = ?", (int(enabled), channel_id))

    def delete_channel(self, channel_id: int) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM channels WHERE id = ?", (channel_id,))

    def is_processed(self, video_id: str) -> bool:
        with self._connect() as db:
            row = db.execute("SELECT status FROM videos WHERE video_id = ?", (video_id,)).fetchone()
        return bool(row and row["status"] == "completed")

    def record_discovered_video(self, channel_id: int, video) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO videos (video_id, channel_id, title, published_at, status) VALUES (?, ?, ?, ?, 'queued')",
                (video.video_id, channel_id, video.title, video.publish_date.isoformat()),
            )

    def complete_videos(self, videos: list, error: str | None = None) -> None:
        status = "completed" if error is None else "failed"
        with self._connect() as db:
            for video in videos:
                db.execute(
                    "UPDATE videos SET status = ?, error = ?, processed_at = ? WHERE video_id = ?",
                    (status, error, _now(), video.video_id),
                )
                if error is None:
                    db.execute(
                        "UPDATE channels SET last_processed_video_id = ? WHERE id = (SELECT channel_id FROM videos WHERE video_id = ?)",
                        (video.video_id, video.video_id),
                    )

    def start_run(self) -> str:
        run_id = uuid4().hex
        with self._connect() as db:
            db.execute("INSERT INTO scan_runs (id, status, started_at) VALUES (?, 'running', ?)", (run_id, _now()))
        return run_id

    def finish_run(self, run_id: str, result: dict | None, errors: list[str], failed: bool = False) -> None:
        payload = json.dumps(result, default=lambda value: value.model_dump(mode="json") if hasattr(value, "model_dump") else str(value)) if result else None
        with self._connect() as db:
            db.execute(
                "UPDATE scan_runs SET status = ?, completed_at = ?, result_json = ?, errors_json = ? WHERE id = ?",
                ("failed" if failed else "completed", _now(), payload, json.dumps(errors), run_id),
            )

    def record_artifact(self, run_id: str, kind: str, path: Path) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO artifacts (run_id, kind, path, created_at) VALUES (?, ?, ?, ?)", (run_id, kind, str(path), _now()))


class ChannelMonitoringService:
    """Runs one newest unseen public video from each enabled saved channel, sequentially."""

    def __init__(self, config, store: ChannelStore, progress=None):
        self.config = config
        self.store = store
        self.progress = progress or (lambda _: None)

    async def run_latest(self, top_n: int = 5, skip_debate: bool = False) -> tuple[str, dict, list]:
        run_id = self.store.start_run()
        videos, errors = [], []
        try:
            for channel in self.store.list_channels():
                if not channel.enabled:
                    continue
                self.progress(f"Checking latest video: {channel.label}")
                found, skipped = await asyncio.to_thread(scan_url, channel.url, 3650, 1, True)
                errors.extend(skipped)
                if not found:
                    continue
                video = found[0]
                if self.store.is_processed(video.video_id):
                    self.progress(f"Already processed: {channel.label}")
                    continue
                self.store.record_discovered_video(channel.id, video)
                videos.append(video)
            if not videos:
                result = {"reports": [], "all_reports": [], "stocks": [], "unresolved": [], "errors": errors, "videos": []}
                self.store.finish_run(run_id, result, errors)
                return run_id, result, []
            self.progress(f"Analysing {len(videos)} latest video(s), one per saved channel")
            result = await YouTubeScannerService(self.config, self.progress).scan(
                [video.url for video in videos], 3650, 1, top_n, skip_debate=skip_debate,
            )
            errors.extend(result.get("errors", []))
            self.store.complete_videos(videos)
            self.store.finish_run(run_id, result, errors)
            return run_id, result, videos
        except Exception as exc:
            self.store.complete_videos(videos, str(exc))
            errors.append(str(exc))
            self.store.finish_run(run_id, None, errors, failed=True)
            raise
