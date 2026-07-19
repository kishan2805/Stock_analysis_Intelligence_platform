import json
import logging
from pathlib import Path

from src.agents.base_agent import BaseAgent
from src.data.knowledge_graph import KnowledgeGraph
from src.models.base_llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

# Maximum chars for the KG summary sent to the auditor
_MAX_KG_SUMMARY_CHARS = 4_000
_LOCAL_AUDIT_MAX_TOKENS = 500


class EvidenceAuditor(BaseAgent):
    AGENT_NAME = "evidence_auditor"
    PROMPT_FILE = "evidence_auditor.md"
    REQUIRED_KG_FIELDS = []   # receives a custom compact summary, not raw KG fields

    async def audit(self, kg: KnowledgeGraph, agent_reports: dict) -> dict:
        try:
            agent_cfg = self.config.agents.get(self.AGENT_NAME, {})

            kg_summary = self._build_kg_summary(kg)
            reports_to_audit = {
                k: v for k, v in agent_reports.items() if k != "det_risk"
            }
            is_local_gemma = self.llm.get_model_name().lower().startswith("gemma3:4b")
            if is_local_gemma:
                reports_to_audit = self._compact_reports(reports_to_audit)
                kg_summary = {
                    "key_ratios": kg.key_ratios,
                    "valuation_metrics": kg.valuation_metrics,
                    "data_gaps": kg.data_gaps,
                    "news_headline_count": len(kg.news_headlines),
                    "peer_count": len(kg.peers),
                }

            user_msg = (
                "Audit the following agent reports against the IntelligenceBundle.\n"
                "Respond with valid JSON only — no markdown, no preamble.\n\n"
                + json.dumps(
                    {
                        "intelligence_bundle_summary": kg_summary,
                        "agent_reports": reports_to_audit,
                    },
                    default=str,
                    indent=2,
                )
            )

            system_prompt = self.system_prompt
            if is_local_gemma:
                system_prompt = (
                    "You are a concise evidence checker. Compare the supplied compact reports "
                    "only with the supplied data. Return ONLY valid JSON and do not rewrite reports. "
                    "Use this shape: {\"agent\":\"evidence_auditor\","
                    "\"reliability_score\":0-10,\"confidence_adjustment\":0 or negative,"
                    "\"evidence_completeness\":{\"overall\":0-1},"
                    "\"contradictions\":[],\"citation_errors\":[],\"warnings\":[]}."
                )
            raw = self.llm.complete(
                system_prompt=system_prompt,
                user_message=user_msg,
                temperature=getattr(agent_cfg, "temperature", 0.1),
                max_tokens=min(getattr(agent_cfg, "max_tokens", 2000), _LOCAL_AUDIT_MAX_TOKENS)
                if is_local_gemma else getattr(agent_cfg, "max_tokens", 2000),
                response_format="json",
            )

            # Use the full recovery pipeline from BaseAgent
            result = self._parse_and_validate(raw)
            result["_model_used"] = self.llm.get_model_name()

            # Always populate validated_reports — fall back to originals if missing
            if "validated_reports" not in result or not result["validated_reports"]:
                result["validated_reports"] = agent_reports

            # Ensure numeric fields have defaults
            result.setdefault("reliability_score", 5.0)
            result.setdefault("confidence_adjustment", -0.3)
            result.setdefault("evidence_completeness", {"overall": 0.5})
            result.setdefault("contradictions", [])
            result.setdefault("citation_errors", [])
            result.setdefault("warnings", [])

            return result

        except Exception as e:
            logger.error(f"[evidence_auditor] failed: {e}")
            return self._fallback_audit(agent_reports, error=str(e))

    @staticmethod
    def _compact_reports(reports: dict) -> dict:
        """Keep audit-relevant facts without asking a local model to reprint reports."""
        compact = {}
        allowed = (
            "agent", "ticker", "score", "moat_score", "confidence", "error",
            "key_metrics_cited", "key_macro_signals", "bull_points", "bear_points",
            "ranked_risks", "sector_regime_multiplier", "valuation_verdict",
        )
        for name, report in reports.items():
            if not isinstance(report, dict):
                compact[name] = report
                continue
            item = {key: report[key] for key in allowed if key in report}
            for list_key in ("bull_points", "bear_points", "ranked_risks"):
                if isinstance(item.get(list_key), list):
                    item[list_key] = item[list_key][:2]
            compact[name] = item
        return compact

    def _build_kg_summary(self, kg: KnowledgeGraph) -> dict:
        """
        Send only the key numeric fields to the auditor — not the full
        balance sheet — so the prompt stays within token budget.
        """
        summary = {
            "key_ratios":      kg.key_ratios,
            "valuation_metrics": kg.valuation_metrics,
            "promoter_holding_latest": (
                kg.promoter_holding[-1] if kg.promoter_holding else None
            ),
            "news_headline_count": len(kg.news_headlines),
            "peer_count":          len(kg.peers),
            "data_gaps":           kg.data_gaps,
            "earnings_surprises":  kg.earnings_surprises,
        }
        # Trim if still large
        raw = json.dumps(summary, default=str)
        if len(raw) > _MAX_KG_SUMMARY_CHARS:
            summary.pop("earnings_surprises", None)
        return summary

    def _fallback_audit(self, agent_reports: dict, error: str = "") -> dict:
        """Return a safe default when the auditor LLM itself fails."""
        return {
            "agent":                "evidence_auditor",
            "error":                error or "auditor_failed",
            "reliability_score":    5.0,
            "confidence_adjustment": -0.3,
            "evidence_completeness": {"overall": 0.5},
            "contradictions":       [],
            "citation_errors":      [],
            "warnings":             [f"Evidence Auditor failed: {error}"],
            "validated_reports":    agent_reports,  # pass originals through
            "_model_used":          "FAILED",
        }
