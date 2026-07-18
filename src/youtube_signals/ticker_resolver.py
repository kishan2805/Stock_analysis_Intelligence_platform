from __future__ import annotations
import re
from functools import lru_cache
from rapidfuzz.fuzz import token_set_ratio
from .schemas import StockCall

COMMON = {
    "reliance": "RELIANCE.NS", "tcs": "TCS.NS", "tata consultancy services": "TCS.NS",
    "infosys": "INFY.NS", "hdfc bank": "HDFCBANK.NS", "icici bank": "ICICIBANK.NS",
    "tata motors": "TATAMOTORS.NS", "sbi": "SBIN.NS", "state bank of india": "SBIN.NS",
    "larsen and toubro": "LT.NS", "lt": "LT.NS", "shyam metallics": "SHYAMMETL.NS",
    "divis laboratories": "DIVISLAB.NS", "divis labs": "DIVISLAB.NS",
    "jsw infra": "JSWINFRA.NS", "jsw infrastructure": "JSWINFRA.NS",
}


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", value.lower()).strip()


@lru_cache(maxsize=512)
def _search_nse(company_name: str) -> str | None:
    """Resolve only a high-confidence NSE result; ambiguity stays unresolved."""
    try:
        import yfinance as yf
        quotes = yf.Search(company_name, max_results=8).quotes
    except Exception:
        return None
    wanted = _normalise(company_name)
    best_score, best_symbol = 0.0, None
    for quote in quotes:
        symbol = quote.get("symbol", "")
        exchange = str(quote.get("exchange", "")).upper()
        if not (symbol.endswith(".NS") or exchange in {"NSI", "NSE"}):
            continue
        names = [quote.get("shortname", ""), quote.get("longname", ""), quote.get("displayName", "")]
        match = max((token_set_ratio(wanted, _normalise(name)) for name in names if name), default=0)
        if match > best_score:
            best_score, best_symbol = match, symbol if symbol.endswith(".NS") else f"{symbol}.NS"
    return best_symbol if best_score >= 85 else None


def resolve(call: StockCall) -> StockCall:
    normalized = _normalise(call.company_name_raw)
    ticker = COMMON.get(normalized) or _search_nse(call.company_name_raw)
    if ticker:
        call.ticker, call.exchange = ticker, "NSE"
    return call
