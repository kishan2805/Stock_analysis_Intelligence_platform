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
