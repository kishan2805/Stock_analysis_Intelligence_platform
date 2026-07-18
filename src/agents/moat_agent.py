import logging

from src.agents.base_agent import BaseAgent

logger = logging.getLogger(__name__)

class MoatAgent(BaseAgent):
    AGENT_NAME = "moat"
    PROMPT_FILE = "moat_agent.md"
    REQUIRED_KG_FIELDS = [
        "ticker", "company_name", "sector", "industry",
        "key_ratios", "valuation_metrics",
        "peers", "market_position",
    ]

    _LOCAL_GEMMA_PROMPT = """You are a concise competitive-moat analyst. Use only the supplied data; do not invent facts.
Return ONLY one valid JSON object, with no markdown. Keep every evidence string <=12 words and return at most 2 peers.
Required shape:
{"agent":"moat_analyst","ticker":"<ticker>","moat_score":0-10,
"moat_category":"WIDE|NARROW|NONE",
"moat_sources":{"brand_strength":{"score":0-2,"evidence":"..."},
"distribution_network":{"score":0-2,"evidence":"..."},
"switching_costs":{"score":0-2,"evidence":"..."},
"cost_advantage":{"score":0-2,"evidence":"..."},
"technology_ip":{"score":0-2,"evidence":"..."},
"market_share":{"score":0-2,"evidence":"..."}},
"peer_comparison":[{"peer":"<ticker>","moat_vs_subject":"stronger|similar|weaker","key_difference":"..."}],
"moat_durability":"5yr+|3-5yr|<3yr","moat_trend":"widening|stable|narrowing","confidence":"high|medium|low"}
If evidence is unavailable, use score 0 and evidence "No supporting data"."""

    async def analyze(self, kg, **kwargs) -> dict:
        """Use a small schema for Gemma 4B so JSON fits its local output budget."""
        try:
            agent_cfg = self.config.agents.get(self.AGENT_NAME, {})
            user_msg = self._build_user_message(kg, kwargs.get("extra"))
            is_local_gemma = self.llm.get_model_name().lower().startswith("gemma3:4b")
            raw = self.llm.complete(
                system_prompt=self._LOCAL_GEMMA_PROMPT if is_local_gemma else self.system_prompt,
                user_message=user_msg,
                temperature=0.0 if is_local_gemma else getattr(agent_cfg, "temperature", 0.2),
                max_tokens=700 if is_local_gemma else getattr(agent_cfg, "max_tokens", 2000),
                response_format="json",
            )
            result = self._parse_and_validate(raw)
            result["_model_used"] = self.llm.get_model_name()
            return result
        except Exception as exc:
            logger.error("[moat] failed: %s", exc)
            return {
                "agent": self.AGENT_NAME,
                "error": str(exc),
                "score": None,
                "_model_used": "FAILED",
            }
