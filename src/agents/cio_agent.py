import json, logging
from pathlib import Path
from src.models.base_llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

class CIOAgent:
    AGENT_NAME = "cio"
    PROMPT_FILE = "cio.md"

    def __init__(self, llm: BaseLLMClient, config):
        self.llm = llm
        self.config = config
        self.system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        path = Path("config/prompts") / self.PROMPT_FILE
        if not path.exists():
            raise FileNotFoundError(f"Prompt not found: {path}")
        return path.read_text()

    async def judge(self, audited_bundle: dict, debate_result: dict,
                    det_risk: dict, config_weights: dict,
                    ticker: str, company_name: str,
                    duration_months: int) -> dict:
        try:
            agent_cfg = self.config.agents.get(self.AGENT_NAME, {})

            validated = audited_bundle.get("validated_reports", {})

            user_msg = json.dumps({
                "ticker": ticker,
                "company_name": company_name,
                "investment_horizon_months": duration_months,
                "weights": config_weights,
                "agent_scores": {
                    "fundamental": validated.get("fundamental", {}).get("score"),
                    "macro": validated.get("macro", {}).get("score"),
                    "moat": validated.get("moat", {}).get("moat_score"),
                    "growth": validated.get("growth", {}).get("score"),
                    "det_risk_score": det_risk.get("det_risk_score"),
                },
                "regime_multiplier": validated.get("market_regime", {}).get("sector_regime_multiplier", 0),
                "reliability_score": audited_bundle.get("reliability_score"),
                "confidence_adjustment": audited_bundle.get("confidence_adjustment", 0),
                "bull_conviction": debate_result.get("bull_conviction"),
                "bear_conviction": debate_result.get("bear_conviction"),
                "debate_transcript_summary": debate_result.get("transcript", [])[-4:] if debate_result.get("transcript") else [],
                "full_reports": validated,
            }, default=str, indent=2)

            raw = self.llm.complete(
                system_prompt=self.system_prompt,
                user_message=f"Make your CIO judgment based on:\n\n{user_msg}",
                temperature=getattr(agent_cfg, "temperature", 0.1),
                max_tokens=getattr(agent_cfg, "max_tokens", 3000),
                response_format="json"
            )

            result = self._parse_and_validate(raw)
            result["_model_used"] = self.llm.get_model_name()
            return result
        except Exception as e:
            logger.error(f"[cio] failed: {e}")
            return self._fallback_cio_output(ticker, company_name, duration_months, audited_bundle, det_risk)

    def _parse_and_validate(self, raw: str) -> dict:
        try:
            clean = raw.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:-1]) if len(lines) > 2 else lines[0].replace("```json", "").replace("```", "")
            result = json.loads(clean)
            if "agent" not in result:
                result["agent"] = self.AGENT_NAME
            return result
        except json.JSONDecodeError as e:
            logger.error(f"[cio] JSON parse failed: {e}")
            return {"agent": self.AGENT_NAME, "error": "json_parse_failed"}

    def _fallback_cio_output(self, ticker, company_name, duration, audited, det_risk):
        # Deterministic fallback when CIO LLM fails
        scores = audited.get("validated_reports", {})
        fund = scores.get("fundamental", {}).get("score", 5) or 5
        macro = scores.get("macro", {}).get("score", 5) or 5
        moat = scores.get("moat", {}).get("moat_score", 5) or 5
        growth = scores.get("growth", {}).get("score", 5) or 5
        risk = det_risk.get("det_risk_score", 5) or 5

        raw_score = (fund * 0.25 + macro * 0.20 + moat * 0.15 + 
                     growth * 0.20 + (10 - risk) * 0.20)
        adj = audited.get("confidence_adjustment", 0) or 0
        final = max(0, min(10, raw_score + adj))

        verdict = "HOLD"
        if final >= 9.0: verdict = "STRONG BUY"
        elif final >= 7.5: verdict = "BUY"
        elif final >= 6.0: verdict = "ACCUMULATE"
        elif final >= 4.5: verdict = "HOLD"
        elif final >= 3.0: verdict = "REDUCE"
        else: verdict = "AVOID"

        return {
            "agent": "cio",
            "ticker": ticker,
            "company_name": company_name,
            "analysis_date": "",
            "investment_horizon_months": duration,
            "scores": {
                "business_quality": round((moat * 0.35 + fund * 0.35 + (10-risk) * 0.30), 1),
                "investment_quality": round((growth * 0.40 + 5 * 0.35 + macro * 0.25), 1),
                "valuation_score": round(growth, 1),
                "macro_risk": round(10 - macro, 1),
                "execution_risk": round(risk, 1),
                "catalyst_score": 5.0,
            },
            "final_rating": round(final, 1),
            "verdict": verdict,
            "conviction": "LOW",
            "uncertainty": "HIGH",
            "expected_cagr": "N/A",
            "recommended_position_size": "0%",
            "recommended_holding_period": "N/A",
            "score_calculation": {
                "weighted_raw": round(raw_score, 2),
                "confidence_penalty": adj,
                "debate_adjustment": 0,
                "regime_multiplier": 0,
                "final": round(final, 2),
            },
            "five_point_summary": ["CIO analysis failed — deterministic fallback used."],
            "geopolitical_regime_flags": [],
            "recommended_hold_months": {"min": duration, "max": duration * 2},
            "buy_below_price": "N/A",
            "next_catalyst_to_watch": "N/A",
            "thesis_invalidating_risk": "Analysis incomplete due to LLM failure",
            "debate_decisive_argument": "N/A",
            "_model_used": "DETERMINISTIC_FALLBACK",
            "error": "LLM fallback to deterministic scoring"
        }
