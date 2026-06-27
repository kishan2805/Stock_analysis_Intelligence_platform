import pytest
from src.data.risk_engine import DeterministicRiskEngine
from src.data.knowledge_graph import KnowledgeGraph

def test_high_pledge_scores_high():
    kg = KnowledgeGraph(
        ticker="TEST",
        promoter_holding=[{"pledge_pct": 45}],
        key_ratios={"debt_equity": 0.3, "interest_coverage": 8, "fcf_margin": 0.05},
        governance_flags=[]
    )
    engine = DeterministicRiskEngine()
    result = engine.compute(kg)
    assert result["risk_level"] in ["HIGH", "CRITICAL"]
    assert result["det_risk_score"] >= 5.5

def test_clean_company_scores_low():
    kg = KnowledgeGraph(
        ticker="TEST",
        promoter_holding=[{"pledge_pct": 2}],
        key_ratios={"debt_equity": 0.1, "interest_coverage": 15, "fcf_margin": 0.1},
        governance_flags=[]
    )
    engine = DeterministicRiskEngine()
    result = engine.compute(kg)
    assert result["risk_level"] == "LOW"
    assert result["det_risk_score"] < 3.5

def test_empty_kg_handles_gracefully():
    kg = KnowledgeGraph(ticker="TEST")
    engine = DeterministicRiskEngine()
    result = engine.compute(kg)
    assert "det_risk_score" in result
    assert "risk_level" in result
    assert result["risk_level"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]
