from src.agents.cio_agent import _safe_regime_multiplier
from src.agents.cio_agent import CIOAgent
from types import SimpleNamespace


def test_risk_off_regime_multiplier_remains_negative():
    assert _safe_regime_multiplier(-0.4) == -0.4
    assert _safe_regime_multiplier(-9) == -1.5


def test_missing_specialist_is_not_replaced_with_neutral_five():
    agent = CIOAgent.__new__(CIOAgent)
    result = agent._compute_scores(
        {
            "validated_reports": {
                "fundamental": {"error": "timeout"},
                "macro": {"score": 6},
                "moat": {"moat_score": 7},
                "growth": {"score": 7},
                "market_regime": {"sector_regime_multiplier": 0},
            },
            "confidence_adjustment": 0,
            "reliability_score": 5,
        },
        {"bull_conviction": 5, "bear_conviction": 5},
        {"det_risk_score": 2},
        {"fundamental": 0.25, "macro": 0.2, "moat": 0.15, "growth": 0.2, "risk": 0.2},
        "AAPL", "Apple Inc.", 18,
    )
    calc = result["score_calculation"]
    assert calc["agent_scores"]["fundamental"] is None
    assert "fundamental" in calc["missing_agents"]
    assert calc["weights"]["fundamental"] == 0


def test_local_cio_narrative_uses_grounded_fields_only():
    agent = CIOAgent.__new__(CIOAgent)
    narrative = agent._local_narrative(
        {},
        {
            "validated_reports": {
                "fundamental": {"key_metrics_cited": {"debt_equity": 0.8}},
                "macro": {"sentiment_summary": "Neutral."},
                "moat": {"moat_score": 7, "moat_category": "WIDE"},
                "growth": {"valuation_verdict": "FAIR", "relative_valuation": {"pe_current": 20}},
                "risk_narrative": {"ranked_risks": [{"risk": "Competition"}]},
                "market_regime": {"primary_regime": "NEUTRAL_CONSOLIDATION"},
            }
        },
        {},
        {"det_risk_score": 2.4},
    )
    assert all("850 million" not in item for item in narrative["five_point_summary"])
    assert narrative["thesis_invalidating_risk"] == "Competition"
