import yfinance as yf
import logging

logger = logging.getLogger(__name__)

class StockFetcher:
    def fetch(self, ticker: str, exchange: str) -> dict:
        symbol = ticker if exchange == "US" else (
            ticker if ticker.endswith(".NS") else f"{ticker}.NS"
        )
        logger.info(f"Fetching stock data for {symbol}")

        try:
            stock = yf.Ticker(symbol)
            info = stock.info or {}

            return {
                "ticker": ticker,
                "exchange": exchange,
                "company_name": info.get("longName", ticker),
                "sector": info.get("sector", "Unknown"),
                "industry": info.get("industry", "Unknown"),
                "balance_sheet": self._safe_to_dict(stock.balance_sheet),
                "income_statement": self._safe_to_dict(stock.financials),
                "cash_flow": self._safe_to_dict(stock.cashflow),
                "key_ratios": self._extract_ratios(info),
                "valuation_metrics": self._extract_valuation(info),
                "promoter_holding": self._extract_holders(stock, "promoter"),
                "fii_holding": self._extract_holders(stock, "institutional"),
                "dii_holding": [],
                "insider_transactions": self._safe_records(stock.insider_transactions),
                "peers": self._fetch_peers(stock),
                "market_position": {},
                "governance_flags": [],
                "debt_schedule": {},
                "analyst_ratings": self._extract_analyst(stock),
                "earnings_surprises": self._extract_earnings_surprises(stock),
            }
        except Exception as e:
            logger.error(f"Error fetching {symbol}: {e}")
            return self._empty_result(ticker, exchange)

    def _safe_to_dict(self, df):
        if df is None or df.empty:
            return {}
        try:
            return df.to_dict()
        except Exception:
            return {}

    def _safe_records(self, df):
        if df is None or df.empty:
            return []
        try:
            return df.to_dict("records")
        except Exception:
            return []

    def _extract_ratios(self, info: dict) -> dict:
        total_debt = info.get("totalDebt", 0) or 1
        ebitda = info.get("ebitda", 0) or 1
        total_revenue = info.get("totalRevenue", 0) or 1
        fcf = info.get("freeCashflow", 0) or 0

        interest_coverage = 999
        if total_debt > 0 and ebitda > 0:
            interest_coverage = round(ebitda / max(total_debt * 0.05, 1), 2)

        fcf_margin = round(fcf / total_revenue, 4) if total_revenue > 0 else 0

        return {
            "roe": info.get("returnOnEquity"),
            "roa": info.get("returnOnAssets"),
            "debt_equity": info.get("debtToEquity"),
            "current_ratio": info.get("currentRatio"),
            "interest_coverage": interest_coverage,
            "fcf_margin": fcf_margin,
            "related_party_pct": None,
        }

    def _extract_valuation(self, info: dict) -> dict:
        return {
            "pe_ratio": info.get("trailingPE"),
            "pb_ratio": info.get("priceToBook"),
            "ev_ebitda": info.get("enterpriseToEbitda"),
            "peg_ratio": info.get("pegRatio"),
            "market_cap": info.get("marketCap"),
            "current_price": info.get("currentPrice"),
        }

    def _extract_analyst(self, stock) -> dict:
        try:
            rec = stock.recommendations
            if rec is None or rec.empty:
                return {}
            latest = rec.tail(10).to_dict("records")
            return {
                "recent_recommendations": latest,
                "price_target": stock.info.get("targetMeanPrice")
            }
        except Exception:
            return {}

    def _extract_earnings_surprises(self, stock) -> list:
        try:
            earnings = stock.earnings_history
            if earnings is None or earnings.empty:
                return []
            return earnings.tail(4).to_dict("records")
        except Exception:
            return []

    def _extract_holders(self, stock, holder_type: str) -> list:
        try:
            if holder_type == "institutional":
                h = stock.institutional_holders
            else:
                h = stock.major_holders
            if h is None or h.empty:
                return []
            return h.to_dict("records")
        except Exception:
            return []

    def _fetch_peers(self, stock) -> list:
        return []

    def _empty_result(self, ticker, exchange):
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
