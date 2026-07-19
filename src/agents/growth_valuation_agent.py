import logging

from src.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

class GrowthValuationAgent(BaseAgent):
    AGENT_NAME = "growth_valuation"
    PROMPT_FILE = "growth_valuation_agent.md"
    REQUIRED_KG_FIELDS = [
        "ticker", "company_name", "sector", "industry",
        "investment_duration_months",
        "income_statement", "cash_flow", "key_ratios",
        "valuation_metrics", "peers", "analyst_ratings",
    ]

    _LOCAL_GEMMA_PROMPT = """You are a concise growth and valuation analyst. Use only supplied data; never invent numbers.
Return ONLY valid JSON. Keep growth_drivers to two short items and use null for missing values.
Required shape:
{"agent":"growth_valuation_analyst","ticker":"<ticker>","score":0-10,
"valuation_verdict":"OVERVALUED|FAIR|UNDERVALUED",
"relative_valuation":{"pe_current":null,"pe_5yr_avg":null,"pe_sector_median":null,"ev_ebitda_current":null,"premium_discount_pct":null},
"dcf_scenarios":{"conservative":{"implied_price":null,"growth_rate_assumed":""},"base":{"implied_price":null,"growth_rate_assumed":""},"bull":{"implied_price":null,"growth_rate_assumed":""}},
"implied_growth_in_price":"","growth_drivers":["",""],"confidence":"high|medium|low"}"""

    async def analyze(self, kg, **kwargs) -> dict:
        """Keep Gemma's valuation response compact enough to finish as JSON."""
        try:
            agent_cfg = self.config.agents.get(self.AGENT_NAME, {})
            is_local_gemma = self.llm.get_model_name().lower().startswith("gemma3:4b")
            raw = self.llm.complete(
                system_prompt=self._LOCAL_GEMMA_PROMPT if is_local_gemma else self.system_prompt,
                user_message=self._build_user_message(kg, kwargs.get("extra")),
                temperature=0.0 if is_local_gemma else getattr(agent_cfg, "temperature", 0.2),
                max_tokens=700 if is_local_gemma else getattr(agent_cfg, "max_tokens", 2000),
                response_format="json",
            )
            result = self._parse_and_validate(raw)
            if result.get("score") is None:
                raise ValueError("growth response did not include a numeric score")
            result["_model_used"] = self.llm.get_model_name()
            return result
        except Exception as exc:
            logger.error("[growth_valuation] failed: %s", exc)
            return {
                "agent": self.AGENT_NAME,
                "error": str(exc),
                "score": None,
                "_model_used": "FAILED",
            }
