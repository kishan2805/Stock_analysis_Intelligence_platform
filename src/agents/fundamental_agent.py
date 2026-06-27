from src.agents.base_agent import BaseAgent

class FundamentalAgent(BaseAgent):
    AGENT_NAME = "fundamental"
    PROMPT_FILE = "fundamental_agent.md"
    REQUIRED_KG_FIELDS = [
        "ticker", "company_name", "sector", "exchange",
        "investment_duration_months", "data_gaps",
        "balance_sheet", "income_statement", "cash_flow",
        "key_ratios", "valuation_metrics",
        "promoter_holding", "fii_holding", "dii_holding",
        "analyst_ratings", "earnings_surprises",
    ]
