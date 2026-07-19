from __future__ import annotations
from datetime import date
import math
from .schemas import AggregatedStock


def conviction_score(stock: AggregatedStock, channels_scanned: int) -> float:
    """Score the strength of the video evidence, independent of HFIP analysis."""
    mention = min(1.0, len(stock.channels) / max(1, channels_scanned))
    newest = max(c.publish_date for c in stock.calls)
    recency = math.exp(-((date.today() - newest).days) / 30)
    numeric_sets = [c.target_price for c in stock.calls if c.target_price]
    consensus = 1.0 if len(numeric_sets) < 2 else max(0.0, 1 - ((max(numeric_sets) - min(numeric_sets)) / max(numeric_sets)))
    return round(100 * (.50 * mention + .30 * consensus + .20 * recency), 1)


def ranking_score(conviction: float, cio: dict | None) -> float:
    """Blend channel evidence (60%) with the independent HFIP rating (40%)."""
    hfip_score = float((cio or {}).get("final_rating", 5.0)) * 10
    return round(.60 * conviction + .40 * hfip_score, 1)


def score(stock: AggregatedStock, channels_scanned: int, cio: dict | None) -> float:
    """Backward-compatible final ranking score."""
    return ranking_score(conviction_score(stock, channels_scanned), cio)


def diversify(rows: list[tuple], top_n: int, max_per_sector: int):
    selected, per_sector = [], {}
    for row in sorted(rows, key=lambda r: r[-1], reverse=True):
        stock = row[0]
        sector = stock.sector or "Unclassified"
        if per_sector.get(sector, 0) >= max_per_sector:
            continue
        per_sector[sector] = per_sector.get(sector, 0) + 1
        selected.append(row)
        if len(selected) == top_n:
            break
    return selected
