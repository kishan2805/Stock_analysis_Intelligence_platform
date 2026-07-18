from src.agents.evidence_auditor import EvidenceAuditor


def test_local_audit_report_compaction_keeps_only_verification_facts():
    compact = EvidenceAuditor._compact_reports({
        "fundamental": {
            "agent": "fundamental", "score": 7, "key_metrics_cited": {"roe": 0.2},
            "bull_points": ["a", "b", "c"], "long_narrative": "x" * 10000,
        }
    })
    report = compact["fundamental"]
    assert report["score"] == 7
    assert report["bull_points"] == ["a", "b"]
    assert "long_narrative" not in report
