from src.agents.base_agent import BaseAgent

class GrowthValuationAgent(BaseAgent):
    AGENT_NAME = "growth_valuation"
    PROMPT_FILE = "growth_valuation_agent.md"
    REQUIRED_KG_FIELDS = [
        "ticker", "company_name", "sector", "industry",
        "investment_duration_months",
        "income_statement", "cash_flow", "key_ratios",
        "valuation_metrics", "peers", "analyst_ratings",
    ]
