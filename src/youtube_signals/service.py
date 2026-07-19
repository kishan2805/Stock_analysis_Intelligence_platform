from __future__ import annotations
import asyncio
from .aggregator import aggregate
from .cache import SignalCache
from .channel_scanner import scan_url
from .conviction_ranker import conviction_score, diversify, ranking_score
from .extractor_agent import ExtractorAgent
from .groq_client import GroqClient
from .schemas import RankedStockReport
from .ticker_resolver import resolve
from .transcript_fetcher import TranscriptFetcher
from src.pipeline.orchestrator import PipelineOrchestrator


class YouTubeScannerService:
    def __init__(self, config, progress=None):
        self.config, self.progress = config, progress or (lambda _: None)
        cfg = config.youtube_signals
        self.cache = SignalCache()
        groq = GroqClient(cfg.api_key)
        self.transcripts = TranscriptFetcher(self.cache, groq, cfg.transcription.translation_model, cfg.transcription.caption_translation_model)
        self.extractor = ExtractorAgent(self.cache, groq, cfg.extraction.model, cfg.extraction.temperature)

    async def scan(
        self,
        urls: list[str],
        lookback_days: int,
        max_videos: int,
        top_n: int,
        skip_debate: bool | None = None,
    ) -> dict:
        """Scan videos and run deep-dives.

        ``skip_debate`` is a per-run user choice. Configuration is only the
        default; it must never override an explicit checkbox selection.
        """
        videos, errors = [], []
        for url in urls:
            found, skipped = await asyncio.to_thread(scan_url, url, lookback_days, max_videos, True)
            videos.extend(found); errors.extend(skipped)
        calls = []
        for index, video in enumerate(videos, 1):
            self.progress(f"Processing video {index}/{len(videos)}: {video.title}")
            try:
                transcript = await asyncio.to_thread(self.transcripts.fetch, video)
                self.progress(f"Extracting calls from {video.title} ({transcript.source})")
                calls.extend(await asyncio.to_thread(self.extractor.extract, video, transcript))
            except Exception as exc:
                errors.append(f"{video.title}: {exc}")
        stocks, unresolved = aggregate([resolve(call) for call in calls])
        candidates = sorted(stocks, key=lambda s: len(s.channels), reverse=True)[:self.config.youtube_signals.scan.max_deep_dives]
        sem = asyncio.Semaphore(self.config.youtube_signals.scan.deep_dive_concurrency)
        async def deep_dive(stock):
            async with sem:
                self.progress(f"Deep-diving {stock.ticker}")
                try:
                    settings = self.config.youtube_signals.deep_dive
                    run_skip_debate = settings.skip_debate if skip_debate is None else skip_debate
                    def run_pipeline():
                        return asyncio.run(PipelineOrchestrator(self.config).run(
                            stock.ticker, "IN", 18, settings.execution_mode,
                            skip_debate=run_skip_debate,
                        ))
                    result = await asyncio.wait_for(
                        asyncio.to_thread(run_pipeline), timeout=settings.timeout_seconds,
                    )
                    return stock.ticker, result
                except asyncio.TimeoutError:
                    errors.append(f"Deep-dive {stock.ticker}: timed out after {settings.timeout_seconds}s; neutral ranking score used")
                    return stock.ticker, None
                except Exception as exc:
                    errors.append(f"Deep-dive {stock.ticker}: {exc}")
                    return stock.ticker, None
        deep_results = dict(await asyncio.gather(*(deep_dive(s) for s in candidates)))
        verdicts = {ticker: result.get("cio") if result else None for ticker, result in deep_results.items()}
        channels_scanned = max(1, len({v.channel_url for v in videos}))
        rows = []
        for stock in candidates:
            cio = verdicts.get(stock.ticker)
            conviction = conviction_score(stock, channels_scanned)
            rows.append((stock, cio, conviction, ranking_score(conviction, cio)))
        # Keep a report for every stock that received a deep-dive.  ``top_n``
        # controls only the shortlist shown first in the UI; it must not
        # silently remove stocks from the downloadable result set.
        ranked_rows = sorted(rows, key=lambda row: row[3], reverse=True)
        selected = diversify(ranked_rows, top_n, self.config.youtube_signals.ranking.max_per_sector)
        reports_by_ticker = {}
        for rank, (stock, cio, conviction, final_score) in enumerate(ranked_rows, 1):
            entry = [c.entry_price for c in stock.calls if c.entry_price is not None]
            target = [c.target_price for c in stock.calls if c.target_price is not None]
            stop = [c.stop_loss for c in stock.calls if c.stop_loss is not None]
            deep_result = deep_results.get(stock.ticker) or {}
            model = (cio or {}).get("_model_used")
            quality_notes = list(deep_result.get("kg_metadata", {}).get("data_gaps", []))
            failed_agents = [
                name for name, report in (deep_result.get("agent_reports") or {}).items()
                if isinstance(report, dict) and report.get("error")
            ]
            quality_notes.extend(f"agent:{name}" for name in failed_agents)
            debate_error = (deep_result.get("debate") or {}).get("error")
            if debate_error:
                quality_notes.append("debate_failed")
            if not cio:
                quality_notes.append("SAIP deep-dive failed; neutral ranking score used")
            reports_by_ticker[stock.ticker] = RankedStockReport(ticker=stock.ticker, company_name=stock.company_name, conviction_score=conviction, ranking_score=final_score, rank=rank, suggested_buy_price=min(entry) if entry else None, target_price=sum(target)/len(target) if target else None, stop_loss=max(stop) if stop else None, buy_side_view="Channel-stated rationale: " + "; ".join(filter(None, [c.rationale_snippet for c in stock.calls[:3]])), sell_side_view=(cio or {}).get("thesis_invalidating_risk") or "No independent downside narrative was available; verify the underlying video evidence.", source_channels=stock.channels, mention_count=stock.mention_count, saip_rating=(cio or {}).get("final_rating"), saip_model=model, saip_execution_mode=self.config.youtube_signals.deep_dive.execution_mode, data_quality="Complete" if not quality_notes else "Degraded", data_quality_notes=quality_notes, sector=stock.sector, channel_price_note="Prices shown are only levels explicitly stated by channels; SAIP buy-below is a separate valuation guardrail.")
        all_reports = list(reports_by_ticker.values())
        shortlist_tickers = {stock.ticker for stock, *_ in selected}
        reports = [report for report in all_reports if report.ticker in shortlist_tickers]
        return {"reports": reports, "all_reports": all_reports, "stocks": stocks, "unresolved": unresolved, "errors": errors, "videos": videos}
