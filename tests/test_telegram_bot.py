from pathlib import Path

from src.telegram_bot.bot import _is_youtube_channel_url, _is_youtube_video_url
from src.telegram_bot.stocks import resolve_stock_options, resolve_stock_request
from src.telegram_bot.store import TelegramStore
from src.telegram_bot.worker import TelegramWorkerManager, WorkerStatus
from src.utils.pdf_report import _financial_metric_rows


def test_telegram_profile_uses_a_stable_private_subject(tmp_path):
    store = TelegramStore(str(tmp_path / "monitoring.sqlite3"))
    user = store.ensure_user(12345, 12345, "Kishan", "kishan")
    moved_chat = store.ensure_user(12345, 99999, "Kishan K", "kishan_k")

    assert user.subject_id == "telegram:12345"
    assert moved_chat.subject_id == user.subject_id
    assert moved_chat.chat_id == 99999
    assert moved_chat.analysis_depth == "balanced"


def test_private_analysis_job_can_only_be_claimed_once(tmp_path):
    store = TelegramStore(str(tmp_path / "monitoring.sqlite3"))
    user = store.ensure_user(12345, 12345, "Kishan", None)
    job = store.create_analysis_job(user, "RELIANCE.NS", "IN")

    claimed = store.claim_job(job.id)
    assert claimed is not None
    assert claimed.status == "running"
    assert store.claim_job(job.id) is None

    report = Path(tmp_path / "report.pdf")
    report.write_bytes(b"pdf")
    store.complete_job(job.id, {"cio": {"final_rating": 8}}, report)
    saved = store.latest_completed_report(user.subject_id, "RELIANCE.NS")
    assert saved is not None
    assert saved.result() == {"cio": {"final_rating": 8}}
    assert saved.pdf_path == str(report)


def test_admin_activity_identifies_stock_and_video_work_and_progress(tmp_path):
    store = TelegramStore(str(tmp_path / "monitoring.sqlite3"))
    user = store.ensure_user(12345, 12345, "Kishan", None)
    stock_job = store.create_analysis_job(user, "AAPL", "US")
    video_job = store.create_video_job(user, "https://youtu.be/abc123")

    store.claim_job(stock_job.id)
    store.update_stock_progress(stock_job.id, "Running specialist agents")
    activity = {item["id"]: item for item in store.admin_job_activity()}

    assert activity[stock_job.id]["kind"] == "Stock"
    assert activity[stock_job.id]["progress_text"] == "Running specialist agents"
    assert activity[video_job.id]["kind"] == "YouTube video"


def test_preferences_are_validated_and_persisted(tmp_path):
    store = TelegramStore(str(tmp_path / "monitoring.sqlite3"))
    user = store.ensure_user(7, 7, "User", None)
    changed = store.update_preferences(user.subject_id, notifications_enabled=False, duration_months=36, analysis_depth="premium")

    assert not changed.notifications_enabled
    assert changed.duration_months == 36
    assert changed.analysis_depth == "premium"


def test_stock_requests_require_safe_ticker_syntax_or_known_name():
    assert resolve_stock_request("Reliance").ticker == "RELIANCE.NS"
    assert resolve_stock_request("reliance.ns").exchange == "IN"
    assert resolve_stock_request("AAPL").exchange == "US"
    assert resolve_stock_request("unknown & co") is None


def test_cross_market_stock_name_requires_an_exchange_choice():
    options = resolve_stock_options("Infosys")

    assert len(options) == 2
    assert [(option.ticker, option.exchange) for option in options] == [("INFY.NS", "IN"), ("INFY", "US")]
    assert resolve_stock_request("Infosys") is None
    assert resolve_stock_request("Cupid").ticker == "CUPID.NS"
    assert resolve_stock_request("CUPID.NS").exchange == "IN"
    assert resolve_stock_request("Apple") is None


def test_channel_input_only_accepts_public_youtube_channel_urls():
    assert _is_youtube_channel_url("https://www.youtube.com/@example/videos")
    assert _is_youtube_channel_url("https://youtube.com/channel/UC123")
    assert not _is_youtube_channel_url("https://notyoutube.com/@example")
    assert not _is_youtube_channel_url("https://www.youtube.com/watch?v=abc")


def test_video_input_accepts_supported_public_youtube_video_urls_only():
    assert _is_youtube_video_url("https://www.youtube.com/watch?v=abc123")
    assert _is_youtube_video_url("https://youtu.be/abc123")
    assert _is_youtube_video_url("https://www.youtube.com/shorts/abc123")
    assert not _is_youtube_video_url("https://www.youtube.com/@example/videos")
    assert not _is_youtube_video_url("https://t.me/example")


def test_video_analysis_job_is_durable_and_claimed_once(tmp_path):
    store = TelegramStore(str(tmp_path / "monitoring.sqlite3"))
    user = store.ensure_user(99, 99, "User", None)
    job = store.create_video_job(user, "https://youtu.be/abc123")

    assert store.claim_video_job(job.id) is not None
    assert store.claim_video_job(job.id) is None


def test_fcfs_queue_claims_the_oldest_stock_or_video_request(tmp_path):
    store = TelegramStore(str(tmp_path / "monitoring.sqlite3"))
    user = store.ensure_user(99, 99, "User", None)
    stock_job = store.create_analysis_job(user, "AAPL", "US")
    video_job = store.create_video_job(user, "https://youtu.be/abc123")

    with store._connect() as db:
        db.execute("UPDATE telegram_analysis_jobs SET created_at = ? WHERE id = ?", ("2026-01-01T00:00:00+00:00", stock_job.id))
        db.execute("UPDATE telegram_video_analysis_jobs SET created_at = ? WHERE id = ?", ("2026-01-01T00:01:00+00:00", video_job.id))

    first = store.claim_next_fcfs_job()
    assert first is not None
    assert first[0] == "stock"
    assert first[1].id == stock_job.id

    # A second worker cannot bypass the active job and run this video in parallel.
    assert store.claim_next_fcfs_job() is None
    store.fail_job(stock_job.id, "test completion")

    second = store.claim_next_fcfs_job()
    assert second is not None
    assert second[0] == "video"
    assert second[1].id == video_job.id


def test_admin_can_reject_only_a_queued_job(tmp_path):
    store = TelegramStore(str(tmp_path / "monitoring.sqlite3"))
    user = store.ensure_user(99, 99, "User", None)
    queued_job = store.create_analysis_job(user, "AAPL", "US")
    running_job = store.create_video_job(user, "https://youtu.be/abc123")
    assert store.claim_video_job(running_job.id) is not None

    rejected = store.reject_queued_job("stock", queued_job.id)
    assert rejected is not None
    assert rejected.status == "rejected"
    assert store.reject_queued_job("video", running_job.id) is None


def test_admin_can_cancel_a_running_job_without_touching_queued_work(tmp_path):
    store = TelegramStore(str(tmp_path / "monitoring.sqlite3"))
    user = store.ensure_user(99, 99, "User", None)
    running_job = store.create_analysis_job(user, "AAPL", "US")
    queued_job = store.create_video_job(user, "https://youtu.be/abc123")
    assert store.claim_job(running_job.id) is not None

    cancelled = store.cancel_running_job("stock", running_job.id)
    assert cancelled is not None
    assert cancelled.status == "rejected"
    assert cancelled.progress_text == "Cancelled by SAIP admin"
    assert store.cancel_running_job("video", queued_job.id) is None


def test_restarting_running_work_force_stops_then_restarts_the_worker(tmp_path, monkeypatch):
    manager = TelegramWorkerManager(tmp_path / "worker.json", tmp_path / "worker.log")
    monkeypatch.setattr(manager, "status", lambda: WorkerStatus(True, 4321, "Running"))
    calls = []

    def stop(*, force):
        calls.append(("stop", force))
        return WorkerStatus(False, None, "Stopped")

    def start():
        calls.append(("start", None))
        return WorkerStatus(True, 9876, "Running")

    monkeypatch.setattr(manager, "_stop", stop)
    monkeypatch.setattr(manager, "start", start)

    assert manager.restart_active_worker() == WorkerStatus(True, 9876, "Running")
    assert calls == [("stop", True), ("start", None)]


def test_report_financial_metrics_are_human_readable_and_never_model_metadata():
    rows = dict(_financial_metric_rows({
        "exchange": "US",
        "key_metrics": {
            "current_price": 210.5,
            "analyst_target": 240,
            "target_upside_pct": 14.0,
            "market_cap": 3_000_000_000_000,
            "pe_ratio": 30.1,
            "pb_ratio": 45.2,
            "ev_ebitda": 22.1,
            "free_cash_flow": 100_000_000_000,
            "fcf_margin": 0.25,
            "fcf_yield_pct": 3.3,
            "roe": 1.5,
            "debt_equity": 1.1,
            "interest_coverage": 15,
        },
    }))
    assert rows["Current price"] == "$210.50"
    assert rows["Market cap"] == "$3.00T"
    assert rows["FCF margin"] == "25.0%"


def test_worker_status_only_accepts_a_verified_saip_process(tmp_path, monkeypatch):
    manager = TelegramWorkerManager(tmp_path / "worker.json", tmp_path / "worker.log")
    manager._write_state(4321)
    monkeypatch.setattr(manager, "_is_saip_worker", lambda pid: pid == 4321)
    assert manager.status().running

    monkeypatch.setattr(manager, "_is_saip_worker", lambda pid: False)
    assert not manager.status().running
    assert not (tmp_path / "worker.json").exists()
