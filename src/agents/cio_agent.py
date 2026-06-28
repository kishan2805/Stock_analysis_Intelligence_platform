"""
src/agents/cio_agent.py  — v2.5.1

FIX: growth score was always read as 5.0 (default) because:
  - stage2_parallel used pipeline key "growth"
  - but evidence_auditor passed reports through under the model's "agent" value
    which could be "growth_valuation_analyst" or "growth_valuation"
  - CIO looked for validated_reports["growth"] → found nothing → default 5.0

Fix: _safe_get_score() tries multiple key variants for each agent slot.
All other logic unchanged.
"""

import json
import logging
from pathlib import Path

from src.models.base_llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

_VERDICT_BANDS = [
    (9.0, "STRONG BUY",  "HIGH"),
    (7.5, "BUY",         "MODERATE"),
    (6.0, "ACCUMULATE",  "MODERATE"),
    (4.5, "HOLD",        "LOW"),
    (3.0, "REDUCE",      "LOW"),
    (0.0, "AVOID",       "LOW"),
]

_POSITION_SIZE = {
    ("STRONG BUY",  "LOW"):    "5-7%",
    ("BUY",         "LOW"):    "3-5%",
    ("BUY",         "MEDIUM"): "2-3%",
    ("BUY",         "HIGH"):   "1-2%",
    ("ACCUMULATE",  "LOW"):    "1-2%",
    ("ACCUMULATE",  "MEDIUM"): "0.5-1%",
    ("HOLD",        "LOW"):    "0%",
}

# Score key candidates for each agent slot — tries in order, first non-None wins
_SCORE_KEY_MAP: dict[str, list[str]] = {
    "fundamental":   ["score"],
    "macro":         ["score"],
    "moat":          ["moat_score", "score"],
    "growth":        ["score"],
    "market_regime": [],   # no investment score — uses sector_regime_multiplier
    "risk_narrative": [],  # no investment score — det_risk_score comes from det_risk directly
}

# Agent name aliases — what the model may echo vs pipeline key
_AGENT_ALIASES: dict[str, str] = {
    "growth_valuation":        "growth",
    "growth_valuation_analyst":"growth",
    "market_regime_head":      "market_regime",
    "market_regime_agent":     "market_regime",
    "risk_officer":            "risk_narrative",
    "moat_analyst":            "moat",
    "macro_strategist":        "macro",
    "fundamental_analyst":     "fundamental",
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


def _find_report(reports: dict, pipeline_key: str) -> dict:
    """
    Find an agent report in the validated_reports dict by pipeline key,
    trying aliases if the primary key is missing or empty.
    """
    # Direct hit
    r = reports.get(pipeline_key)
    if r and isinstance(r, dict):
        return r

    # Search all reports for one whose "agent" field matches known aliases
    aliases_for_key = {
        alias for alias, canonical in _AGENT_ALIASES.items()
        if canonical == pipeline_key
    }
    aliases_for_key.add(pipeline_key)

    for k, v in reports.items():
        if not isinstance(v, dict):
            continue
        agent_field = v.get("agent", "")
        pipeline_field = v.get("_pipeline_key", "")
        if k in aliases_for_key or agent_field in aliases_for_key or pipeline_field == pipeline_key:
            return v

    return {}


def _extract_score(reports: dict, pipeline_key: str, default: float = 5.0) -> float:
    """Extract a 0-10 score for an agent, trying all known key variants."""
    report = _find_report(reports, pipeline_key)
    if not report:
        return default

    score_keys = _SCORE_KEY_MAP.get(pipeline_key, ["score"])
    for key in score_keys:
        val = report.get(key)
        if val is not None:
            return _safe(val, default)

    # Last resort: generic "score" key
    val = report.get("score")
    if val is not None:
        return _safe(val, default)

    return default


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
        skeleton = self._compute_scores(
            audited_bundle, debate_result, det_risk,
            config_weights, ticker, company_name, duration_months,
        )
        try:
            narrative = await self._get_narrative(skeleton, audited_bundle, debate_result)
            skeleton.update(narrative)
        except Exception as e:
            logger.error(f"[cio] narrative LLM call failed: {e}")
            skeleton["five_point_summary"] = [
                "CIO narrative generation failed. Review the agent reports above for details."
            ]

        skeleton["_model_used"] = self.llm.get_model_name()
        return skeleton

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

        # Extract scores using alias-aware lookup
        fund   = _extract_score(validated, "fundamental")
        macro  = _extract_score(validated, "macro")
        moat   = _extract_score(validated, "moat")
        growth = _extract_score(validated, "growth")
        risk_s = _safe(det_risk.get("det_risk_score"))

        # Regime multiplier from market_regime report
        regime_report = _find_report(validated, "market_regime")
        regime = _safe(
            regime_report.get("sector_regime_multiplier", 0),
            default=0.0,
        )

        confidence_adj = float(audited_bundle.get("confidence_adjustment") or 0)
        reliability    = float(audited_bundle.get("reliability_score") or 5.0)

        logger.info(
            f"[CIO] Scores — fund={fund} macro={macro} moat={moat} "
            f"growth={growth} risk={risk_s} regime={regime} "
            f"conf_adj={confidence_adj}"
        )

        def _w(name, fallback):
            try:
                return float(
                    getattr(config_weights, name, None)
                    if not isinstance(config_weights, dict)
                    else config_weights.get(name, fallback)
                )
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

        # Step 2 — confidence penalty (always ≤ 0)
        after_confidence = round(weighted_raw + confidence_adj, 3)

        # Step 3 — debate adjustment (capped at ±0.75)
        bull_c = _safe(debate_result.get("bull_conviction"), 5.0)
        bear_c = _safe(debate_result.get("bear_conviction"), 5.0)
        debate_avg = (bull_c + (10 - bear_c)) / 2
        debate_adj = round(max(-0.75, min(0.75, (debate_avg - after_confidence) * 0.1)), 3)
        after_debate = round(after_confidence + debate_adj, 3)

        # Step 4 — regime multiplier
        regime_clamped = max(-1.5, min(1.5, regime))
        final = round(max(0.0, min(10.0, after_debate + regime_clamped)), 2)

        verdict, conviction = _verdict(final)

        agent_scores_list = [fund, macro, moat, growth, 10 - risk_s]
        spread = max(agent_scores_list) - min(agent_scores_list)
        uncertainty = "HIGH" if spread > 3.0 else ("MEDIUM" if spread > 1.5 else "LOW")
        if debate_result.get("high_uncertainty"):
            uncertainty = "HIGH"

        business_quality   = round(moat * 0.35 + fund * 0.35 + (10 - risk_s) * 0.30, 1)
        investment_quality = round(growth * 0.40 + final * 0.35 + macro * 0.25, 1)

        pos_key = (verdict, uncertainty)
        position_size = _POSITION_SIZE.get(pos_key, "0%")
        if uncertainty == "HIGH" and verdict in ("BUY", "STRONG BUY"):
            position_size = "1-2%"

        return {
            "agent":          "cio",
            "ticker":         ticker,
            "company_name":   company_name,
            "investment_horizon_months": duration_months,

            "scores": {
                "business_quality":   business_quality,
                "investment_quality": investment_quality,
                "valuation_score":    round(growth * 0.5 + (10 - risk_s) * 0.5, 1),
                "macro_risk":         round(10 - macro, 1),
                "execution_risk":     round(risk_s, 1),
                "catalyst_score":     round(growth * 0.6 + macro * 0.4, 1),
            },

            "final_rating":  final,
            "verdict":       verdict,
            "conviction":    conviction,
            "uncertainty":   uncertainty,

            "score_calculation": {
                "agent_scores":       {
                    "fundamental": fund,
                    "macro":       macro,
                    "moat":        moat,
                    "growth":      growth,
                    "det_risk":    risk_s,
                },
                "weights":            {
                    "fundamental": w_fund,
                    "macro":       w_macro,
                    "moat":        w_moat,
                    "growth":      w_growth,
                    "risk":        w_risk,
                },
                "weighted_raw":       weighted_raw,
                "confidence_penalty": round(confidence_adj, 3),
                "debate_adjustment":  debate_adj,
                "regime_multiplier":  round(regime_clamped, 3),
                "final":              final,
            },

            "recommended_position_size":  position_size,
            "recommended_holding_period": f"{duration_months}–{duration_months * 2} months",
            "recommended_hold_months":    {"min": duration_months, "max": duration_months * 2},
            "reliability_score":          reliability,

            "expected_cagr":            None,
            "five_point_summary":       [],
            "buy_below_price":          None,
            "next_catalyst_to_watch":   None,
            "thesis_invalidating_risk": None,
            "debate_decisive_argument": None,
            "geopolitical_regime_flags": [],
        }

    async def _get_narrative(
        self, skeleton: dict, audited_bundle: dict, debate_result: dict
    ) -> dict:
        agent_cfg = self.config.agents.get(self.AGENT_NAME, {})
        validated = audited_bundle.get("validated_reports", {})

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
                    "score": (
                        report.get("score")
                        or report.get("moat_score")
                        or report.get("sector_regime_multiplier")
                        or report.get("det_risk_score")
                    ),
                }
                for name, report in validated.items()
                if isinstance(report, dict)
            },
            "debate_closing": [
                t for t in (debate_result.get("transcript") or [])
                if t.get("round", 0) >= 6
            ],
            "geopolitical_regime": _find_report(validated, "market_regime").get(
                "geopolitical_chains", []
            ),
            "immediate_risk_flags": _find_report(validated, "risk_narrative").get(
                "ranked_risks", []
            )[:3],
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
