from src.agents.base_agent import BaseAgent

class MoatAgent(BaseAgent):
    AGENT_NAME = "moat"
    PROMPT_FILE = "moat_agent.md"
    REQUIRED_KG_FIELDS = [
        "ticker", "company_name", "sector", "industry",
        "key_ratios", "valuation_metrics",
        "peers", "market_position",
    ]
