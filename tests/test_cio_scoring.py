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
