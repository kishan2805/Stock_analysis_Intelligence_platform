import json
import logging
from pathlib import Path

from src.models.base_llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

# Verdict thresholds
_VERDICT_BANDS = [
    (9.0, "STRONG BUY",  "HIGH"),
    (7.5, "BUY",         "MODERATE"),
    (6.0, "ACCUMULATE",  "MODERATE"),
    (4.5, "HOLD",        "LOW"),
    (3.0, "REDUCE",      "LOW"),
    (0.0, "AVOID",       "LOW"),
]

# Position sizing by verdict × uncertainty
_POSITION_SIZE = {
    ("STRONG BUY",  "LOW"):    "5-7%",
    ("BUY",         "LOW"):    "3-5%",
    ("BUY",         "MEDIUM"): "2-3%",
    ("BUY",         "HIGH"):   "1-2%",
    ("ACCUMULATE",  "LOW"):    "1-2%",
    ("ACCUMULATE",  "MEDIUM"): "0.5-1%",
    ("HOLD",        "LOW"):    "0%",
}


def _safe(val, default=5.0):
    try:
        f = float(val)
        return f if 0 <= f <= 10 else default
    except (TypeError, ValueError):
        return default


def _verdict(score: float) -> tuple[str, str]:
    for threshold, v, c in _VERDICT_BANDS:
        if score >= threshold:
            return v, c
    return "AVOID", "LOW"


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

    # ── public entry point ────────────────────────────────────────────────

    async def judge(
        self,
        audited_bundle: dict,
        debate_result: dict,
        det_risk: dict,
        config_weights,
        ticker: str,
        company_name: str,
        duration_months: int,
    ) -> dict:
        # Step 1 — compute the formula deterministically in Python
        skeleton = self._compute_scores(
            audited_bundle, debate_result, det_risk,
            config_weights, ticker, company_name, duration_months,
        )

        # Step 2 — ask the LLM only for narrative fields
        try:
            narrative = await self._get_narrative(skeleton, audited_bundle, debate_result)
            skeleton.update(narrative)
        except Exception as e:
            logger.error(f"[cio] narrative LLM call failed: {e}")
            skeleton["five_point_summary"] = [
                "CIO narrative generation failed. "
                "Review the agent reports above for details."
            ]

        skeleton["_model_used"] = self.llm.get_model_name()
        return skeleton

    # ── deterministic scoring ─────────────────────────────────────────────

    def _compute_scores(
        self,
        audited_bundle,
        debate_result,
        det_risk,
        config_weights,
        ticker,
        company_name,
        duration_months,
    ) -> dict:
        validated = audited_bundle.get("validated_reports", {})

        fund   = _safe(validated.get("fundamental",   {}).get("score"))
        macro  = _safe(validated.get("macro",          {}).get("score"))
        moat   = _safe(validated.get("moat",           {}).get("moat_score"))
        growth = _safe(validated.get("growth",         {}).get("score"))
        risk_s = _safe(det_risk.get("det_risk_score"))
        regime = _safe(
            validated.get("market_regime", {}).get("sector_regime_multiplier", 0),
            default=0.0,
        )
        confidence_adj = float(audited_bundle.get("confidence_adjustment") or 0)
        reliability    = float(audited_bundle.get("reliability_score") or 5.0)

        # Weights — support both dict and namespace
        def _w(name, fallback):
            try:
                return float(getattr(config_weights, name, config_weights.get(name, fallback)))
            except Exception:
                return fallback

        w_fund   = _w("fundamental", 0.25)
        w_macro  = _w("macro",       0.20)
        w_moat   = _w("moat",        0.15)
        w_growth = _w("growth",      0.20)
        w_risk   = _w("risk",        0.20)

        # Step 1 — weighted raw
        risk_contribution = (10 - risk_s) * w_risk
        weighted_raw = round(
            fund   * w_fund  +
            macro  * w_macro +
            moat   * w_moat  +
            growth * w_growth +
            risk_contribution,
            3,
        )

        # Step 2 — confidence penalty (from Evidence Auditor, always ≤ 0)
        after_confidence = round(weighted_raw + confidence_adj, 3)

        # Step 3 — debate adjustment (capped at ±0.75)
        bull_c = _safe(debate_result.get("bull_conviction"), 5.0)
        bear_c = _safe(debate_result.get("bear_conviction"), 5.0)
        debate_avg = (bull_c + (10 - bear_c)) / 2
        raw_debate_adj = max(-0.75, min(0.75, (debate_avg - after_confidence) * 0.1))
        debate_adj = round(raw_debate_adj, 3)
        after_debate = round(after_confidence + debate_adj, 3)

        # Step 4 — regime multiplier
        regime_clamped = max(-1.5, min(1.5, regime))
        final = round(max(0.0, min(10.0, after_debate + regime_clamped)), 2)

        verdict, conviction = _verdict(final)

        # Uncertainty: spread across agent scores
        agent_scores_list = [fund, macro, moat, growth, 10 - risk_s]
        spread = max(agent_scores_list) - min(agent_scores_list)
        uncertainty = "HIGH" if spread > 3.0 else ("MEDIUM" if spread > 1.5 else "LOW")

        # High-uncertainty from debate
        if debate_result.get("high_uncertainty"):
            uncertainty = "HIGH"

        # Composite sub-scores
        business_quality  = round(moat * 0.35 + fund * 0.35 + (10 - risk_s) * 0.30, 1)
        investment_quality = round(growth * 0.40 + final * 0.35 + macro * 0.25, 1)

        # Position size
        pos_key = (verdict, uncertainty)
        position_size = _POSITION_SIZE.get(pos_key, "0%")
        if uncertainty == "HIGH" and verdict in ("BUY", "STRONG BUY"):
            position_size = "1-2%"  # forced reduction

        return {
            "agent":          "cio",
            "ticker":         ticker,
            "company_name":   company_name,
            "investment_horizon_months": duration_months,

            "scores": {
                "business_quality":  business_quality,
                "investment_quality": investment_quality,
                "valuation_score":   round(growth * 0.5 + (10 - risk_s) * 0.5, 1),
                "macro_risk":        round(10 - macro, 1),
                "execution_risk":    round(risk_s, 1),
                "catalyst_score":    round(growth * 0.6 + macro * 0.4, 1),
            },

            "final_rating":  final,
            "verdict":       verdict,
            "conviction":    conviction,
            "uncertainty":   uncertainty,

            "score_calculation": {
                "agent_scores":        {"fundamental": fund, "macro": macro,
                                        "moat": moat, "growth": growth,
                                        "det_risk": risk_s},
                "weights":             {"fundamental": w_fund, "macro": w_macro,
                                        "moat": w_moat, "growth": w_growth, "risk": w_risk},
                "weighted_raw":        weighted_raw,
                "confidence_penalty":  round(confidence_adj, 3),
                "debate_adjustment":   debate_adj,
                "regime_multiplier":   round(regime_clamped, 3),
                "final":               final,
            },

            "recommended_position_size":  position_size,
            "recommended_holding_period": f"{duration_months}–{duration_months * 2} months",
            "recommended_hold_months":    {"min": duration_months, "max": duration_months * 2},
            "reliability_score":          reliability,

            # Narrative fields — filled by LLM in step 2
            "expected_cagr":            None,
            "five_point_summary":       [],
            "buy_below_price":          None,
            "next_catalyst_to_watch":   None,
            "thesis_invalidating_risk": None,
            "debate_decisive_argument": None,
            "geopolitical_regime_flags": [],
        }

    # ── LLM narrative call ────────────────────────────────────────────────

    async def _get_narrative(self, skeleton: dict, audited_bundle: dict, debate_result: dict) -> dict:
        """
        Ask the LLM only for qualitative fields.
        The formula numbers are already computed — we send them as context
        so the LLM can refer to them in the summary without re-doing math.
        """
        agent_cfg = self.config.agents.get(self.AGENT_NAME, {})
        validated = audited_bundle.get("validated_reports", {})

        # Compact context for the LLM — just the key numbers and latest debate
        context = {
            "ticker":         skeleton["ticker"],
            "company_name":   skeleton["company_name"],
            "final_rating":   skeleton["final_rating"],
            "verdict":        skeleton["verdict"],
            "score_calculation": skeleton["score_calculation"],
            "agent_summaries": {
                name: {
                    "bull_points": report.get("bull_points", []),
                    "bear_points": report.get("bear_points", []),
                    "score":       report.get("score") or report.get("moat_score"),
                }
                for name, report in validated.items()
                if isinstance(report, dict)
            },
            "debate_closing": [
                t for t in (debate_result.get("transcript") or [])
                if t.get("round", 0) >= 6
            ],
            "geopolitical_regime": validated.get("market_regime", {}).get("geopolitical_chains", []),
            "immediate_risk_flags": audited_bundle.get("validated_reports", {})
                                    .get("risk_narrative", {})
                                    .get("ranked_risks", [])[:3],
        }

        prompt = (
            "The formula scoring is already complete — do NOT recalculate any numbers.\n"
            "Based on the analysis context provided, output ONLY a JSON object with these fields:\n"
            '{\n'
            '  "expected_cagr": "<e.g. 15-20%>",\n'
            '  "five_point_summary": ["1. ...", "2. ...", "3. ...", "4. ...", "5. ..."],\n'
            '  "buy_below_price": "<price or null>",\n'
            '  "next_catalyst_to_watch": "<event>",\n'
            '  "thesis_invalidating_risk": "<single biggest risk>",\n'
            '  "debate_decisive_argument": "<which side and what point>",\n'
            '  "geopolitical_regime_flags": ["<flag 1>", "<flag 2>"]\n'
            '}\n'
            "Each five_point_summary entry must cite a specific number from the reports.\n"
            "No markdown, no preamble, respond with JSON only."
        )

        raw = self.llm.complete(
            system_prompt=self.system_prompt + "\n\n" + prompt,
            user_message=json.dumps(context, default=str, indent=2),
            temperature=getattr(agent_cfg, "temperature", 0.1),
            max_tokens=1500,
            response_format="json",
        )

        # Parse with the same recovery logic as BaseAgent
        from src.agents.base_agent import BaseAgent
        tmp = BaseAgent.__new__(BaseAgent)
        tmp.AGENT_NAME = "cio_narrative"
        parsed = tmp._parse_and_validate(raw)

        return {
            "expected_cagr":            parsed.get("expected_cagr"),
            "five_point_summary":       parsed.get("five_point_summary", []),
            "buy_below_price":          parsed.get("buy_below_price"),
            "next_catalyst_to_watch":   parsed.get("next_catalyst_to_watch"),
            "thesis_invalidating_risk": parsed.get("thesis_invalidating_risk"),
            "debate_decisive_argument": parsed.get("debate_decisive_argument"),
            "geopolitical_regime_flags": parsed.get("geopolitical_regime_flags", []),
        }

    # ── misc ──────────────────────────────────────────────────────────────

    def _normalize_missing_values(self, value):
        if isinstance(value, dict):
            return {k: self._normalize_missing_values(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._normalize_missing_values(i) for i in value]
        if isinstance(value, str) and value.strip().lower() in {
            "none", "null", "n/a", "na", "nil", "not available"
        }:
            return None
        return value
