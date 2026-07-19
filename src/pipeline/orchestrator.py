import asyncio
import logging
from types import SimpleNamespace
from src.data.intelligence_builder import IntelligenceBuilder
from src.pipeline.stage2_parallel import run_specialist_agents
from src.agents.evidence_auditor import EvidenceAuditor
from src.agents.cio_agent import CIOAgent
from src.pipeline.stage3_debate import DebateOrchestrator
from src.models.llm_factory import get_llm_with_fallback

logger = logging.getLogger(__name__)


def _missing_core_agents(agent_reports: dict) -> list[str]:
    missing = []
    for name in ("fundamental", "macro", "growth"):
        report = agent_reports.get(name, {})
        if not isinstance(report, dict) or report.get("error") or report.get("score") is None:
            missing.append(name)
    return missing

class PipelineOrchestrator:
    def __init__(self, config):
        self.config = config

    async def run(self, ticker: str, exchange: str,
                  duration_months: int, depth: str,
                  skip_debate: bool = False) -> dict:

        # Stage 1: Intelligence Builder
        logger.info("Stage 1: Building KnowledgeGraph")
        kg = IntelligenceBuilder(self.config).build(
            ticker, exchange, duration_months, depth
        )

        # Determine execution mode (support dict or namespace formats)
        exec_modes = self.config.execution_modes
        default_mode = getattr(self.config, "default_execution_mode", "balanced")
        if isinstance(exec_modes, dict):
            raw = exec_modes.get(depth) or exec_modes.get(default_mode) or exec_modes.get("balanced") or {}
            mode_cfg = SimpleNamespace(**raw) if isinstance(raw, dict) else SimpleNamespace()
        else:
            mode_cfg = getattr(exec_modes, depth, getattr(exec_modes, default_mode, getattr(exec_modes, "balanced", SimpleNamespace())))

        skip_agents = getattr(mode_cfg, "skip_agents", [])
        debate_rounds = getattr(mode_cfg, "debate_rounds", 4)

        # Stage 2: Parallel specialist agents
        logger.info("Stage 2: Running specialist agents")
        agent_reports = await run_specialist_agents(kg, self.config, skip_agents=skip_agents)
        det_risk = agent_reports.pop("det_risk")

        # Stage 3: Evidence Auditor
        logger.info("Stage 3: Evidence Auditor")
        auditor = EvidenceAuditor(
            get_llm_with_fallback("evidence_auditor", self.config),
            self.config
        )
        audited_bundle = await auditor.audit(kg, agent_reports)

        # Stage 4: Bull vs Bear debate
        debate_result = None
        if not skip_debate:
            logger.info("Stage 4: Bull vs Bear debate")
            debate = DebateOrchestrator(self.config)
            debate_result = debate.run(
                audited_bundle, ticker, kg.company_name, duration_months,
                max_rounds=debate_rounds
            )
        else:
            debate_result = {
                "transcript": [],
                "bull_conviction": 5.0,
                "bear_conviction": 5.0,
                "high_uncertainty": False,
                "error": None
            }

        # Stage 5: CIO judgment
        logger.info("Stage 5: CIO Judgment")
        weights = self.config.scoring_weights
        cio = CIOAgent(
            get_llm_with_fallback("cio", self.config),
            self.config
        )
        cio_output = await cio.judge(
            audited_bundle, debate_result, det_risk,
            weights, ticker, kg.company_name, duration_months
        )

        return {
            "kg_metadata": {
                "ticker": kg.ticker,
                "company": kg.company_name,
                "fetched": kg.fetch_timestamp,
                "data_gaps": kg.data_gaps,
            },
            "agent_reports": agent_reports,
            "det_risk": det_risk,
            "audited_bundle": audited_bundle,
            "debate": debate_result,
            "cio": cio_output,
        }
