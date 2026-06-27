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

async def run_specialist_agents(kg: KnowledgeGraph, config, skip_agents: list = None) -> dict:
    skip_agents = skip_agents or []

    # Step 1: Deterministic Risk Engine (no LLM)
    det_risk = DeterministicRiskEngine().compute(kg)

    # Step 2: Build agents
    agents = {}
    if "fundamental" not in skip_agents:
        agents["fundamental"] = FundamentalAgent(get_llm_with_fallback("fundamental", config), config)
    if "macro" not in skip_agents:
        agents["macro"] = MacroAgent(get_llm_with_fallback("macro", config), config)
    if "moat" not in skip_agents:
        agents["moat"] = MoatAgent(get_llm_with_fallback("moat", config), config)
    if "growth" not in skip_agents:
        agents["growth"] = GrowthValuationAgent(get_llm_with_fallback("growth_valuation", config), config)
    if "market_regime" not in skip_agents:
        agents["market_regime"] = MarketRegimeAgent(get_llm_with_fallback("market_regime", config), config)

    # Risk narrative needs det_risk injected
    risk_agent = None
    if "risk_narrative" not in skip_agents:
        risk_llm = get_llm_with_fallback("risk_narrative", config)
        risk_agent = RiskNarrativeAgent(risk_llm, config)

    # Run all in parallel
    tasks = {name: agent.analyze(kg) for name, agent in agents.items()}
    if risk_agent:
        tasks["risk_narrative"] = risk_agent.analyze(kg, det_risk_output=det_risk)

    results = await asyncio.gather(*tasks.values(), return_exceptions=True)
    agent_reports = {}
    for name, result in zip(tasks.keys(), results):
        if isinstance(result, Exception):
            logger.error(f"Agent {name} raised exception: {result}")
            agent_reports[name] = {"agent": name, "error": str(result), "score": None, "_model_used": "FAILED"}
        else:
            agent_reports[name] = result

    agent_reports["det_risk"] = det_risk
    return agent_reports
