import logging
import urllib.request
import urllib.parse
import feedparser

logger = logging.getLogger(__name__)

# feedparser needs a real browser UA to avoid 429s from Google News
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def _parse_feed_with_ua(url: str) -> list:
    """Parse an RSS feed with a proper User-Agent header."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read()
        feed = feedparser.parse(content)
        return feed.entries
    except Exception as e:
        logger.warning(f"Feed fetch failed ({url[:80]}): {e}")
        return []


class NewsFetcher:
    def fetch(self, company_name: str, ticker: str) -> dict:
        logger.info(f"Fetching news for {company_name} ({ticker})")

        # Deduplicate across sources by title
        seen_titles: set = set()
        all_articles: list = []

        for source_fn in [
            lambda: self._google_news_company(company_name),
            lambda: self._google_news_ticker(ticker),
            lambda: self._yahoo_finance_rss(ticker),
        ]:
            for art in source_fn():
                t = art.get("title", "").strip()
                if t and t not in seen_titles:
                    seen_titles.add(t)
                    all_articles.append(art)
            if len(all_articles) >= 20:
                break

        return {"news_headlines": all_articles[:25]}

    # ── sources ───────────────────────────────────────────────────────────

    def _google_news_company(self, company_name: str) -> list:
        """Search by company name — works for both Indian and US stocks."""
        q = urllib.parse.quote_plus(company_name)
        # Try US English first (broader coverage), then India locale
        for url in [
            f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en",
            f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en",
        ]:
            entries = _parse_feed_with_ua(url)
            if entries:
                return [self._entry_to_article(e) for e in entries[:15]]
        return []

    def _google_news_ticker(self, ticker: str) -> list:
        """Search by ticker symbol — catches earnings reports and analyst notes."""
        clean = ticker.replace(".NS", "").replace(".BO", "")
        q = urllib.parse.quote_plus(f"{clean} stock")
        url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
        entries = _parse_feed_with_ua(url)
        return [self._entry_to_article(e) for e in entries[:10]]

    def _yahoo_finance_rss(self, ticker: str) -> list:
        """Yahoo Finance RSS — reliable fallback, doesn't require a UA."""
        try:
            url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
            feed = feedparser.parse(url)
            return [self._entry_to_article(e) for e in feed.entries[:10]]
        except Exception as e:
            logger.warning(f"Yahoo Finance RSS failed for {ticker}: {e}")
            return []

    # ── helpers ───────────────────────────────────────────────────────────

    def _entry_to_article(self, entry) -> dict:
        source = entry.get("source", {})
        source_name = (
            source.get("title", "") if isinstance(source, dict)
            else str(source)
        )
        return {
            "title":     entry.get("title", "").strip(),
            "published": entry.get("published", ""),
            "source":    source_name,
            "link":      entry.get("link", ""),
            "sentiment": None,
        }
