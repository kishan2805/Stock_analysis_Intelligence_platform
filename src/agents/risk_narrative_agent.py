from src.agents.base_agent import BaseAgent

class RiskNarrativeAgent(BaseAgent):
    AGENT_NAME = "risk_narrative"
    PROMPT_FILE = "risk_agent.md"
    REQUIRED_KG_FIELDS = [
        "ticker", "company_name", "sector",
        "key_ratios", "governance_flags",
        "promoter_holding", "debt_schedule",
    ]

    async def analyze(self, kg, det_risk_output: dict = None, **kwargs):
        return await super().analyze(kg, extra={"det_risk_output": det_risk_output or {}})
