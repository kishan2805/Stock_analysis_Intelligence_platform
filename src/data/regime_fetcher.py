import yfinance as yf
import feedparser
import logging

logger = logging.getLogger(__name__)

class RegimeFetcher:
    GEOPOLITICAL_KEYWORDS = [
        "war", "sanctions", "tariff", "OPEC", "trade war",
        "chip shortage", "Taiwan", "crude oil", "FII outflow",
        "RBI rate", "Fed rate", "inflation"
    ]

    def fetch(self) -> dict:
        logger.info("Fetching regime data")
        return {
            "regime_data": self._fetch_market_indicators(),
            "fii_flow_30d": None,
            "geopolitical_headlines": self._fetch_geo_news(),
            "macro_indicators": self._fetch_macro(),
        }

    def _fetch_market_indicators(self) -> dict:
        tickers = {
            "vix_us": "^VIX",
            "vix_india": "^NIFVIX",
            "crude_brent": "BZ=F",
            "dxy": "DX-Y.NYB",
            "usdinr": "USDINR=X",
            "nifty": "^NSEI",
        }
        data = {}
        for key, symbol in tickers.items():
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(period="5d")
                if not hist.empty:
                    data[key] = {
                        "current": round(hist["Close"].iloc[-1], 2),
                        "5d_change_pct": round(
                            (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100, 2
                        )
                    }
            except Exception as e:
                logger.warning(f"Failed to fetch {symbol}: {e}")
                data[key] = None
        return data

    def _fetch_geo_news(self) -> list:
        try:
            query = "geopolitical+war+sanctions+trade+war+oil+supply"
            url = f"https://news.google.com/rss/search?q={query}&hl=en&gl=US&ceid=US:en"
            feed = feedparser.parse(url)
            articles = []
            for entry in feed.entries[:15]:
                title = entry.get("title", "")
                matched = [kw for kw in self.GEOPOLITICAL_KEYWORDS
                           if kw.lower() in title.lower()]
                if matched:
                    articles.append({
                        "title": title,
                        "published": entry.get("published", ""),
                        "keywords_matched": matched,
                    })
            return articles
        except Exception as e:
            logger.error(f"Geo news fetch error: {e}")
            return []

    def _fetch_macro(self) -> dict:
        try:
            rbi_feed = feedparser.parse(
                "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=rss"
            )
            rbi_headlines = [e.get("title", "") for e in rbi_feed.entries[:5]]
            return {"rbi_recent_releases": rbi_headlines}
        except Exception:
            return {"rbi_recent_releases": []}
