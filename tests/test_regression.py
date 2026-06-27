import pytest
import asyncio
from src.pipeline.orchestrator import PipelineOrchestrator
from src.utils.config_loader import load_config

STOCKS = [("TCS.NS", "IN", 18), ("AAPL", "US", 12)]

@pytest.mark.parametrize("ticker,exchange,duration", STOCKS)
def test_pipeline_completes(ticker, exchange, duration):
    config = load_config("config/settings.yaml")
    result = asyncio.run(
        PipelineOrchestrator(config).run(ticker, exchange, duration, "quick", skip_debate=True)
    )
    cio = result["cio"]
    assert "final_rating" in cio
    assert 0 <= cio["final_rating"] <= 10
    assert cio["verdict"] in ["STRONG BUY", "BUY", "ACCUMULATE", "HOLD", "REDUCE", "AVOID"]
