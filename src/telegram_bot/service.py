"""Background execution and delivery of private Telegram analysis jobs."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from src.pipeline.orchestrator import PipelineOrchestrator
from src.utils.config_loader import load_config
from src.utils.pdf_report import build_main_analysis_pdf, build_scanner_pdf
from src.youtube_signals.service import YouTubeScannerService

from .formatters import analysis_summary, report_filename, video_report_filename, video_scan_summary
from .store import AnalysisJob, TelegramStore, TelegramUser, VideoAnalysisJob

logger = logging.getLogger(__name__)


class TelegramFCFSQueue:
    """One global first-come-first-served executor for Telegram compute work."""

    def __init__(self, store: TelegramStore, stock_service, video_service):
        self.store = store
        self.stock_service = stock_service
        self.video_service = video_service
        self._task: asyncio.Task | None = None
        self._wake_requested = asyncio.Event()

    def start(self) -> None:
        """Wake the worker without starting a second concurrent queue runner."""
        self._wake_requested.set()
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._drain(), name="telegram-fcfs-analysis-queue")

    async def _drain(self) -> None:
        while True:
            self._wake_requested.clear()
            item = self.store.claim_next_fcfs_job()
            if item is None:
                # Let a request that arrived as this worker became idle wake it
                # instead of leaving a durable queued job waiting for a restart.
                await asyncio.sleep(0)
                if self._wake_requested.is_set():
                    continue
                return
            kind, job = item
            if kind == "stock":
                await self.stock_service.run_claimed_job(job)
            else:
                await self.video_service.run_claimed_job(job)


class TelegramAnalysisService:
    """Executes one stock job once it has been claimed by the FCFS dispatcher."""

    def __init__(self, bot, store: TelegramStore):
        self.bot = bot
        self.store = store

    def queue_analysis(self, user: TelegramUser, ticker: str, exchange: str) -> AnalysisJob:
        return self.store.create_analysis_job(user, ticker, exchange)

    async def run_claimed_job(self, job: AnalysisJob) -> None:
        try:
            self.store.update_stock_progress(job.id, "Building market intelligence and running SAIP agents")
            # The existing debate stage makes synchronous model calls.  Run the
            # complete pipeline in a worker thread so bot updates stay responsive.
            result = await asyncio.to_thread(
                lambda: asyncio.run(
                    PipelineOrchestrator(load_config()).run(
                        job.ticker, job.exchange, job.duration_months, job.depth, skip_debate=False
                    )
                )
            )
            pdf = await asyncio.to_thread(
                build_main_analysis_pdf,
                result,
                {
                    "ticker": job.ticker,
                    "exchange": job.exchange,
                    "duration": job.duration_months,
                    "depth": job.depth,
                    "skip_debate": False,
                },
            )
            self.store.update_stock_progress(job.id, "Preparing private PDF report")
            output_path = Path("output/telegram-reports") / job.id / report_filename(job.ticker)
            await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(output_path.write_bytes, pdf)
            self.store.complete_job(job.id, result, output_path)
            await self._send_report(job, result, output_path)
        except Exception as exc:
            logger.exception("Telegram analysis job %s failed", job.id)
            self.store.fail_job(job.id, str(exc))
            await self._safe_send(job.chat_id, "Analysis could not be completed. Use /analyze again later or verify the ticker.")

    async def send_latest_report(self, job: AnalysisJob) -> bool:
        result = job.result()
        path = Path(job.pdf_path) if job.pdf_path else None
        if not result or not path or not path.is_file():
            return False
        await self._send_report(job, result, path)
        return True

    async def _send_report(self, job: AnalysisJob, result: dict, pdf_path: Path) -> None:
        await self._safe_send(job.chat_id, analysis_summary(result))
        try:
            with pdf_path.open("rb") as report:
                await self.bot.send_document(
                    chat_id=job.chat_id,
                    document=report,
                    filename=report_filename(job.ticker),
                    caption="Full SAIP report — informational research only, not investment advice.",
                )
        except Exception:
            # A delivery failure must not discard a successfully generated private report.
            logger.exception("Unable to deliver Telegram report for job %s", job.id)

    async def _safe_send(self, chat_id: int, text: str) -> None:
        try:
            await self.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception("Unable to send Telegram message to chat %s", chat_id)


class TelegramVideoAnalysisService:
    """Executes one video job once it has been claimed by the FCFS dispatcher."""

    def __init__(self, bot, store: TelegramStore):
        self.bot = bot
        self.store = store

    def queue_video(self, user: TelegramUser, video_url: str) -> VideoAnalysisJob:
        return self.store.create_video_job(user, video_url)

    async def run_claimed_job(self, job: VideoAnalysisJob) -> None:
        try:
            config = load_config()
            top_n = config.youtube_signals.ranking.top_n_default
            self.store.update_video_progress(job.id, "Reading the video, extracting stock calls, and ranking candidates")
            # The scanner may invoke the synchronous debate stage. Keep it off
            # the bot event loop so new Telegram updates are still received.
            result = await asyncio.to_thread(
                lambda: asyncio.run(
                    YouTubeScannerService(config).scan(
                        [job.video_url], lookback_days=3650, max_videos=1, top_n=top_n, skip_debate=False
                    )
                )
            )
            self.store.update_video_progress(job.id, "Preparing ranked video-analysis PDF")
            pdf = await asyncio.to_thread(build_scanner_pdf, result, job.id)
            output_path = Path("output/telegram-video-reports") / job.id / video_report_filename()
            await asyncio.to_thread(output_path.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(output_path.write_bytes, pdf)
            self.store.complete_video_job(job.id, result, output_path)
            await self._send_report(job, result, output_path)
        except Exception as exc:
            logger.exception("Telegram YouTube video job %s failed", job.id)
            self.store.fail_video_job(job.id, str(exc))
            await self._safe_send(job.chat_id, "Video analysis could not be completed. Please verify that the video is public and try again.")

    async def _send_report(self, job: VideoAnalysisJob, result: dict, pdf_path: Path) -> None:
        await self._safe_send(job.chat_id, video_scan_summary(result))
        try:
            with pdf_path.open("rb") as report:
                await self.bot.send_document(
                    chat_id=job.chat_id,
                    document=report,
                    filename=video_report_filename(),
                    caption="YouTube video analysis — informational research only, not investment advice.",
                )
        except Exception:
            logger.exception("Unable to deliver Telegram YouTube report for job %s", job.id)

    async def _safe_send(self, chat_id: int, text: str) -> None:
        try:
            await self.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception("Unable to send Telegram message to chat %s", chat_id)
