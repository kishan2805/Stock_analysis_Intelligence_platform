import feedparser
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class NewsFetcher:
    def fetch(self, company_name: str, ticker: str) -> dict:
        logger.info(f"Fetching news for {company_name}")
        headlines = self._google_news_rss(company_name)
        return {"news_headlines": headlines}

    def _google_news_rss(self, query: str) -> list:
        try:
            url = f"https://news.google.com/rss/search?q={query.replace(' ', '+')}&hl=en-IN&gl=IN&ceid=IN:en"
            feed = feedparser.parse(url)
            articles = []
            for entry in feed.entries[:20]:
                articles.append({
                    "title": entry.get("title", ""),
                    "published": entry.get("published", ""),
                    "source": entry.get("source", {}).get("title", "") if isinstance(entry.get("source"), dict) else "",
                    "link": entry.get("link", ""),
                    "sentiment": None,
                })
            return articles
        except Exception as e:
            logger.error(f"News fetch error: {e}")
            return []
