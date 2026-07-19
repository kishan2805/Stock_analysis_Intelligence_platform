from __future__ import annotations
import re
from functools import lru_cache
from rapidfuzz.fuzz import ratio
from .schemas import StockCall

COMMON = {
    "reliance": "RELIANCE.NS", "tcs": "TCS.NS", "tata consultancy services": "TCS.NS",
    "infosys": "INFY.NS", "hdfc bank": "HDFCBANK.NS", "icici bank": "ICICIBANK.NS",
    "tata motors": "TATAMOTORS.NS", "sbi": "SBIN.NS", "state bank of india": "SBIN.NS",
    "larsen and toubro": "LT.NS", "lt": "LT.NS", "shyam metallics": "SHYAMMETL.NS",
    "divis laboratories": "DIVISLAB.NS", "divis labs": "DIVISLAB.NS",
    "jsw infra": "JSWINFRA.NS", "jsw infrastructure": "JSWINFRA.NS",
}


LEGAL_SUFFIXES = {"limited", "ltd", "inc", "incorporated", "corp", "corporation", "plc", "company", "co"}


def _normalise(value: str) -> str:
    tokens = re.sub(r"[^a-z0-9 ]", " ", value.lower()).split()
    return " ".join(token for token in tokens if token not in LEGAL_SUFFIXES)


def _symbol(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper().removesuffix("NS"))


def _match_score(company_name: str, quote: dict) -> float:
    """Return a strict name-match score for a single NSE search candidate."""
    wanted = _normalise(company_name)
    wanted_tokens = set(wanted.split())
    symbol = _symbol(quote.get("symbol", ""))
    if _symbol(company_name) == symbol and len(symbol) >= 2:
        return 100.0
    if len(wanted_tokens) < 2:
        # A one-word name such as "Tata" is not enough to choose a company.
        return 0.0
    names = [quote.get("shortname", ""), quote.get("longname", ""), quote.get("displayName", "")]
    scores = []
    for name in names:
        candidate = _normalise(name)
        if not candidate:
            continue
        candidate_tokens = set(candidate.split())
        if wanted == candidate:
            scores.append(100.0)
        elif wanted_tokens <= candidate_tokens:
            # "Tata Consumer" is a safe prefix/subset of "Tata Consumer Products".
            scores.append(96.0)
        else:
            scores.append(float(ratio(wanted, candidate)))
    return max(scores, default=0.0)


def _choose_nse_candidate(company_name: str, quotes: list[dict]) -> str | None:
    """Choose only a high-confidence, clearly better NSE candidate."""
    scored = []
    for quote in quotes:
        symbol = str(quote.get("symbol", ""))
        exchange = str(quote.get("exchange", "")).upper()
        if not (symbol.endswith(".NS") or exchange in {"NSI", "NSE"}):
            continue
        score = _match_score(company_name, quote)
        if score:
            scored.append((score, symbol if symbol.endswith(".NS") else f"{symbol}.NS"))
    scored.sort(reverse=True)
    if not scored or scored[0][0] < 92:
        return None
    # Do not guess when two different listed companies are materially tied.
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 5:
        return None
    return scored[0][1]


@lru_cache(maxsize=512)
def _search_nse(company_name: str) -> str | None:
    """Resolve only a high-confidence, unambiguous NSE result."""
    try:
        import yfinance as yf
        quotes = yf.Search(company_name, max_results=8).quotes
    except Exception:
        return None
    return _choose_nse_candidate(company_name, quotes)


def resolve(call: StockCall) -> StockCall:
    normalized = _normalise(call.company_name_raw)
    ticker = COMMON.get(normalized) or _search_nse(call.company_name_raw)
    if ticker:
        call.ticker, call.exchange = ticker, "NSE"
    return call
