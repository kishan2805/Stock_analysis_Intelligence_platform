from src.agents.base_agent import BaseAgent

class MarketRegimeAgent(BaseAgent):
    AGENT_NAME = "market_regime"
    PROMPT_FILE = "market_regime_agent.md"
    REQUIRED_KG_FIELDS = [
        "ticker", "company_name", "sector",
        "regime_data", "fii_flow_30d",
        "geopolitical_headlines", "macro_indicators",
    ]
