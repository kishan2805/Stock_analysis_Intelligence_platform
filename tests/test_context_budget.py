from src.agents.base_agent import _trim_kg_data
from src.models.ollama_client import OllamaClient, _get_num_ctx, _get_max_output_tokens, _get_timeout_seconds


def test_small_context_keeps_a_compact_financial_snapshot():
    data = {
        "balance_sheet": {"2025": {"Total Debt": 100, "Cash Cash Equivalents": 20, "Noise": "x" * 500}},
        "income_statement": {"2025": {"Total Revenue": 200, "Net Income": 25, "Noise": "x" * 500}},
        "cash_flow": {"2025": {"Operating Cash Flow": 30, "Free Cash Flow": 10, "Noise": "x" * 500}},
        "key_ratios": {"roe": 0.2},
    }
    trimmed = _trim_kg_data(data, context_budget=100)
    assert "financial_snapshot" in trimmed
    assert trimmed["financial_snapshot"]["income_statement"]["2025"]["Total Revenue"] == 200


def test_gemma_uses_responsive_local_request_context():
    assert _get_num_ctx("gemma3:4b") == 2_048
    assert _get_max_output_tokens("gemma3:4b", 10_000) == 900
    assert _get_timeout_seconds("gemma3:4b") == 180
    assert OllamaClient("gemma3:4b", num_ctx_override=10_000).num_ctx_override == 10_000
