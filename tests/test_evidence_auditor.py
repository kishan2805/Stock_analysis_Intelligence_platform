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


def test_audit_patch_never_replaces_or_rescores_specialist_reports():
    originals = {
        "fundamental": {
            "agent": "fundamental_analyst",
            "ticker": "AAPL",
            "score": 8,
            "key_metrics_cited": {"revenue_growth": 0.08, "debt_equity": 0.9},
            "_model_used": "nvidia",
        },
        "macro": {"score": 7},
        "moat": {"moat_score": 8},
        "growth": {"score": 6},
    }
    patches = {
        "NOTE": "only corrected fields are shown",
        "fundamental_analyst": {
            "agent": "fundamental_analyst",
            "score": 1,
            "key_metrics_cited": {"debt_equity": 0.7},
        },
    }

    merged = EvidenceAuditor._merge_report_patches(originals, patches)

    assert set(merged) == set(originals)
    assert merged["fundamental"]["score"] == 8
    assert merged["fundamental"]["key_metrics_cited"] == {
        "revenue_growth": 0.08,
        "debt_equity": 0.7,
    }
    assert merged["macro"]["score"] == 7
    assert merged["growth"]["score"] == 6
