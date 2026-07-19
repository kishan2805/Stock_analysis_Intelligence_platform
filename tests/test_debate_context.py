from src.pipeline.stage3_debate import DebateOrchestrator


def test_local_debate_context_keeps_only_score_bearing_facts():
    reports = {
        "fundamental": {
            "score": 7,
            "bull_points": ["x" * 500, "second"],
            "raw_financials": {"noise": "x" * 5000},
        }
    }
    compact = DebateOrchestrator._compact_reports(reports)
    assert "raw_financials" not in compact["fundamental"]
    assert len(compact["fundamental"]["bull_points"][0]) == 180


def test_debate_accepts_short_gemma_conviction_label():
    debate = DebateOrchestrator.__new__(DebateOrchestrator)
    assert debate._extract_score("Conviction Score: 8", "BULL CONVICTION SCORE") == 8
    assert debate._extract_score("Bear Conviction Score: 6/10", "BEAR CONVICTION SCORE") == 6
    assert debate._extract_score("Conviction: 7/10", "BULL CONVICTION SCORE") == 7
