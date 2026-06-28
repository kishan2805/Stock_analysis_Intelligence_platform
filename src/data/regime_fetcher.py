import logging
import urllib.request
import urllib.parse
import yfinance as yf
import feedparser

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _parse_feed_with_ua(url: str) -> list:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read()
        return feedparser.parse(content).entries
    except Exception as e:
        logger.warning(f"Regime feed failed ({url[:80]}): {e}")
        return []


class RegimeFetcher:
    GEOPOLITICAL_KEYWORDS = [
        "war", "conflict", "sanctions", "tariff", "trade war", "OPEC",
        "chip shortage", "Taiwan", "crude oil", "FII outflow", "RBI rate",
        "Fed rate", "inflation", "recession", "geopolit", "embargo",
        "missile", "ceasefire", "naval", "energy crisis", "supply chain",
        "export controls", "Middle East", "Ukraine", "China Taiwan",
    ]

    def fetch(self) -> dict:
        logger.info("Fetching regime data")
        return {
            "regime_data":            self._fetch_market_indicators(),
            "fii_flow_30d":           None,
            "geopolitical_headlines": self._fetch_geo_news(),
            "macro_indicators":       self._fetch_macro(),
        }

    # ── market indicators ─────────────────────────────────────────────────

    def _fetch_market_indicators(self) -> dict:
        symbols = {
            "vix_us":      "^VIX",
            "vix_india":   "^NIFVIX",
            "crude_brent": "BZ=F",
            "dxy":         "DX-Y.NYB",
            "usdinr":      "USDINR=X",
            "nifty":       "^NSEI",
            "sp500":       "^GSPC",
        }
        data = {}
        for key, symbol in symbols.items():
            try:
                t = yf.Ticker(symbol)
                hist = t.history(period="5d")
                if not hist.empty and len(hist) >= 2:
                    first = hist["Close"].iloc[0]
                    last  = hist["Close"].iloc[-1]
                    data[key] = {
                        "current":        round(last, 2),
                        "5d_change_pct":  round((last / first - 1) * 100, 2) if first else None,
                    }
                else:
                    data[key] = None
            except Exception as e:
                logger.warning(f"Indicator fetch failed for {symbol}: {e}")
                data[key] = None
        return data

    # ── geopolitical news ─────────────────────────────────────────────────

    def _fetch_geo_news(self) -> list:
        queries = [
            "geopolitical conflict war sanctions oil supply 2025",
            "trade war tariff chip export controls Taiwan",
            "Fed interest rate inflation recession outlook",
        ]
        articles = []
        seen = set()
        for query in queries:
            q = urllib.parse.quote_plus(query)
            url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
            for entry in _parse_feed_with_ua(url)[:10]:
                title = entry.get("title", "").strip()
                if not title or title in seen:
                    continue
                matched = [kw for kw in self.GEOPOLITICAL_KEYWORDS
                           if kw.lower() in title.lower()]
                if matched:
                    seen.add(title)
                    articles.append({
                        "title":            title,
                        "published":        entry.get("published", ""),
                        "keywords_matched": matched,
                    })
            if len(articles) >= 20:
                break
        return articles[:20]

    # ── macro indicators ──────────────────────────────────────────────────

    def _fetch_macro(self) -> dict:
        result = {
            "rbi_recent_releases": [],
            "fed_recent_releases":  [],
        }

        # RBI press releases
        try:
            rbi_url = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=rss"
            entries = _parse_feed_with_ua(rbi_url)
            result["rbi_recent_releases"] = [e.get("title", "") for e in entries[:5] if e.get("title")]
        except Exception as e:
            logger.warning(f"RBI RSS failed: {e}")

        # Fed / ECB news via Google News RSS
        try:
            q = urllib.parse.quote_plus("Federal Reserve interest rate decision 2025")
            url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
            entries = _parse_feed_with_ua(url)
            result["fed_recent_releases"] = [
                e.get("title", "") for e in entries[:5] if e.get("title")
            ]
        except Exception as e:
            logger.warning(f"Fed news fetch failed: {e}")

        return result
