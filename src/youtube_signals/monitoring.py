"""Tenant-aware saved-channel monitoring, durable runs, and artifact storage."""
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp() -> str:
    return _now().isoformat()


def _subject(value: str) -> str:
    subject = value.strip()
    if not subject:
        raise ValueError("A unique subject/user ID is required.")
    if len(subject) > 128:
        raise ValueError("Subject/user ID must be 128 characters or fewer.")
    return subject


@dataclass(frozen=True)
class SavedChannel:
    id: int
    owner_subject: str
    url: str
    label: str
    enabled: bool
    last_processed_video_id: str | None


class ChannelStore:
    """SQLite repository with strict subject ownership boundaries for every record."""

    def __init__(self, path: str = "user_database/saip_monitoring.sqlite3"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS channels (
                    id INTEGER PRIMARY KEY,
                    owner_subject TEXT NOT NULL,
                    url TEXT NOT NULL,
                    label TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_processed_video_id TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(owner_subject, url)
                );
                CREATE TABLE IF NOT EXISTS videos (
                    owner_subject TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    channel_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    processed_at TEXT,
                    PRIMARY KEY(owner_subject, video_id)
                );
                CREATE TABLE IF NOT EXISTS scan_runs (
                    id TEXT PRIMARY KEY,
                    owner_subject TEXT NOT NULL,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    result_json TEXT,
                    errors_json TEXT
                );
                CREATE TABLE IF NOT EXISTS artifacts (
                    id INTEGER PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    owner_subject TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_runs_subject ON scan_runs(owner_subject, started_at DESC);
                CREATE TABLE IF NOT EXISTS daily_schedule (
                    scheduled_date TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                );
                """
            )

    def _connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _channel(row: sqlite3.Row) -> SavedChannel:
        return SavedChannel(
            row["id"], row["owner_subject"], row["url"], row["label"], bool(row["enabled"]), row["last_processed_video_id"],
        )

    def add_channel(self, owner_subject: str, url: str, label: str = "") -> SavedChannel:
        owner_subject = _subject(owner_subject)
        url = url.strip()
        if not url:
            raise ValueError("Channel URL is required.")
        with self._connect() as db:
            db.execute(
                "INSERT INTO channels (owner_subject, url, label, created_at) VALUES (?, ?, ?, ?)",
                (owner_subject, url, label.strip() or url, _timestamp()),
            )
        return next(channel for channel in self.list_channels(owner_subject) if channel.url == url)

    def list_channels(self, owner_subject: str) -> list[SavedChannel]:
        owner_subject = _subject(owner_subject)
        with self._connect() as db:
            rows = db.execute("SELECT * FROM channels WHERE owner_subject = ? ORDER BY id DESC", (owner_subject,)).fetchall()
        return [self._channel(row) for row in rows]

    def list_enabled_channels(self) -> list[SavedChannel]:
        with self._connect() as db:
            rows = db.execute("SELECT * FROM channels WHERE enabled = 1 ORDER BY owner_subject, id").fetchall()
        return [self._channel(row) for row in rows]

    def set_enabled(self, owner_subject: str, channel_id: int, enabled: bool) -> None:
        with self._connect() as db:
            db.execute("UPDATE channels SET enabled = ? WHERE id = ? AND owner_subject = ?", (int(enabled), channel_id, _subject(owner_subject)))

    def delete_channel(self, owner_subject: str, channel_id: int) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM channels WHERE id = ? AND owner_subject = ?", (channel_id, _subject(owner_subject)))

    def is_processed(self, owner_subject: str, video_id: str) -> bool:
        with self._connect() as db:
            row = db.execute("SELECT status FROM videos WHERE owner_subject = ? AND video_id = ?", (_subject(owner_subject), video_id)).fetchone()
        return bool(row and row["status"] == "completed")

    def record_discovered_video(self, channel: SavedChannel, video) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO videos (owner_subject, video_id, channel_id, title, published_at, status) VALUES (?, ?, ?, ?, ?, 'queued')",
                (channel.owner_subject, video.video_id, channel.id, video.title, video.publish_date.isoformat()),
            )

    def complete_videos(self, owner_subject: str, videos: list, error: str | None = None) -> None:
        status = "completed" if error is None else "failed"
        with self._connect() as db:
            for video in videos:
                db.execute("UPDATE videos SET status = ?, error = ?, processed_at = ? WHERE owner_subject = ? AND video_id = ?", (status, error, _timestamp(), _subject(owner_subject), video.video_id))
                if error is None:
                    db.execute("UPDATE channels SET last_processed_video_id = ? WHERE owner_subject = ? AND id = (SELECT channel_id FROM videos WHERE owner_subject = ? AND video_id = ?)", (video.video_id, _subject(owner_subject), _subject(owner_subject), video.video_id))

    def start_run(self, owner_subject: str, source: str) -> str:
        run_id = uuid4().hex
        with self._connect() as db:
            db.execute("INSERT INTO scan_runs (id, owner_subject, source, status, started_at) VALUES (?, ?, ?, 'running', ?)", (run_id, _subject(owner_subject), source, _timestamp()))
        return run_id

    def finish_run(self, owner_subject: str, run_id: str, result: dict | None, errors: list[str], failed: bool = False) -> None:
        payload = json.dumps(result, default=lambda value: value.model_dump(mode="json") if hasattr(value, "model_dump") else str(value)) if result else None
        with self._connect() as db:
            db.execute("UPDATE scan_runs SET status = ?, completed_at = ?, result_json = ?, errors_json = ? WHERE id = ? AND owner_subject = ?", ("failed" if failed else "completed", _timestamp(), payload, json.dumps(errors), run_id, _subject(owner_subject)))

    def record_artifact(self, owner_subject: str, run_id: str, kind: str, path: Path) -> None:
        with self._connect() as db:
            db.execute("INSERT INTO artifacts (run_id, owner_subject, kind, path, created_at) VALUES (?, ?, ?, ?, ?)", (run_id, _subject(owner_subject), kind, str(path), _timestamp()))

    def queue_daily_approval(self, scheduled_date: str) -> str:
        """Create a no-compute daily approval request unless the day is already terminal."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM daily_schedule WHERE scheduled_date = ?", (scheduled_date,)).fetchone()
            if not row:
                db.execute("INSERT INTO daily_schedule (scheduled_date, status, started_at) VALUES (?, 'pending_approval', ?)", (scheduled_date, _timestamp()))
                return "pending_approval"
            return row["status"]

    def daily_schedule_status(self, scheduled_date: str) -> str | None:
        with self._connect() as db:
            row = db.execute("SELECT status FROM daily_schedule WHERE scheduled_date = ?", (scheduled_date,)).fetchone()
        return row["status"] if row else None

    def approve_daily_schedule(self, scheduled_date: str) -> bool:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute("UPDATE daily_schedule SET status = 'approved', started_at = ?, completed_at = NULL WHERE scheduled_date = ? AND status IN ('pending_approval', 'failed')", (_timestamp(), scheduled_date)).rowcount
        return bool(updated)

    def claim_approved_daily_schedule(self, scheduled_date: str) -> bool:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute("UPDATE daily_schedule SET status = 'running', started_at = ? WHERE scheduled_date = ? AND status = 'approved'", (_timestamp(), scheduled_date)).rowcount
        return bool(updated)

    def finish_daily_schedule(self, scheduled_date: str, failed: bool = False) -> None:
        with self._connect() as db:
            db.execute("UPDATE daily_schedule SET status = ?, completed_at = ? WHERE scheduled_date = ?", ("failed" if failed else "completed", _timestamp(), scheduled_date))


def persist_run_artifacts(store: ChannelStore, owner_subject: str, run_id: str, result: dict) -> dict[str, Path]:
    """Write the tenant-owned CSV and PDF artifacts for a completed run."""
    from .exports import build_scan_csv
    from src.utils.pdf_report import build_scanner_pdf

    output_dir = Path("output/youtube-runs") / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path, pdf_path = output_dir / "youtube_stock_scan.csv", output_dir / "youtube_stock_scan.pdf"
    csv_path.write_text(build_scan_csv(result), encoding="utf-8")
    pdf_path.write_bytes(build_scanner_pdf(result, run_id))
    store.record_artifact(owner_subject, run_id, "csv", csv_path)
    store.record_artifact(owner_subject, run_id, "pdf", pdf_path)
    return {"csv": csv_path, "pdf": pdf_path}


class ChannelMonitoringService:
    """Runs one newest unseen video from each selected channel, sequentially and per subject."""

    def __init__(self, config, store: ChannelStore, owner_subject: str, progress=None):
        self.config, self.store, self.owner_subject = config, store, _subject(owner_subject)
        self.progress = progress or (lambda _: None)

    async def run_latest(self, top_n: int = 5, skip_debate: bool = False, channels: list[SavedChannel] | None = None, source: str = "manual_saved_channel") -> tuple[str, dict, list]:
        run_id = self.store.start_run(self.owner_subject, source)
        videos, errors = [], []
        try:
            for channel in channels if channels is not None else self.store.list_channels(self.owner_subject):
                if not channel.enabled or channel.owner_subject != self.owner_subject:
                    continue
                self.progress(f"Checking latest video: {channel.label}")
                found, skipped = await asyncio.to_thread(scan_url, channel.url, 3650, 1, True)
                errors.extend(skipped)
                if not found:
                    continue
                video = found[0]
                if self.store.is_processed(self.owner_subject, video.video_id):
                    self.progress(f"Already processed: {channel.label}")
                    continue
                self.store.record_discovered_video(channel, video)
                videos.append(video)
            if not videos:
                result = {"reports": [], "all_reports": [], "stocks": [], "unresolved": [], "errors": errors, "videos": []}
                self.store.finish_run(self.owner_subject, run_id, result, errors)
                return run_id, result, []
            self.progress(f"Analysing {len(videos)} latest video(s), one per saved channel")
            result = await YouTubeScannerService(self.config, self.progress).scan([video.url for video in videos], 3650, 1, top_n, skip_debate=skip_debate)
            errors.extend(result.get("errors", []))
            self.store.complete_videos(self.owner_subject, videos)
            self.store.finish_run(self.owner_subject, run_id, result, errors)
            return run_id, result, videos
        except Exception as exc:
            self.store.complete_videos(self.owner_subject, videos, str(exc))
            errors.append(str(exc))
            self.store.finish_run(self.owner_subject, run_id, None, errors, failed=True)
            raise


def queue_daily_approval(store: ChannelStore, now: datetime | None = None) -> tuple[str | None, str | None]:
    """Queue, but never execute, today's daily run after 11:00 AM India time."""
    from zoneinfo import ZoneInfo

    local_now = now.astimezone(ZoneInfo("Asia/Kolkata")) if now else datetime.now(ZoneInfo("Asia/Kolkata"))
    if (local_now.hour, local_now.minute) < (11, 0):
        return None, None
    scheduled_date = local_now.date().isoformat()
    return scheduled_date, store.queue_daily_approval(scheduled_date)


async def run_all_enabled_channels(config, store: ChannelStore, progress=None, source: str = "admin_manual_all_users") -> list[str]:
    """Run every enabled user channel serially after an explicit local-admin action."""
    completed_run_ids = []
    for channel in store.list_enabled_channels():
        service = ChannelMonitoringService(config, store, channel.owner_subject, progress)
        run_id, result, _ = await service.run_latest(channels=[channel], source=source)
        persist_run_artifacts(store, channel.owner_subject, run_id, result)
        completed_run_ids.append(run_id)
    return completed_run_ids


async def run_approved_daily_schedule(config, store: ChannelStore, scheduled_date: str, progress=None) -> list[str]:
    """Execute only an explicitly approved daily run; no approval means no compute."""
    if not store.claim_approved_daily_schedule(scheduled_date):
        return []
    try:
        run_ids = await run_all_enabled_channels(config, store, progress, source="approved_daily")
        store.finish_daily_schedule(scheduled_date)
        return run_ids
    except Exception:
        store.finish_daily_schedule(scheduled_date, failed=True)
        raise
