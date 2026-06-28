import math
import logging
import yfinance as yf

logger = logging.getLogger(__name__)

# Hard-coded peer map for common tickers (yfinance doesn't expose peers)
PEER_MAP = {
    "AAPL":       ["MSFT", "GOOGL", "META"],
    "MSFT":       ["AAPL", "GOOGL", "AMZN"],
    "GOOGL":      ["META", "MSFT", "AMZN"],
    "TSLA":       ["F", "GM", "NIO"],
    "NVDA":       ["AMD", "INTC", "QCOM"],
    "RELIANCE":   ["TCS.NS", "HDFCBANK.NS", "INFY.NS"],
    "TCS":        ["INFY.NS", "WIPRO.NS", "HCLTECH.NS"],
    "HDFCBANK":   ["ICICIBANK.NS", "KOTAKBANK.NS", "AXISBANK.NS"],
    "INFY":       ["TCS.NS", "WIPRO.NS", "HCLTECH.NS"],
    "WIPRO":      ["TCS.NS", "INFY.NS", "HCLTECH.NS"],
}


def _clean_value(v):
    """Convert NaN/Inf floats to None so JSON stays valid."""
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    return v


def _clean_dict(d: dict) -> dict:
    """Recursively sanitise a dict: NaN→None, Timestamp keys→str."""
    if not isinstance(d, dict):
        return d
    out = {}
    for k, v in d.items():
        str_key = str(k)
        if isinstance(v, dict):
            out[str_key] = _clean_dict(v)
        elif isinstance(v, list):
            out[str_key] = [_clean_dict(i) if isinstance(i, dict) else _clean_value(i) for i in v]
        else:
            out[str_key] = _clean_value(v)
    return out


def _drop_sparse_years(financial_dict: dict, min_fill_ratio: float = 0.3) -> dict:
    """
    Drop years (columns) where fewer than min_fill_ratio of values are non-None.
    Prevents the 2021 all-NaN row from polluting agent prompts.
    """
    cleaned = {}
    for year_key, row in financial_dict.items():
        if not isinstance(row, dict):
            cleaned[year_key] = row
            continue
        values = list(row.values())
        non_null = sum(1 for v in values if v is not None)
        if values and (non_null / len(values)) >= min_fill_ratio:
            cleaned[year_key] = row
    return cleaned


class StockFetcher:
    def fetch(self, ticker: str, exchange: str) -> dict:
        symbol = (
            ticker if exchange == "US"
            else (ticker if ticker.endswith(".NS") else f"{ticker}.NS")
        )
        logger.info(f"Fetching stock data for {symbol}")

        try:
            stock = yf.Ticker(symbol)
            info = stock.info or {}

            balance_sheet   = _drop_sparse_years(_clean_dict(self._safe_to_dict(stock.balance_sheet)))
            income_stmt     = _drop_sparse_years(_clean_dict(self._safe_to_dict(stock.financials)))
            cash_flow       = _drop_sparse_years(_clean_dict(self._safe_to_dict(stock.cashflow)))

            return {
                "ticker":               ticker,
                "exchange":             exchange,
                "company_name":         info.get("longName", ticker),
                "sector":               info.get("sector", "Unknown"),
                "industry":             info.get("industry", "Unknown"),
                "balance_sheet":        balance_sheet,
                "income_statement":     income_stmt,
                "cash_flow":            cash_flow,
                "key_ratios":           self._extract_ratios(info),
                "valuation_metrics":    self._extract_valuation(info),
                "promoter_holding":     self._extract_promoter(stock, exchange),
                "fii_holding":          self._extract_institutional(stock),
                "dii_holding":          [],
                "insider_transactions": self._safe_records(stock.insider_transactions),
                "peers":                self._fetch_peers(ticker, stock),
                "market_position":      {},
                "governance_flags":     [],
                "debt_schedule":        {},
                "analyst_ratings":      self._extract_analyst(stock, info),
                "earnings_surprises":   self._extract_earnings_surprises(stock),
            }
        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")
            return self._empty_result(ticker, exchange)

    # ── helpers ───────────────────────────────────────────────────────────

    def _safe_to_dict(self, df) -> dict:
        if df is None or df.empty:
            return {}
        try:
            return df.to_dict()
        except Exception:
            return {}

    def _safe_records(self, df) -> list:
        if df is None or df.empty:
            return []
        try:
            records = df.to_dict("records")
            return [_clean_dict(r) for r in records]
        except Exception:
            return []

    def _extract_ratios(self, info: dict) -> dict:
        total_revenue = info.get("totalRevenue") or 1
        fcf           = info.get("freeCashflow") or 0
        ebitda        = info.get("ebitda") or 0
        total_debt    = info.get("totalDebt") or 0

        # Interest coverage: EBITDA / (total_debt * assumed 5% rate)
        # Falls back to info field if available
        interest_coverage = info.get("interestCoverage")
        if interest_coverage is None:
            interest_coverage = (
                round(ebitda / max(total_debt * 0.05, 1), 2)
                if ebitda > 0 and total_debt > 0
                else 999.0
            )

        return {
            "roe":                _clean_value(info.get("returnOnEquity")),
            "roa":                _clean_value(info.get("returnOnAssets")),
            "debt_equity":        _clean_value(info.get("debtToEquity")),
            "current_ratio":      _clean_value(info.get("currentRatio")),
            "interest_coverage":  _clean_value(interest_coverage),
            "fcf_margin":         _clean_value(round(fcf / total_revenue, 4) if total_revenue else 0),
            "related_party_pct":  None,
        }

    def _extract_valuation(self, info: dict) -> dict:
        return {
            "pe_ratio":      _clean_value(info.get("trailingPE")),
            "pb_ratio":      _clean_value(info.get("priceToBook")),
            "ev_ebitda":     _clean_value(info.get("enterpriseToEbitda")),
            "peg_ratio":     _clean_value(info.get("pegRatio")),
            "market_cap":    _clean_value(info.get("marketCap")),
            "current_price": _clean_value(info.get("currentPrice")),
        }

    def _extract_promoter(self, stock, exchange: str) -> list:
        """
        For Indian stocks: major_holders row 0 = insider %, used as proxy for promoter %.
        For US stocks: returns institutional summary instead; marks it clearly.
        No pledge data is available from yfinance — always None.
        """
        try:
            mh = stock.major_holders
            if mh is None or mh.empty:
                return []

            rows = mh.to_dict("records")

            if exchange == "IN":
                # yfinance major_holders for .NS has [insider%, institution%, float%, total]
                if rows:
                    first_val = list(rows[0].values())[0] if rows[0] else 0
                    return [{
                        "type":                 "promoter_proxy",
                        "insider_pct":          _clean_value(first_val),
                        "pledge_pct":           None,   # not available from yfinance
                        "note":                 "Pledge % not available via yfinance; check BSE/NSE filings"
                    }]
            else:
                # US stock — return institutional summary
                return [{
                    "type":       "major_holders_us",
                    "pledge_pct": None,
                    "rows":       [_clean_dict(r) for r in rows]
                }]
        except Exception as e:
            logger.warning(f"Promoter/holder fetch failed: {e}")
        return []

    def _extract_institutional(self, stock) -> list:
        try:
            ih = stock.institutional_holders
            if ih is None or ih.empty:
                return []
            records = ih.head(10).to_dict("records")
            return [_clean_dict(r) for r in records]
        except Exception:
            return []

    def _extract_analyst(self, stock, info: dict) -> dict:
        try:
            rec = stock.recommendations
            if rec is None or rec.empty:
                return {"price_target": _clean_value(info.get("targetMeanPrice"))}
            latest = rec.tail(10).to_dict("records")
            return {
                "recent_recommendations": [_clean_dict(r) for r in latest],
                "price_target":           _clean_value(info.get("targetMeanPrice")),
            }
        except Exception:
            return {}

    def _extract_earnings_surprises(self, stock) -> list:
        try:
            eh = stock.earnings_history
            if eh is None or eh.empty:
                return []
            records = eh.tail(4).to_dict("records")
            return [_clean_dict(r) for r in records]
        except Exception:
            return []

    def _fetch_peers(self, ticker: str, stock) -> list:
        """
        Look up hard-coded peer map first.
        For each peer, fetch a minimal ratio summary so agents can compare.
        """
        base = ticker.replace(".NS", "").upper()
        peer_tickers = PEER_MAP.get(base, [])
        if not peer_tickers:
            return []

        peers = []
        for pt in peer_tickers:
            try:
                p = yf.Ticker(pt)
                pi = p.info or {}
                peers.append({
                    "ticker":     pt,
                    "name":       pi.get("longName", pt),
                    "pe_ratio":   _clean_value(pi.get("trailingPE")),
                    "pb_ratio":   _clean_value(pi.get("priceToBook")),
                    "market_cap": _clean_value(pi.get("marketCap")),
                    "roe":        _clean_value(pi.get("returnOnEquity")),
                    "debt_equity":_clean_value(pi.get("debtToEquity")),
                })
            except Exception as e:
                logger.warning(f"Peer fetch failed for {pt}: {e}")
        return peers

    def _empty_result(self, ticker, exchange) -> dict:
        return {
            "ticker": ticker, "exchange": exchange,
            "company_name": ticker, "sector": "Unknown", "industry": "Unknown",
            "balance_sheet": {}, "income_statement": {}, "cash_flow": {},
            "key_ratios": {}, "valuation_metrics": {},
            "promoter_holding": [], "fii_holding": [], "dii_holding": [],
            "insider_transactions": [], "peers": [], "market_position": {},
            "governance_flags": [], "debt_schedule": {},
            "analyst_ratings": {}, "earnings_surprises": [],
        }
