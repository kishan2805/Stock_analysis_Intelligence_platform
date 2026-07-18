import logging

from src.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

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

    _LOCAL_GEMMA_PROMPT = """You are a concise fundamental equity analyst. Use only supplied data; never invent numbers.
Return ONLY valid JSON. Keep bull_points and bear_points to two short items each.
Required shape:
{"agent":"fundamental_analyst","ticker":"<ticker>","score":0-10,
"score_breakdown":{"financial_health":0-3,"growth_quality":0-3,"valuation":0-2,"management_quality":0-2},
"bull_points":["...","..."],"bear_points":["...","..."],
"key_metrics_cited":{"roe_latest":null,"debt_equity":null,"fcf_margin":null,"revenue_cagr_3yr":null,"promoter_pledge_pct":null},
"earnings_quality_flag":"CLEAN|WARNING|RED_FLAG","confidence":"high|medium|low","data_gaps_impact":"none|minor|significant"}
Use null for unavailable metrics."""

    async def analyze(self, kg, **kwargs) -> dict:
        """Keep Gemma's numbers-heavy response below its local output budget."""
        try:
            agent_cfg = self.config.agents.get(self.AGENT_NAME, {})
            is_local_gemma = self.llm.get_model_name().lower().startswith("gemma3:4b")
            raw = self.llm.complete(
                system_prompt=self._LOCAL_GEMMA_PROMPT if is_local_gemma else self.system_prompt,
                user_message=self._build_user_message(kg, kwargs.get("extra")),
                temperature=getattr(agent_cfg, "temperature", 0.1),
                max_tokens=700 if is_local_gemma else getattr(agent_cfg, "max_tokens", 2000),
                response_format="json",
            )
            result = self._parse_and_validate(raw)
            if result.get("score") is None:
                raise ValueError("fundamental response did not include a numeric score")
            result["_model_used"] = self.llm.get_model_name()
            return result
        except Exception as exc:
            logger.error("[fundamental] failed: %s", exc)
            return {
                "agent": self.AGENT_NAME,
                "error": str(exc),
                "score": None,
                "_model_used": "FAILED",
            }
