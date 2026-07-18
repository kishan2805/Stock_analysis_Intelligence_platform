from __future__ import annotations

from datetime import date
from typing import Literal
from pydantic import BaseModel, Field


class VideoMeta(BaseModel):
    video_id: str
    channel_name: str
    channel_url: str
    title: str
    publish_date: date
    url: str
    duration_seconds: int = 0


class Transcript(BaseModel):
    video_id: str
    text_en: str
    source: Literal["captions", "whisper"]
    original_language: str | None = None


class StockCall(BaseModel):
    video_id: str
    channel_name: str
    publish_date: date
    company_name_raw: str
    ticker: str | None = None
    exchange: Literal["NSE", "BSE"] | None = None
    action: Literal["BUY", "SELL", "HOLD", "WATCH", "AVOID"]
    entry_price: float | None = None
    target_price: float | None = None
    stop_loss: float | None = None
    time_horizon: str | None = None
    rationale_snippet: str | None = None
    sector_mentioned: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)
    evidence_timestamp_seconds: int | None = None
    evidence_text: str | None = None


class AggregatedStock(BaseModel):
    ticker: str
    exchange: str = "NSE"
    company_name: str
    calls: list[StockCall]
    mention_count: int
    channels: list[str]
    consensus_action: str
    tp_range: tuple[float, float] | None = None
    sl_range: tuple[float, float] | None = None
    sector: str | None = None


class RankedStockReport(BaseModel):
    ticker: str
    company_name: str
    conviction_score: float
    rank: int
    suggested_buy_price: float | None = None
    target_price: float | None = None
    stop_loss: float | None = None
    buy_side_view: str
    sell_side_view: str
    source_channels: list[str]
    mention_count: int
    hfip_rating: float | None = None
    hfip_model: str | None = None
    data_quality: Literal["Complete", "Degraded"] = "Degraded"
    data_quality_notes: list[str] = Field(default_factory=list)
    sector: str | None = None
    channel_price_note: str | None = None
