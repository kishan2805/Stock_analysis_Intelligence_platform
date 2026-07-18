from __future__ import annotations
import asyncio
from .aggregator import aggregate
from .cache import SignalCache
from .channel_scanner import scan_url
from .conviction_ranker import diversify, score
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

    async def scan(self, urls: list[str], lookback_days: int, max_videos: int, top_n: int) -> dict:
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
                    return stock.ticker, await PipelineOrchestrator(self.config).run(stock.ticker, "IN", 18, "quick", skip_debate=True)
                except Exception as exc:
                    errors.append(f"Deep-dive {stock.ticker}: {exc}")
                    return stock.ticker, None
        deep_results = dict(await asyncio.gather(*(deep_dive(s) for s in candidates)))
        verdicts = {ticker: result.get("cio") if result else None for ticker, result in deep_results.items()}
        rows = [(stock, verdicts.get(stock.ticker), score(stock, max(1, len({v.channel_url for v in videos})), verdicts.get(stock.ticker))) for stock in candidates]
        selected = diversify(rows, top_n, self.config.youtube_signals.ranking.max_per_sector)
        reports = []
        for rank, (stock, cio, conviction) in enumerate(selected, 1):
            entry = [c.entry_price for c in stock.calls if c.entry_price is not None]
            target = [c.target_price for c in stock.calls if c.target_price is not None]
            stop = [c.stop_loss for c in stock.calls if c.stop_loss is not None]
            deep_result = deep_results.get(stock.ticker) or {}
            model = (cio or {}).get("_model_used")
            quality_notes = list(deep_result.get("kg_metadata", {}).get("data_gaps", []))
            if not cio:
                quality_notes.append("HFIP deep-dive failed; neutral ranking score used")
            if model and model.startswith("gemma3:4b"):
                quality_notes.append("Gemma 3 4B context limit excluded raw financial statements")
            reports.append(RankedStockReport(ticker=stock.ticker, company_name=stock.company_name, conviction_score=conviction, rank=rank, suggested_buy_price=min(entry) if entry else None, target_price=sum(target)/len(target) if target else None, stop_loss=max(stop) if stop else None, buy_side_view="Channel-stated rationale: " + "; ".join(filter(None, [c.rationale_snippet for c in stock.calls[:3]])), sell_side_view=(cio or {}).get("thesis_invalidating_risk") or "No independent downside narrative was available; verify the underlying video evidence.", source_channels=stock.channels, mention_count=stock.mention_count, hfip_rating=(cio or {}).get("final_rating"), hfip_model=model, data_quality="Complete" if not quality_notes else "Degraded", data_quality_notes=quality_notes, sector=stock.sector, channel_price_note="Prices shown are only levels explicitly stated by channels; HFIP buy-below is a separate valuation guardrail."))
        return {"reports": reports, "stocks": stocks, "unresolved": unresolved, "errors": errors, "videos": videos}
