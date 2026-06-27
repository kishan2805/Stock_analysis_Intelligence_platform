import json, logging, re
from pathlib import Path
from src.data.knowledge_graph import KnowledgeGraph
from src.models.base_llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

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
        if extra:
            data.update(extra)
        return f"Analyse the following data:\n\n{json.dumps(data, default=str, indent=2)}"

    async def analyze(self, kg: KnowledgeGraph, **kwargs) -> dict:
        try:
            agent_cfg = self.config.agents.get(self.AGENT_NAME, {})
            user_msg = self._build_user_message(kg, kwargs.get("extra"))
            raw = self.llm.complete(
                system_prompt=self.system_prompt,
                user_message=user_msg,
                temperature=getattr(agent_cfg, "temperature", 0.2),
                max_tokens=getattr(agent_cfg, "max_tokens", 2000),
                response_format="json"
            )
            result = self._parse_and_validate(raw)
            result["_model_used"] = self.llm.get_model_name()
            return result
        except Exception as e:
            logger.error(f"[{self.AGENT_NAME}] failed: {e}")
            return {"agent": self.AGENT_NAME, "error": str(e), "score": None, "_model_used": "FAILED"}

    def _repair_json(self, text: str) -> str:
        # Common model output issues: unquoted keys, single quotes, trailing commas, Python literals
        repaired = text.replace("\u201c", '"').replace("\u201d", '"').replace("\u2018", "'").replace("\u2019", "'")
        repaired = repaired.replace("None", "null").replace("True", "true").replace("False", "false")
        repaired = repaired.replace("\t", " ").replace("\r", " ")
        repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
        repaired = re.sub(r"(?<=\{|,)(\s*)([A-Za-z_][A-Za-z0-9_]*)\s*:", r"\1\"\2\":", repaired)
        repaired = re.sub(r"'([^']*)'", r'"\1"', repaired)
        return repaired

    def _extract_json_candidate(self, text: str) -> str | None:
        stack = []
        start_idx = None
        for idx, ch in enumerate(text):
            if ch == '{':
                if start_idx is None:
                    start_idx = idx
                stack.append(ch)
            elif ch == '}' and stack:
                stack.pop()
                if not stack and start_idx is not None:
                    return text[start_idx:idx + 1]
        return None

    def _parse_and_validate(self, raw: str) -> dict:
        try:
            clean = raw.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:-1]) if len(lines) > 2 else lines[0].replace("```json", "").replace("```", "")

            try:
                result = json.loads(clean)
            except json.JSONDecodeError:
                candidate = self._extract_json_candidate(clean)
                if candidate:
                    try:
                        result = json.loads(candidate)
                    except json.JSONDecodeError:
                        result = json.loads(self._repair_json(candidate))
                else:
                    result = json.loads(self._repair_json(clean))

            if "agent" not in result:
                result["agent"] = self.AGENT_NAME
            return result
        except json.JSONDecodeError as e:
            logger.error(f"[{self.AGENT_NAME}] JSON parse failed: {e}\nRaw: {raw[:200]}")
            return {"agent": self.AGENT_NAME, "error": "json_parse_failed", "score": None}
