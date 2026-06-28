import json
import logging
import re
from pathlib import Path

from src.data.knowledge_graph import KnowledgeGraph
from src.models.base_llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

# Fields that contain large arrays — trim to most-recent N entries
_TRIM_LIST_FIELDS = {
    "insider_transactions": 10,
    "news_headlines":       15,
    "fii_holding":          10,
    "governance_flags":     20,
    "geopolitical_headlines": 10,
}

# Maximum chars for the user_message before we start summarising financials
_MAX_USER_MSG_CHARS = 12_000


def _trim_kg_data(data: dict) -> dict:
    """Trim large list fields and drop the raw financial statements
    if the total payload would be too large for the model."""
    out = {}
    for k, v in data.items():
        if k in _TRIM_LIST_FIELDS and isinstance(v, list):
            out[k] = v[: _TRIM_LIST_FIELDS[k]]
        else:
            out[k] = v

    # Summarise financial statements if payload is still huge
    payload_size = len(json.dumps(out, default=str))
    if payload_size > _MAX_USER_MSG_CHARS:
        for heavy in ("balance_sheet", "income_statement", "cash_flow"):
            if heavy in out and isinstance(out[heavy], dict):
                years = sorted(out[heavy].keys(), reverse=True)
                out[heavy] = {y: out[heavy][y] for y in years[:3]}  # keep latest 3 years

    return out


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
        data = _trim_kg_data(data)
        if extra:
            data.update(extra)
        return (
            "Analyse the following data and respond with valid JSON only.\n"
            "Do NOT include markdown fences, preamble, or commentary outside the JSON.\n\n"
            + json.dumps(data, default=str, indent=2)
        )

    async def analyze(self, kg: KnowledgeGraph, **kwargs) -> dict:
        try:
            agent_cfg = self.config.agents.get(self.AGENT_NAME, {})
            user_msg = self._build_user_message(kg, kwargs.get("extra"))
            raw = self.llm.complete(
                system_prompt=self.system_prompt,
                user_message=user_msg,
                temperature=getattr(agent_cfg, "temperature", 0.2),
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
            # drop first and last line if they are fence lines
            start = 1
            end = len(lines) - 1 if lines[-1].strip().startswith("```") else len(lines)
            text = "\n".join(lines[start:end]).strip()
        return text

    def _normalize_string_whitespace(self, text: str) -> str:
        """
        Collapse literal newlines / extra spaces inside JSON string values.
        gemma3 (and other small models) sometimes break long string values
        across lines, creating invalid JSON like:
            "evidence": "Apple maintains a premium pricing
            strategy..."
        This regex finds every quoted string and collapses internal whitespace.
        """
        def _replace(match: re.Match) -> str:
            inner = match.group(1)
            inner = re.sub(r"[\r\n]+", " ", inner)
            inner = re.sub(r"[ \t]{2,}", " ", inner)
            return f'"{inner}"'

        # Match quoted strings, respecting backslash escapes
        return re.sub(r'"((?:\\.|[^"\\])*)"', _replace, text, flags=re.DOTALL)

    def _repair_json(self, text: str) -> str:
        """Fix the most common small-model JSON formatting mistakes."""
        # Smart quotes → ASCII quotes
        text = (
            text
            .replace("\u201c", '"').replace("\u201d", '"')
            .replace("\u2018", "'").replace("\u2019", "'")
        )
        # Python literals → JSON literals
        text = (
            text
            .replace(": None", ": null")
            .replace(":None",  ": null")
            .replace(": True",  ": true")
            .replace(": False", ": false")
        )
        # Tabs and CR
        text = text.replace("\t", "  ").replace("\r", "")
        # Trailing commas before } or ]
        text = re.sub(r",\s*([}\]])", r"\1", text)
        # Unquoted keys  {key: ...}  →  {"key": ...}
        text = re.sub(
            r'(?<=[{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:',
            r' "\1":',
            text,
        )
        # Single-quoted strings (only if not already inside double-quotes)
        text = re.sub(r"(?<![\\])'([^']*)'", r'"\1"', text)
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

    def _normalize_missing_values(self, obj):
        """Recursively convert string sentinels like 'N/A', 'None' to Python None."""
        SENTINELS = {"none", "null", "n/a", "na", "nil", "not available", "not_available", ""}
        if isinstance(obj, dict):
            return {k: self._normalize_missing_values(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._normalize_missing_values(i) for i in obj]
        if isinstance(obj, str) and obj.strip().lower() in SENTINELS:
            return None
        return obj

    def _coerce_to_json_object(self, text: str) -> dict:
        text = self._strip_fences(text)

        # Try candidates in order from least to most aggressive repair
        candidates = [
            text,
            self._normalize_string_whitespace(text),
            self._repair_json(text),
            self._normalize_string_whitespace(self._repair_json(text)),
        ]

        # Also try extracting just the first { } block for each candidate
        expanded = []
        for c in candidates:
            expanded.append(c)
            extracted = self._extract_first_json_object(c)
            if extracted and extracted != c:
                expanded.append(extracted)
                expanded.append(self._normalize_string_whitespace(extracted))

        for candidate in expanded:
            if not candidate:
                continue
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
            if "agent" not in result:
                result["agent"] = self.AGENT_NAME
            return result
        except json.JSONDecodeError as e:
            logger.error(
                f"[{self.AGENT_NAME}] JSON parse failed: {e}\n"
                f"Raw (first 300 chars): {(raw or '')[:300]}"
            )
            return {"agent": self.AGENT_NAME, "error": "json_parse_failed", "score": None}
