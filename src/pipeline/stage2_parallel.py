"""
src/pipeline/stage2_parallel.py  — v2.5.1

FIX: growth agent key normalisation.
GrowthValuationAgent.AGENT_NAME = "growth_valuation" but the CIO scorer
and report table use "growth" as the key. This caused the growth score
to always be read as None.

Fix: after collecting all results, remap "growth_valuation" → "growth"
so the rest of the pipeline uses consistent keys.

Also: ensure every agent result has a "score" key (some agents use
different score field names like "moat_score", "det_risk_score").
We add a _score_normalised field so CIO and formatter always have
one consistent place to look.
"""

import asyncio
import logging

from src.data.knowledge_graph import KnowledgeGraph
from src.data.risk_engine import DeterministicRiskEngine
from src.agents.fundamental_agent import FundamentalAgent
from src.agents.macro_agent import MacroAgent
from src.agents.moat_agent import MoatAgent
from src.agents.growth_valuation_agent import GrowthValuationAgent
from src.agents.risk_narrative_agent import RiskNarrativeAgent
from src.agents.market_regime_agent import MarketRegimeAgent
from src.models.llm_factory import get_llm_with_fallback

logger = logging.getLogger(__name__)

# Maps internal agent key (used in pipeline dicts) → display name
_KEY_DISPLAY = {
    "fundamental":   "Fundamental Analyst",
    "macro":         "Macro & News",
    "moat":          "Competitive Moat",
    "growth":        "Growth & Valuation",
    "market_regime": "Market Regime",
    "risk_narrative":"Risk Narrative",
}


def _extract_score(report: dict, agent_key: str) -> float | None:
    """
    Normalise score extraction across all agent types.
    Each agent type may store its primary score under a different key.
    Returns None only if truly no score-like value exists.
    """
    if not isinstance(report, dict):
        return None

    # Direct "score" key — most agents
    val = report.get("score")
    if val is not None:
        try:
            return float(val)
        except (TypeError, ValueError):
            pass

    # Moat agent
    val = report.get("moat_score")
    if val is not None:
        try:
            return float(val)
        except (TypeError, ValueError):
            pass

    # Risk narrative agent (det_risk_score from engine, NOT an investment score)
    # We do NOT use det_risk_score as the agent's "score" here —
    # it's already used separately as the deterministic risk input.
    # Return None so the table shows the det_risk_score column correctly.

    # Market regime agent — no 0-10 investment score; uses multiplier
    # Return None — table formatter handles this explicitly.

    return None


async def run_specialist_agents(
    kg: KnowledgeGraph,
    config,
    skip_agents: list = None,
) -> dict:
    skip_agents = skip_agents or []

    # Step 1: Deterministic Risk Engine (no LLM)
    det_risk = DeterministicRiskEngine().compute(kg)

    # Step 2: Build agents (keyed by pipeline name, not AGENT_NAME)
    agent_tasks: dict[str, tuple] = {}

    if "fundamental" not in skip_agents:
        llm = get_llm_with_fallback("fundamental", config)
        agent_tasks["fundamental"] = (
            FundamentalAgent(llm, config).analyze(kg), llm
        )
    if "macro" not in skip_agents:
        llm = get_llm_with_fallback("macro", config)
        agent_tasks["macro"] = (
            MacroAgent(llm, config).analyze(kg), llm
        )
    if "moat" not in skip_agents:
        llm = get_llm_with_fallback("moat", config)
        agent_tasks["moat"] = (
            MoatAgent(llm, config).analyze(kg), llm
        )
    if "growth" not in skip_agents:
        llm = get_llm_with_fallback("growth_valuation", config)
        agent_tasks["growth"] = (                          # ← key is "growth"
            GrowthValuationAgent(llm, config).analyze(kg), llm
        )
    if "market_regime" not in skip_agents:
        llm = get_llm_with_fallback("market_regime", config)
        agent_tasks["market_regime"] = (
            MarketRegimeAgent(llm, config).analyze(kg), llm
        )
    if "risk_narrative" not in skip_agents:
        llm = get_llm_with_fallback("risk_narrative", config)
        agent_tasks["risk_narrative"] = (
            RiskNarrativeAgent(llm, config).analyze(
                kg, extra={"det_risk_output": det_risk}
            ),
            llm,
        )

    # Run all coroutines concurrently
    keys = list(agent_tasks.keys())
    coros = [agent_tasks[k][0] for k in keys]
    raw_results = await asyncio.gather(*coros, return_exceptions=True)

    agent_reports: dict[str, dict] = {}
    for pipeline_key, result in zip(keys, raw_results):
        if isinstance(result, Exception):
            logger.error(f"[Stage2] Agent '{pipeline_key}' raised exception: {result}")
            agent_reports[pipeline_key] = {
                "agent":       pipeline_key,
                "error":       str(result),
                "score":       None,
                "_model_used": "FAILED",
            }
        else:
            # Ensure pipeline key is consistent regardless of what model echoed back
            result["_pipeline_key"] = pipeline_key
            # Add normalised score for table display
            result["_score_display"] = _extract_score(result, pipeline_key)
            agent_reports[pipeline_key] = result

    agent_reports["det_risk"] = det_risk
    return agent_reports
