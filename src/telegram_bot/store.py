"""Durable user preferences and private SAIP analysis jobs for Telegram."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from uuid import uuid4


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


REPORT_CACHE_TTL_DAYS = 7


@dataclass(frozen=True)
class TelegramUser:
    telegram_user_id: int
    subject_id: str
    chat_id: int
    display_name: str
    username: str | None
    notifications_enabled: bool
    duration_months: int
    analysis_depth: str


@dataclass(frozen=True)
class AnalysisJob:
    id: str
    owner_subject: str
    telegram_user_id: int
    chat_id: int
    ticker: str
    exchange: str
    duration_months: int
    depth: str
    status: str
    created_at: str
    started_at: str | None
    completed_at: str | None
    result_json: str | None
    pdf_path: str | None
    error: str | None
    progress_text: str | None
    updated_at: str | None
    cache_source_job_id: str | None

    def result(self) -> dict | None:
        return json.loads(self.result_json) if self.result_json else None


@dataclass(frozen=True)
class VideoAnalysisJob:
    id: str
    owner_subject: str
    telegram_user_id: int
    chat_id: int
    video_url: str
    status: str
    created_at: str
    started_at: str | None
    completed_at: str | None
    result_json: str | None
    pdf_path: str | None
    error: str | None
    progress_text: str | None
    updated_at: str | None

    def result(self) -> dict | None:
        return json.loads(self.result_json) if self.result_json else None


class TelegramStore:
    """Repository that keeps Telegram data isolated by SAIP subject ID."""

    def __init__(self, path: str = "user_database/saip_monitoring.sqlite3"):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS telegram_users (
                    telegram_user_id INTEGER PRIMARY KEY,
                    subject_id TEXT NOT NULL UNIQUE,
                    chat_id INTEGER NOT NULL,
                    display_name TEXT NOT NULL,
                    username TEXT,
                    notifications_enabled INTEGER NOT NULL DEFAULT 1,
                    duration_months INTEGER NOT NULL DEFAULT 18,
                    analysis_depth TEXT NOT NULL DEFAULT 'balanced',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS telegram_analysis_jobs (
                    id TEXT PRIMARY KEY,
                    owner_subject TEXT NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    ticker TEXT NOT NULL,
                    exchange TEXT NOT NULL,
                    duration_months INTEGER NOT NULL,
                    depth TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    result_json TEXT,
                    pdf_path TEXT,
                    error TEXT,
                    progress_text TEXT,
                    updated_at TEXT,
                    cache_source_job_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_telegram_jobs_owner
                    ON telegram_analysis_jobs(owner_subject, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_telegram_jobs_status
                    ON telegram_analysis_jobs(status, created_at);
                CREATE TABLE IF NOT EXISTS telegram_video_analysis_jobs (
                    id TEXT PRIMARY KEY,
                    owner_subject TEXT NOT NULL,
                    telegram_user_id INTEGER NOT NULL,
                    chat_id INTEGER NOT NULL,
                    video_url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    result_json TEXT,
                    pdf_path TEXT,
                    error TEXT,
                    progress_text TEXT,
                    updated_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_telegram_video_jobs_owner
                    ON telegram_video_analysis_jobs(owner_subject, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_telegram_video_jobs_status
                    ON telegram_video_analysis_jobs(status, created_at);
                """
            )
            self._ensure_column(db, "telegram_analysis_jobs", "progress_text", "TEXT")
            self._ensure_column(db, "telegram_analysis_jobs", "updated_at", "TEXT")
            self._ensure_column(db, "telegram_analysis_jobs", "cache_source_job_id", "TEXT")
            self._ensure_column(db, "telegram_video_analysis_jobs", "progress_text", "TEXT")
            self._ensure_column(db, "telegram_video_analysis_jobs", "updated_at", "TEXT")
            self._backfill_progress(db, "telegram_analysis_jobs", "Stock analysis")
            self._backfill_progress(db, "telegram_video_analysis_jobs", "YouTube video analysis")

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _backfill_progress(db: sqlite3.Connection, table: str, label: str) -> None:
        db.execute(
            f"""
            UPDATE {table}
            SET progress_text = CASE status
                WHEN 'queued' THEN 'Waiting to start'
                WHEN 'running' THEN 'Running {label.lower()}'
                WHEN 'completed' THEN '{label} complete'
                WHEN 'failed' THEN '{label} failed'
                ELSE progress_text
            END
            WHERE progress_text IS NULL
            """
        )

    @staticmethod
    def _user(row: sqlite3.Row) -> TelegramUser:
        return TelegramUser(
            telegram_user_id=row["telegram_user_id"],
            subject_id=row["subject_id"],
            chat_id=row["chat_id"],
            display_name=row["display_name"],
            username=row["username"],
            notifications_enabled=bool(row["notifications_enabled"]),
            duration_months=row["duration_months"],
            analysis_depth=row["analysis_depth"],
        )

    @staticmethod
    def _job(row: sqlite3.Row) -> AnalysisJob:
        return AnalysisJob(
            id=row["id"], owner_subject=row["owner_subject"], telegram_user_id=row["telegram_user_id"],
            chat_id=row["chat_id"], ticker=row["ticker"], exchange=row["exchange"],
            duration_months=row["duration_months"], depth=row["depth"], status=row["status"],
            created_at=row["created_at"], started_at=row["started_at"], completed_at=row["completed_at"],
            result_json=row["result_json"], pdf_path=row["pdf_path"], error=row["error"],
            progress_text=row["progress_text"], updated_at=row["updated_at"],
            cache_source_job_id=row["cache_source_job_id"],
        )

    @staticmethod
    def _video_job(row: sqlite3.Row) -> VideoAnalysisJob:
        return VideoAnalysisJob(
            id=row["id"], owner_subject=row["owner_subject"], telegram_user_id=row["telegram_user_id"],
            chat_id=row["chat_id"], video_url=row["video_url"], status=row["status"],
            created_at=row["created_at"], started_at=row["started_at"], completed_at=row["completed_at"],
            result_json=row["result_json"], pdf_path=row["pdf_path"], error=row["error"],
            progress_text=row["progress_text"], updated_at=row["updated_at"],
        )

    def ensure_user(self, telegram_user_id: int, chat_id: int, display_name: str, username: str | None) -> TelegramUser:
        subject_id = f"telegram:{telegram_user_id}"
        now = _timestamp()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO telegram_users (
                    telegram_user_id, subject_id, chat_id, display_name, username, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    chat_id = excluded.chat_id,
                    display_name = excluded.display_name,
                    username = excluded.username,
                    updated_at = excluded.updated_at
                """,
                (telegram_user_id, subject_id, chat_id, display_name, username, now, now),
            )
        return self.get_user(telegram_user_id)  # type: ignore[return-value]

    def get_user(self, telegram_user_id: int) -> TelegramUser | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM telegram_users WHERE telegram_user_id = ?", (telegram_user_id,)).fetchone()
        return self._user(row) if row else None

    def update_preferences(
        self,
        subject_id: str,
        *,
        notifications_enabled: bool | None = None,
        duration_months: int | None = None,
        analysis_depth: str | None = None,
    ) -> TelegramUser:
        fields, values = ["updated_at = ?"], [_timestamp()]
        if notifications_enabled is not None:
            fields.append("notifications_enabled = ?")
            values.append(int(notifications_enabled))
        if duration_months is not None:
            if duration_months not in {6, 12, 18, 24, 36, 60}:
                raise ValueError("Unsupported analysis horizon.")
            fields.append("duration_months = ?")
            values.append(duration_months)
        if analysis_depth is not None:
            if analysis_depth not in {"quick", "balanced", "premium"}:
                raise ValueError("Unsupported analysis depth.")
            fields.append("analysis_depth = ?")
            values.append(analysis_depth)
        values.append(subject_id)
        with self._connect() as db:
            db.execute(f"UPDATE telegram_users SET {', '.join(fields)} WHERE subject_id = ?", values)
            row = db.execute("SELECT * FROM telegram_users WHERE subject_id = ?", (subject_id,)).fetchone()
        if not row:
            raise ValueError("Telegram user profile not found.")
        return self._user(row)

    def create_analysis_job(self, user: TelegramUser, ticker: str, exchange: str) -> AnalysisJob:
        job_id, now = uuid4().hex, _timestamp()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO telegram_analysis_jobs (
                    id, owner_subject, telegram_user_id, chat_id, ticker, exchange,
                    duration_months, depth, status, created_at, progress_text, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, 'Waiting to start', ?)
                """,
                (
                    job_id, user.subject_id, user.telegram_user_id, user.chat_id, ticker, exchange,
                    user.duration_months, user.analysis_depth, now, now,
                ),
            )
        return self.get_job(job_id)  # type: ignore[return-value]

    def find_cached_analysis_report(
        self,
        ticker: str,
        exchange: str,
        duration_months: int,
        depth: str,
        *,
        exclude_job_id: str | None = None,
    ) -> AnalysisJob | None:
        """Find one generated stock report still valid for the seven-day cache."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=REPORT_CACHE_TTL_DAYS)).isoformat()
        query = """
            SELECT * FROM telegram_analysis_jobs
            WHERE ticker = ? AND exchange = ? AND duration_months = ? AND depth = ?
              AND status = 'completed' AND completed_at >= ?
              AND result_json IS NOT NULL AND pdf_path IS NOT NULL
              AND cache_source_job_id IS NULL
        """
        values: list[str | int] = [ticker, exchange, duration_months, depth, cutoff]
        if exclude_job_id:
            query += " AND id != ?"
            values.append(exclude_job_id)
        query += " ORDER BY completed_at DESC"
        with self._connect() as db:
            rows = db.execute(query, values).fetchall()
        for row in rows:
            job = self._job(row)
            if job.pdf_path and Path(job.pdf_path).is_file():
                return job
        return None

    def create_cached_analysis_job(self, user: TelegramUser, ticker: str, exchange: str) -> AnalysisJob | None:
        """Create a completed requester-owned record from a reusable report."""
        source = self.find_cached_analysis_report(ticker, exchange, user.duration_months, user.analysis_depth)
        if not source:
            return None
        now, job_id = _timestamp(), uuid4().hex
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO telegram_analysis_jobs (
                    id, owner_subject, telegram_user_id, chat_id, ticker, exchange,
                    duration_months, depth, status, created_at, completed_at, result_json,
                    pdf_path, progress_text, updated_at, cache_source_job_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id, user.subject_id, user.telegram_user_id, user.chat_id, ticker, exchange,
                    user.duration_months, user.analysis_depth, now, now, source.result_json,
                    source.pdf_path, "Reused cached report generated within the last 7 days", now, source.id,
                ),
            )
        return self.get_job(job_id)

    def complete_job_from_cache(self, job_id: str, source: AnalysisJob) -> AnalysisJob | None:
        """Finish an already-claimed duplicate job without rerunning the pipeline."""
        now = _timestamp()
        with self._connect() as db:
            updated = db.execute(
                """
                UPDATE telegram_analysis_jobs
                SET status = 'completed', completed_at = ?, result_json = ?, pdf_path = ?, error = NULL,
                    progress_text = 'Reused cached report generated within the last 7 days', updated_at = ?,
                    cache_source_job_id = ?
                WHERE id = ? AND status = 'running'
                """,
                (now, source.result_json, source.pdf_path, now, source.id, job_id),
            ).rowcount
            row = db.execute("SELECT * FROM telegram_analysis_jobs WHERE id = ?", (job_id,)).fetchone() if updated else None
        return self._job(row) if row else None

    def get_job(self, job_id: str) -> AnalysisJob | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM telegram_analysis_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job(row) if row else None

    def claim_job(self, job_id: str) -> AnalysisJob | None:
        """Atomically claim a queued job so two bot workers cannot run it twice."""
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute(
                """
                UPDATE telegram_analysis_jobs
                SET status = 'running', started_at = ?, updated_at = ?, progress_text = 'Starting stock analysis'
                WHERE id = ? AND status = 'queued'
                """,
                (_timestamp(), _timestamp(), job_id),
            ).rowcount
            row = db.execute("SELECT * FROM telegram_analysis_jobs WHERE id = ?", (job_id,)).fetchone() if updated else None
        return self._job(row) if row else None

    def queued_jobs(self, limit: int = 10) -> list[AnalysisJob]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM telegram_analysis_jobs WHERE status = 'queued' ORDER BY created_at LIMIT ?", (limit,)
            ).fetchall()
        return [self._job(row) for row in rows]

    def requeue_interrupted_jobs(self) -> int:
        """Return unfinished work to the queue when the bot process restarts."""
        now = _timestamp()
        with self._connect() as db:
            stock_count = db.execute(
                """
                UPDATE telegram_analysis_jobs
                SET status = 'queued', started_at = NULL, progress_text = 'Recovered after bot restart', updated_at = ?
                WHERE status = 'running'
                """,
                (now,),
            ).rowcount
            video_count = db.execute(
                """
                UPDATE telegram_video_analysis_jobs
                SET status = 'queued', started_at = NULL, progress_text = 'Recovered after bot restart', updated_at = ?
                WHERE status = 'running'
                """,
                (now,),
            ).rowcount
        return stock_count + video_count

    def complete_job(self, job_id: str, result: dict, pdf_path: Path) -> None:
        payload = json.dumps(result, default=str)
        with self._connect() as db:
            db.execute(
                """
                UPDATE telegram_analysis_jobs
                SET status = 'completed', completed_at = ?, result_json = ?, pdf_path = ?, error = NULL,
                    progress_text = 'Stock analysis complete', updated_at = ?, cache_source_job_id = NULL
                WHERE id = ? AND status = 'running'
                """,
                (_timestamp(), payload, str(pdf_path), _timestamp(), job_id),
            )

    def fail_job(self, job_id: str, error: str) -> None:
        with self._connect() as db:
            db.execute(
                """
                UPDATE telegram_analysis_jobs
                SET status = 'failed', completed_at = ?, error = ?, progress_text = 'Stock analysis failed', updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (_timestamp(), error[:1000], _timestamp(), job_id),
            )

    def latest_completed_report(self, subject_id: str, ticker: str | None = None) -> AnalysisJob | None:
        query = "SELECT * FROM telegram_analysis_jobs WHERE owner_subject = ? AND status = 'completed'"
        values: list[str] = [subject_id]
        if ticker:
            query += " AND ticker = ?"
            values.append(ticker)
        query += " ORDER BY completed_at DESC LIMIT 1"
        with self._connect() as db:
            row = db.execute(query, values).fetchone()
        return self._job(row) if row else None

    def create_video_job(self, user: TelegramUser, video_url: str) -> VideoAnalysisJob:
        job_id, now = uuid4().hex, _timestamp()
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO telegram_video_analysis_jobs (
                    id, owner_subject, telegram_user_id, chat_id, video_url, status, created_at, progress_text, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'queued', ?, 'Waiting to start', ?)
                """,
                (job_id, user.subject_id, user.telegram_user_id, user.chat_id, video_url, now, now),
            )
        return self.get_video_job(job_id)  # type: ignore[return-value]

    def get_video_job(self, job_id: str) -> VideoAnalysisJob | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM telegram_video_analysis_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._video_job(row) if row else None

    def claim_video_job(self, job_id: str) -> VideoAnalysisJob | None:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute(
                """
                UPDATE telegram_video_analysis_jobs
                SET status = 'running', started_at = ?, updated_at = ?, progress_text = 'Starting YouTube video analysis'
                WHERE id = ? AND status = 'queued'
                """,
                (_timestamp(), _timestamp(), job_id),
            ).rowcount
            row = db.execute("SELECT * FROM telegram_video_analysis_jobs WHERE id = ?", (job_id,)).fetchone() if updated else None
        return self._video_job(row) if row else None

    def queued_video_jobs(self, limit: int = 10) -> list[VideoAnalysisJob]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM telegram_video_analysis_jobs WHERE status = 'queued' ORDER BY created_at LIMIT ?", (limit,)
            ).fetchall()
        return [self._video_job(row) for row in rows]

    def complete_video_job(self, job_id: str, result: dict, pdf_path: Path) -> None:
        with self._connect() as db:
            db.execute(
                """
                UPDATE telegram_video_analysis_jobs
                SET status = 'completed', completed_at = ?, result_json = ?, pdf_path = ?, error = NULL,
                    progress_text = 'YouTube video analysis complete', updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (_timestamp(), json.dumps(result, default=str), str(pdf_path), _timestamp(), job_id),
            )

    def fail_video_job(self, job_id: str, error: str) -> None:
        with self._connect() as db:
            db.execute(
                """
                UPDATE telegram_video_analysis_jobs
                SET status = 'failed', completed_at = ?, error = ?, progress_text = 'YouTube video analysis failed', updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (_timestamp(), error[:1000], _timestamp(), job_id),
            )

    def update_stock_progress(self, job_id: str, progress_text: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE telegram_analysis_jobs SET progress_text = ?, updated_at = ? WHERE id = ? AND status = 'running'",
                (progress_text[:500], _timestamp(), job_id),
            )

    def update_video_progress(self, job_id: str, progress_text: str) -> None:
        with self._connect() as db:
            db.execute(
                "UPDATE telegram_video_analysis_jobs SET progress_text = ?, updated_at = ? WHERE id = ? AND status = 'running'",
                (progress_text[:500], _timestamp(), job_id),
            )

    def claim_next_fcfs_job(self) -> tuple[str, AnalysisJob | VideoAnalysisJob] | None:
        """Atomically claim the oldest queued stock/video job across all users."""
        now = _timestamp()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            active_job = db.execute(
                """
                SELECT 1
                FROM (
                    SELECT id FROM telegram_analysis_jobs WHERE status = 'running'
                    UNION ALL
                    SELECT id FROM telegram_video_analysis_jobs WHERE status = 'running'
                )
                LIMIT 1
                """
            ).fetchone()
            if active_job:
                return None
            next_job = db.execute(
                """
                SELECT kind, id
                FROM (
                    SELECT 'stock' AS kind, id, created_at FROM telegram_analysis_jobs WHERE status = 'queued'
                    UNION ALL
                    SELECT 'video' AS kind, id, created_at FROM telegram_video_analysis_jobs WHERE status = 'queued'
                )
                ORDER BY created_at ASC, id ASC
                LIMIT 1
                """
            ).fetchone()
            if not next_job:
                return None
            kind, job_id = next_job["kind"], next_job["id"]
            if kind == "stock":
                db.execute(
                    """
                    UPDATE telegram_analysis_jobs
                    SET status = 'running', started_at = ?, updated_at = ?, progress_text = 'Starting stock analysis'
                    WHERE id = ? AND status = 'queued'
                    """,
                    (now, now, job_id),
                )
                row = db.execute("SELECT * FROM telegram_analysis_jobs WHERE id = ?", (job_id,)).fetchone()
                return "stock", self._job(row)
            db.execute(
                """
                UPDATE telegram_video_analysis_jobs
                SET status = 'running', started_at = ?, updated_at = ?, progress_text = 'Starting YouTube video analysis'
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, job_id),
            )
            row = db.execute("SELECT * FROM telegram_video_analysis_jobs WHERE id = ?", (job_id,)).fetchone()
            return "video", self._video_job(row)

    def reject_queued_job(self, kind: str, job_id: str) -> AnalysisJob | VideoAnalysisJob | None:
        """Reject only a job that has not begun consuming compute."""
        if kind not in {"stock", "video"}:
            raise ValueError("Unknown Telegram job type.")
        table = "telegram_analysis_jobs" if kind == "stock" else "telegram_video_analysis_jobs"
        now = _timestamp()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute(
                f"""
                UPDATE {table}
                SET status = 'rejected', completed_at = ?, progress_text = 'Rejected by SAIP admin',
                    error = 'Rejected by SAIP admin before analysis began', updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, job_id),
            ).rowcount
            if not updated:
                return None
            row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (job_id,)).fetchone()
        return self._job(row) if kind == "stock" else self._video_job(row)

    def cancel_running_job(self, kind: str, job_id: str) -> AnalysisJob | VideoAnalysisJob | None:
        """Cancel a running job before the worker is forcibly restarted."""
        if kind not in {"stock", "video"}:
            raise ValueError("Unknown Telegram job type.")
        table = "telegram_analysis_jobs" if kind == "stock" else "telegram_video_analysis_jobs"
        now = _timestamp()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            updated = db.execute(
                f"""
                UPDATE {table}
                SET status = 'rejected', completed_at = ?, progress_text = 'Cancelled by SAIP admin',
                    error = 'Cancelled by SAIP admin after analysis began', updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (now, now, job_id),
            ).rowcount
            if not updated:
                return None
            row = db.execute(f"SELECT * FROM {table} WHERE id = ?", (job_id,)).fetchone()
        return self._job(row) if kind == "stock" else self._video_job(row)

    def admin_job_activity(self, limit: int = 30) -> list[dict]:
        """Return recent stock/video work for the authenticated SAIP Admin view."""
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT 'Stock' AS kind, 'stock' AS job_type, id, owner_subject, chat_id, ticker AS target, status, progress_text,
                       created_at, started_at, completed_at, updated_at, error
                FROM telegram_analysis_jobs
                UNION ALL
                SELECT 'YouTube video' AS kind, 'video' AS job_type, id, owner_subject, chat_id, video_url AS target, status, progress_text,
                       created_at, started_at, completed_at, updated_at, error
                FROM telegram_video_analysis_jobs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
