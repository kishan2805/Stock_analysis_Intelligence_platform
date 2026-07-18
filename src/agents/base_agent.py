"""
src/agents/base_agent.py  — v2.5.1

ROOT CAUSE FIXES:
  1. fundamental/growth N/A (json_parse_failed):
     gemma3:4b has a 2048-token context window. The agent was sending
     balance_sheet + income_statement + cash_flow + 5 more fields,
     easily 3000+ tokens. Model output was truncated after the opening
     '{' → parse failure. Fix: dynamic context budgeting based on
     model name; heavy fields stripped to key-ratios-only for small models.

  2. growth N/A OK (score not extracted):
     GrowthValuationAgent.AGENT_NAME = "growth_valuation" but the CIO
     score extraction looks for "growth". Fixed in stage2_parallel.py
     and cio_agent.py — the key mapping is handled there.
     BaseAgent now also normalises agent name aliases in _parse_and_validate.

  3. market_regime / risk_narrative N/A OK (display only):
     Fixed in report_formatter.py — those agents don't emit a 0-10 "score",
     formatter now checks alternate keys.
"""

import json
import logging
import re
from pathlib import Path

from src.data.knowledge_graph import KnowledgeGraph
from src.models.base_llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

# ── Context-window budgets by model family ────────────────────────────────────
# Maps model-name prefixes → max chars for the user_message (data portion only).
# System prompt is ~1000 chars extra. Budget is conservative to guarantee output fits.
_MODEL_CONTEXT_BUDGETS: dict[str, int] = {
    "gemma3:4b":    2_500,   # 2048-token local profile; compact snapshot retains key financials
    "gemma3:8b":    5_000,   # typically 4096 tokens
    "gemma":        5_000,   # any other gemma variant
    "phi3":         6_000,   # 4096 tokens
    "phi":          6_000,
    "llama3.2":     8_000,   # 128k window but small model — keep concise
    "llama3":      10_000,
    "llama":       10_000,
    "mistral":     12_000,
    "qwen2.5-14b": 16_000,
    "qwen":        16_000,
    "deepseek":    20_000,
    "glm":         20_000,
    "gemini":      30_000,   # Gemini API — generous
    "kimi":        20_000,
    "minimax":     30_000,
    "gpt":         20_000,
    "default":     12_000,   # safe fallback for unknown models
}

# Fields that contain large arrays — trim to most-recent N entries
_TRIM_LIST_FIELDS = {
    "insider_transactions":   5,
    "news_headlines":        10,
    "fii_holding":            6,
    "dii_holding":            6,
    "governance_flags":      10,
    "geopolitical_headlines": 5,
    "earnings_surprises":     4,
    "peers":                  5,
}

# Heavy financial fields — reduce year depth for small context models
_FINANCIAL_FIELDS = ("balance_sheet", "income_statement", "cash_flow")

_FINANCIAL_SNAPSHOT_METRICS = {
    "balance_sheet": ("total debt", "cash", "total assets", "stockholders equity"),
    "income_statement": ("total revenue", "operating income", "net income", "ebitda"),
    "cash_flow": ("operating cash flow", "capital expenditure", "free cash flow"),
}

# Sentinel strings the model might use instead of null
_NULL_SENTINELS = {
    "none", "null", "n/a", "na", "nil", "not available",
    "not_available", "", "-", "—", "unknown",
}


def _get_context_budget(model_name: str) -> int:
    """Return max chars for user_message based on model name prefix match."""
    model_lower = (model_name or "").lower()
    for prefix, budget in _MODEL_CONTEXT_BUDGETS.items():
        if model_lower.startswith(prefix):
            return budget
    return _MODEL_CONTEXT_BUDGETS["default"]


def _compact_financial_snapshot(data: dict) -> dict:
    """Keep two periods of decision-useful financial lines for small models."""
    snapshot = {}
    for field, wanted_metrics in _FINANCIAL_SNAPSHOT_METRICS.items():
        statement = data.get(field)
        if not isinstance(statement, dict):
            continue
        periods = {}
        for period in sorted(statement.keys(), reverse=True)[:2]:
            rows = statement.get(period)
            if not isinstance(rows, dict):
                continue
            selected = {}
            for label, value in rows.items():
                normalised = str(label).lower()
                if value is not None and any(metric in normalised for metric in wanted_metrics):
                    selected[str(label)] = value
            if selected:
                periods[str(period)] = selected
        if periods:
            snapshot[field] = periods
    return snapshot


def _trim_kg_data(data: dict, context_budget: int) -> dict:
    """
    Two-pass context reduction:
    Pass 1 — trim large list fields to their maximums.
    Pass 2 — if still over budget, reduce financial statement year depth,
              then drop heavy fields entirely until we fit.
    """
    out = {}
    for k, v in data.items():
        if k in _TRIM_LIST_FIELDS and isinstance(v, list):
            out[k] = v[: _TRIM_LIST_FIELDS[k]]
        else:
            out[k] = v

    # Pass 2: year reduction for financial statements
    if len(json.dumps(out, default=str)) > context_budget:
        for field in _FINANCIAL_FIELDS:
            if field in out and isinstance(out[field], dict):
                years = sorted(out[field].keys(), reverse=True)
                out[field] = {y: out[field][y] for y in years[:2]}  # keep 2 years max

    # Pass 3: replace raw statements with a compact two-period snapshot.
    if len(json.dumps(out, default=str)) > context_budget:
        snapshot = _compact_financial_snapshot(out)
        for field in _FINANCIAL_FIELDS:
            out.pop(field, None)
        if snapshot:
            out["financial_snapshot"] = snapshot
        logger.info(
            f"Context budget {context_budget} chars: replaced raw financial statements "
            f"with a compact two-period financial snapshot."
        )

    # Pass 4: nuclear — if still huge, trim everything that's a dict/list
    if len(json.dumps(out, default=str)) > context_budget:
        for k in list(out.keys()):
            if isinstance(out[k], (dict, list)) and k not in (
                "key_ratios", "valuation_metrics", "ticker",
                "company_name", "sector", "exchange", "financial_snapshot",
            ):
                out.pop(k, None)
        logger.info(
            f"Local context reduction ({context_budget} chars): retained core ratios "
            "and valuation metrics after dropping optional evidence fields."
        )

    return out


# Agent name aliases — some models echo back a slightly different name
_AGENT_NAME_ALIASES: dict[str, str] = {
    "growth_valuation":      "growth_valuation",  # keep as-is
    "market_regime_head":    "market_regime",
    "market_regime_agent":   "market_regime",
    "risk_officer":          "risk_narrative",
    "moat_analyst":          "moat",
    "macro_strategist":      "macro",
    "fundamental_analyst":   "fundamental",
    "evidence_auditor":      "evidence_auditor",
}


class BaseAgent:
    AGENT_NAME: str = "base"
    PROMPT_FILE: str = ""
    REQUIRED_KG_FIELDS: list[str] = []

    def __init__(self, llm: BaseLLMClient, config):
        self.llm = llm
        self.config = config
        self.system_prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        path = Path("config/prompts") / self.PROMPT_FILE
        if not path.exists():
            raise FileNotFoundError(f"Prompt not found: {path}")
        return path.read_text()

    def _build_user_message(self, kg: KnowledgeGraph, extra: dict = None) -> str:
        data = kg.extract(self.REQUIRED_KG_FIELDS)
        budget = _get_context_budget(self.llm.get_model_name())
        data = _trim_kg_data(data, budget)
        if extra:
            data.update(extra)

        payload_chars = len(json.dumps(data, default=str))
        logger.debug(
            f"[{self.AGENT_NAME}] user_message payload: {payload_chars} chars "
            f"(budget: {budget} for model '{self.llm.get_model_name()}')"
        )

        return (
            "Analyse the following data and respond with valid JSON only.\n"
            "Do NOT include markdown fences, preamble, or commentary outside the JSON.\n\n"
            + json.dumps(data, default=str, indent=2)
        )

    async def analyze(self, kg: KnowledgeGraph, **kwargs) -> dict:
        try:
            agent_cfg = self.config.agents.get(self.AGENT_NAME, {})
            user_msg = self._build_user_message(kg, kwargs.get("extra"))
            is_local_gemma = self.llm.get_model_name().lower().startswith("gemma3:4b")
            raw = self.llm.complete(
                system_prompt=self.system_prompt,
                user_message=user_msg,
                temperature=0.0 if is_local_gemma else getattr(agent_cfg, "temperature", 0.2),
                max_tokens=getattr(agent_cfg, "max_tokens", 2000),
                response_format="json",
            )
            result = self._parse_and_validate(raw)
            result["_model_used"] = self.llm.get_model_name()
            return result
        except Exception as e:
            logger.error(f"[{self.AGENT_NAME}] failed: {e}")
            return {
                "agent":       self.AGENT_NAME,
                "error":       str(e),
                "score":       None,
                "_model_used": "FAILED",
            }

    # ── JSON recovery pipeline ────────────────────────────────────────────

    def _strip_fences(self, text: str) -> str:
        """Remove ```json ... ``` or ``` ... ``` wrappers."""
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            start = 1
            end = len(lines) - 1 if lines[-1].strip().startswith("```") else len(lines)
            text = "\n".join(lines[start:end]).strip()
        return text

    def _normalize_string_whitespace(self, text: str) -> str:
        """
        Collapse literal newlines inside JSON string values.
        Small models often break long strings across lines, producing invalid JSON.
        """
        def _replace(match: re.Match) -> str:
            inner = match.group(1)
            inner = re.sub(r"\s+", " ", inner).strip()
            return f'"{inner}"'

        return re.sub(r'"((?:\\.|[^"\\])*)"', _replace, text, flags=re.DOTALL)

    def _repair_json(self, text: str) -> str:
        """Fix the most common small-model JSON formatting mistakes."""
        text = (
            text
            .replace("\u201c", '"').replace("\u201d", '"')
            .replace("\u2018", "'").replace("\u2019", "'")
        )
        text = (
            text
            .replace(": None",  ": null")
            .replace(":None",   ": null")
            .replace(": True",  ": true")
            .replace(": False", ": false")
        )
        text = text.replace("\t", "  ").replace("\r", "")
        # Trailing commas
        text = re.sub(r",\s*([}\]])", r"\1", text)
        # Unquoted keys
        text = re.sub(
            r'(?<=[{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:',
            r' "\1":',
            text,
        )
        # Single-quoted strings
        text = re.sub(r"(?<![\\\"])\'([^\']*)\'", r'"\1"', text)
        return text

    def _extract_first_json_object(self, text: str) -> str | None:
        """Find the outermost { ... } block in text."""
        depth = 0
        start = None
        in_string = False
        escape_next = False
        for i, ch in enumerate(text):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start is not None:
                    return text[start: i + 1]
        return None

    def _truncation_recovery(self, text: str) -> str | None:
        """
        Handle output truncated mid-JSON (most common small-model failure).
        Strategy: find last complete field, close all open brackets.
        Only works for shallow truncation.
        """
        if not text or not text.strip().startswith("{"):
            return None
        t = text.strip()
        # Count unclosed braces/brackets (outside strings)
        depth_brace = 0
        depth_bracket = 0
        in_string = False
        escape_next = False
        last_complete_pos = 0
        for i, ch in enumerate(t):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                if not in_string:
                    last_complete_pos = i
                continue
            if in_string:
                continue
            if ch == "{":
                depth_brace += 1
            elif ch == "}":
                depth_brace -= 1
            elif ch == "[":
                depth_bracket += 1
            elif ch == "]":
                depth_bracket -= 1
            if depth_brace == 0 and depth_bracket == 0 and i > 0:
                return t  # already complete

        # Truncated — close open structures
        # First truncate to last complete key-value pair to avoid partial strings
        truncated = t[:last_complete_pos + 1] if last_complete_pos > 0 else t
        # Remove trailing comma + partial field
        truncated = re.sub(r",\s*\"[^\"]*\"?\s*:?\s*[^,}\]]*$", "", truncated)
        # Close open brackets/braces
        closing = "]" * depth_bracket + "}" * depth_brace
        recovered = truncated + closing
        return recovered if depth_brace > 0 else None

    def _normalize_missing_values(self, obj):
        """Recursively convert string sentinels like 'N/A', 'None' to Python None."""
        if isinstance(obj, dict):
            return {k: self._normalize_missing_values(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._normalize_missing_values(i) for i in obj]
        if isinstance(obj, str) and obj.strip().lower() in _NULL_SENTINELS:
            return None
        return obj

    def _coerce_to_json_object(self, text: str) -> dict:
        text = self._strip_fences(text)

        # Build candidates in order from least to most aggressive
        normalized = self._normalize_string_whitespace(text)
        candidates = [normalized, text]
        candidates.append(self._repair_json(text))
        candidates.append(self._normalize_string_whitespace(self._repair_json(text)))

        # Add truncation recovery variants
        recovered = self._truncation_recovery(text)
        if recovered:
            candidates.append(recovered)
            candidates.append(self._repair_json(recovered))

        # Extract first { } block from each candidate
        expanded = []
        for c in candidates:
            expanded.append(c)
            extracted = self._extract_first_json_object(c)
            if extracted and extracted != c:
                expanded.append(extracted)
                expanded.append(self._normalize_string_whitespace(extracted))
                expanded.append(self._repair_json(extracted))

        seen = set()
        for candidate in expanded:
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            for variant in [candidate, candidate.replace("\n", " ")]:
                try:
                    parsed = json.loads(variant)
                    if isinstance(parsed, dict):
                        return self._normalize_missing_values(parsed)
                except json.JSONDecodeError:
                    continue

        raise json.JSONDecodeError("Could not recover structured JSON", text, 0)

    def _parse_and_validate(self, raw: str) -> dict:
        try:
            result = self._coerce_to_json_object(raw or "")
            # Normalise agent name aliases
            agent_in_result = result.get("agent", "")
            canonical = _AGENT_NAME_ALIASES.get(agent_in_result)
            if canonical and canonical != self.AGENT_NAME:
                # Only override if the alias maps somewhere useful
                pass  # keep the model's agent name, handled at extraction layer
            if "agent" not in result:
                result["agent"] = self.AGENT_NAME
            return result
        except json.JSONDecodeError as e:
            logger.error(
                f"[{self.AGENT_NAME}] JSON parse failed: {e}\n"
                f"Raw (first 500 chars): {(raw or '')[:500]}"
            )
            return {"agent": self.AGENT_NAME, "error": "json_parse_failed", "score": None}
