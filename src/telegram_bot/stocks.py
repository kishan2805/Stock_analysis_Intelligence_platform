"""Conservative parsing for stock requests received from Telegram."""
from __future__ import annotations

from dataclasses import dataclass
import re

from src.youtube_signals.ticker_resolver import COMMON


@dataclass(frozen=True)
class StockRequest:
    ticker: str
    exchange: str


_TICKER = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")
_NSE_TICKER = re.compile(r"^[A-Z][A-Z0-9\-]{0,14}\.NS$")
_NSE_SYMBOL = re.compile(r"^[A-Z][A-Z0-9\-]{0,14}$")

# A human-friendly name can also have a listing in more than one market. Keep
# verified collisions explicit so the Telegram bot never silently routes the
# request to the wrong market. Add new verified collisions here as discovered.
AMBIGUOUS_STOCK_OPTIONS: dict[str, tuple[StockRequest, ...]] = {
    "infosys": (
        StockRequest("INFY.NS", "IN"),
        StockRequest("INFY", "US"),
    ),
    "infy": (
        StockRequest("INFY.NS", "IN"),
        StockRequest("INFY", "US"),
    ),
}

INDIAN_NAME_TICKERS = {
    "cupid": "CUPID.NS",
    "cupid limited": "CUPID.NS",
    "cupid ltd": "CUPID.NS",
}


def resolve_stock_options(value: str) -> tuple[StockRequest, ...]:
    """Return every safe market choice for a ticker or recognised stock name.

    An empty tuple means the value cannot be safely identified. More than one
    option must be shown to the Telegram user before any job is queued.
    """
    cleaned = " ".join(value.strip().split())
    if not cleaned:
        return ()
    ambiguous = AMBIGUOUS_STOCK_OPTIONS.get(cleaned.lower())
    if ambiguous:
        return ambiguous
    known = INDIAN_NAME_TICKERS.get(cleaned.lower()) or COMMON.get(cleaned.lower())
    if known:
        return (StockRequest(known, "IN"),)
    candidate = cleaned.upper()
    if _NSE_TICKER.fullmatch(candidate):
        return (StockRequest(candidate, "IN"),)
    # Uppercase is treated as a deliberate US ticker. A title-cased or
    # lowercase one-word company name must be resolved explicitly rather than
    # becoming a potentially unrelated US symbol.
    if cleaned == candidate and _TICKER.fullmatch(candidate) and "." not in candidate:
        return (StockRequest(candidate, "US"),)
    return ()


def resolve_stock_request(value: str) -> StockRequest | None:
    """Return the request only if its market is unambiguous."""
    options = resolve_stock_options(value)
    return options[0] if len(options) == 1 else None


def resolve_ticker_for_exchange(value: str, exchange: str) -> StockRequest | None:
    """Normalise a user-entered ticker after they explicitly select a market."""
    candidate = "".join(value.strip().upper().split())
    if exchange == "IN":
        symbol = candidate.removesuffix(".NS")
        return StockRequest(f"{symbol}.NS", "IN") if _NSE_SYMBOL.fullmatch(symbol) else None
    if exchange == "US" and _TICKER.fullmatch(candidate) and not candidate.endswith(".NS"):
        return StockRequest(candidate, "US")
    return None
