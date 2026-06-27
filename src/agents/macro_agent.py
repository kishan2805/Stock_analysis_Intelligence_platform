from src.agents.base_agent import BaseAgent

class MacroAgent(BaseAgent):
    AGENT_NAME = "macro"
    PROMPT_FILE = "macro_agent.md"
    REQUIRED_KG_FIELDS = [
        "ticker", "company_name", "sector", "exchange",
        "investment_duration_months",
        "news_headlines", "analyst_ratings", "earnings_surprises",
        "macro_indicators", "fii_holding", "fii_flow_30d",
    ]
