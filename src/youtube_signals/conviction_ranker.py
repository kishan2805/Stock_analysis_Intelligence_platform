from __future__ import annotations
from datetime import date
import math
from .schemas import AggregatedStock


def score(stock: AggregatedStock, channels_scanned: int, cio: dict | None) -> float:
    mention = min(1.0, len(stock.channels) / max(1, channels_scanned))
    rating = float((cio or {}).get("final_rating", 5.0)) / 10
    newest = max(c.publish_date for c in stock.calls)
    recency = math.exp(-((date.today() - newest).days) / 30)
    numeric_sets = [c.target_price for c in stock.calls if c.target_price]
    consensus = 1.0 if len(numeric_sets) < 2 else max(0.0, 1 - ((max(numeric_sets) - min(numeric_sets)) / max(numeric_sets)))
    return round(100 * (.30 * mention + .15 * consensus + .10 * recency + .35 * rating + .10 * .5), 1)


def diversify(rows: list[tuple[AggregatedStock, dict | None, float]], top_n: int, max_per_sector: int):
    selected, per_sector = [], {}
    for stock, cio, conviction in sorted(rows, key=lambda r: r[2], reverse=True):
        sector = stock.sector or "Unclassified"
        if per_sector.get(sector, 0) >= max_per_sector:
            continue
        per_sector[sector] = per_sector.get(sector, 0) + 1
        selected.append((stock, cio, conviction))
        if len(selected) == top_n:
            break
    return selected
