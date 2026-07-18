from src.pipeline.orchestrator import _missing_core_agents


def test_missing_fundamental_report_is_not_scored_as_a_default_five():
    reports = {
        "fundamental": {"error": "timed out", "score": None},
        "macro": {"score": 6},
        "growth": {"score": 7},
    }
    missing = _missing_core_agents(reports)
    assert missing == ["fundamental"]
