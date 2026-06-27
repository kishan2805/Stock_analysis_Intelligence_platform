import logging

logger = logging.getLogger(__name__)

class DeterministicRiskEngine:
    """Computes structured risk score from KnowledgeGraph fields. Pure Python — no LLM."""

    def compute(self, kg) -> dict:
        scores = {}

        # Financial Risk (0-25)
        de = kg.key_ratios.get("debt_equity", 0) or 0
        ic = kg.key_ratios.get("interest_coverage", 999) or 999
        fcf = kg.key_ratios.get("fcf_margin", 0.1) or 0.1
        scores["financial"] = self._score_financial(de, ic, fcf, kg.debt_schedule)

        # Governance Risk (0-25)
        pledge = 0
        if kg.promoter_holding and isinstance(kg.promoter_holding, list) and len(kg.promoter_holding) > 0:
            last = kg.promoter_holding[-1]
            if isinstance(last, dict):
                pledge = last.get("pledge_pct", 0) or 0
        rpt = kg.key_ratios.get("related_party_pct", 0) or 0
        auditor_change = any(
            isinstance(f, dict) and f.get("type") == "auditor_change"
            for f in (kg.governance_flags or [])
        )
        scores["governance"] = self._score_governance(pledge, rpt, auditor_change, kg.governance_flags)

        # Other categories (simplified for robustness)
        scores["competitive"] = self._score_competitive(kg)
        scores["regulatory"] = self._score_regulatory(kg)
        scores["macro"] = self._score_macro(kg)

        raw_total = sum(scores.values())
        normalised = round(raw_total / 10, 2)

        return {
            "det_risk_score": normalised,
            "risk_level": self._band(normalised),
            "breakdown": scores,
            "immediate_flags": self._extract_flags(kg)
        }

    def _score_financial(self, debt_equity, interest_coverage, fcf_margin, debt_schedule):
        score = 0
        if debt_equity > 3.0:   score += 10
        elif debt_equity > 1.5: score += 5
        elif debt_equity > 0.8: score += 2

        if interest_coverage < 1.5:  score += 10
        elif interest_coverage < 3:  score += 5
        elif interest_coverage < 5:  score += 2

        if fcf_margin < 0:    score += 5
        elif fcf_margin < 0.03: score += 2

        return min(score, 25)

    def _score_governance(self, pledge_pct, rpt_pct, auditor_change, flags):
        score = 0
        if pledge_pct > 40:   score += 15
        elif pledge_pct > 25: score += 10
        elif pledge_pct > 10: score += 5
        elif pledge_pct > 5:  score += 2

        if rpt_pct > 10:  score += 7
        elif rpt_pct > 5: score += 4

        if auditor_change: score += 5

        sebi_actions = sum(1 for f in (flags or []) if isinstance(f, dict) and "SEBI" in str(f.get("type", "")))
        score += sebi_actions * 3

        return min(score, 25)

    def _score_competitive(self, kg):
        # Simplified: 0-20 based on available data
        return 5

    def _score_regulatory(self, kg):
        # Simplified: 0-15
        return 3

    def _score_macro(self, kg):
        # Simplified: 0-15
        return 4

    def _band(self, score):
        if score >= 7.5: return "CRITICAL"
        if score >= 5.5: return "HIGH"
        if score >= 3.5: return "MEDIUM"
        return "LOW"

    def _extract_flags(self, kg) -> list:
        flags = []
        pledge = 0
        if kg.promoter_holding and isinstance(kg.promoter_holding, list) and len(kg.promoter_holding) > 0:
            last = kg.promoter_holding[-1]
            if isinstance(last, dict):
                pledge = last.get("pledge_pct", 0) or 0
        if pledge > 25:
            flags.append(f"CRITICAL: Promoter pledge {pledge}% — forced selling risk")
        ic = kg.key_ratios.get("interest_coverage", 999) or 999
        if ic < 2:
            flags.append("HIGH: Interest coverage below 2x — debt servicing stress")
        for f in (kg.governance_flags or []):
            if isinstance(f, dict) and f.get("severity") in ["HIGH", "CRITICAL"]:
                flags.append(f"{f['severity']}: {f.get('description', '')}")
        return flags
