import logging
from datetime import datetime
from src.data.knowledge_graph import KnowledgeGraph
from src.data.stock_fetcher import StockFetcher
from src.data.news_fetcher import NewsFetcher
from src.data.regime_fetcher import RegimeFetcher
from src.utils.cache import Cache

logger = logging.getLogger(__name__)


class IntelligenceBuilder:
    def __init__(self, config):
        self.config = config
        self.cache = Cache(config)

    def build(
        self,
        ticker: str,
        exchange: str,
        duration_months: int,
        depth: str,
    ) -> KnowledgeGraph:
        cache_key = f"kg_{ticker}_{exchange}"
        cached = self.cache.get(
            cache_key,
            ttl_hours=self.config.cache.knowledge_graph_ttl_hours
        )
        if cached:
            logger.info(f"Cache hit for {ticker}")
            return KnowledgeGraph.from_json(cached)

        logger.info(f"Building KnowledgeGraph for {ticker}")
        stock_data  = StockFetcher().fetch(ticker, exchange)
        news_data   = NewsFetcher().fetch(stock_data.get("company_name", ticker), ticker)
        regime_data = RegimeFetcher().fetch()

        # ── data gap audit ────────────────────────────────────────────────
        data_gaps: list[str] = []
        if not stock_data.get("balance_sheet"):
            data_gaps.append("balance_sheet")
        if not stock_data.get("income_statement"):
            data_gaps.append("income_statement")
        if not stock_data.get("cash_flow"):
            data_gaps.append("cash_flow")
        if not stock_data.get("key_ratios", {}).get("roe"):
            data_gaps.append("key_ratios_partial")
        if not news_data.get("news_headlines"):
            data_gaps.append("news_headlines")
        if not regime_data.get("geopolitical_headlines"):
            data_gaps.append("geopolitical_headlines")
        if not stock_data.get("peers"):
            data_gaps.append("peers")

        kg = KnowledgeGraph(
            fetch_timestamp=datetime.now().isoformat(timespec="seconds"),
            investment_duration_months=duration_months,
            analysis_depth=depth,
            data_gaps=data_gaps,
            **stock_data,
            **news_data,
            **regime_data,
        )

        # Only cache if core financial data is present;
        # skip caching empty shells so next run retries the fetch.
        if stock_data.get("balance_sheet") or stock_data.get("income_statement"):
            self.cache.set(cache_key, kg.to_json())
        else:
            logger.warning(f"Skipping cache for {ticker}: no financial data returned")

        return kg
