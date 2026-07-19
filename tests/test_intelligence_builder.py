from types import SimpleNamespace
import pytest

from src.data.intelligence_builder import IntelligenceBuilder, MarketDataUnavailableError


def test_invalid_ticker_stops_before_agents_run(monkeypatch, tmp_path):
    class EmptyFetcher:
        def fetch(self, ticker, exchange):
            return {
                "ticker": ticker, "exchange": exchange,
                "valuation_metrics": {}, "balance_sheet": {},
                "income_statement": {}, "cash_flow": {},
            }

    monkeypatch.setattr("src.data.intelligence_builder.StockFetcher", EmptyFetcher)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(MarketDataUnavailableError, match="No market data found"):
        config = SimpleNamespace(cache=SimpleNamespace(knowledge_graph_ttl_hours=4))
        IntelligenceBuilder(config).build("AAPA", "US", 18, "quick")
