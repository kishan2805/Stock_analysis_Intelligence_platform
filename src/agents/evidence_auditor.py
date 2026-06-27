import json, logging
from pathlib import Path
from src.data.knowledge_graph import KnowledgeGraph
from src.models.base_llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

class EvidenceAuditor:
    AGENT_NAME = "evidence_auditor"
    PROMPT_FILE = "evidence_auditor.md"

    def __init__(self, llm: BaseLLMClient, config):
        self.llm = llm
        self.config = config
        self.system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        path = Path("config/prompts") / self.PROMPT_FILE
        if not path.exists():
            raise FileNotFoundError(f"Prompt not found: {path}")
        return path.read_text()

    async def audit(self, kg: KnowledgeGraph, agent_reports: dict) -> dict:
        try:
            agent_cfg = self.config.agents.get(self.AGENT_NAME, {})

            # Build compact KG summary
            kg_summary = {
                "key_ratios": kg.key_ratios,
                "valuation_metrics": kg.valuation_metrics,
                "promoter_holding": kg.promoter_holding[-2:] if kg.promoter_holding else [],
                "news_count": len(kg.news_headlines),
                "data_gaps": kg.data_gaps,
            }

            user_msg = json.dumps({
                "intelligence_bundle_summary": kg_summary,
                "agent_reports": {k: v for k, v in agent_reports.items() if k != "det_risk"}
            }, default=str, indent=2)

            raw = self.llm.complete(
                system_prompt=self.system_prompt,
                user_message=f"Audit the following agent reports against the IntelligenceBundle:\n\n{user_msg}",
                temperature=getattr(agent_cfg, "temperature", 0.1),
                max_tokens=getattr(agent_cfg, "max_tokens", 2000),
                response_format="json"
            )

            result = self._parse_and_validate(raw)
            result["_model_used"] = self.llm.get_model_name()
            return result
        except Exception as e:
            logger.error(f"[evidence_auditor] failed: {e}")
            return {
                "agent": "evidence_auditor",
                "error": str(e),
                "reliability_score": 5.0,
                "confidence_adjustment": -0.5,
                "evidence_completeness": {"overall": 0.5},
                "contradictions": [],
                "citation_errors": [],
                "warnings": [f"Auditor failed: {e}"],
                "validated_reports": agent_reports,
                "_model_used": "FAILED"
            }

    def _parse_and_validate(self, raw: str) -> dict:
        try:
            clean = raw.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:-1]) if len(lines) > 2 else lines[0].replace("```json", "").replace("```", "")
            result = json.loads(clean)
            if "agent" not in result:
                result["agent"] = self.AGENT_NAME
            return result
        except json.JSONDecodeError as e:
            logger.error(f"[{self.AGENT_NAME}] JSON parse failed: {e}")
            return {"agent": self.AGENT_NAME, "error": "json_parse_failed", "reliability_score": 5.0}
