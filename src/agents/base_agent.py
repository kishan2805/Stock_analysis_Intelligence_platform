import json, logging
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

    def _parse_and_validate(self, raw: str) -> dict:
        try:
            clean = raw.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:-1]) if len(lines) > 2 else lines[0].replace("```json", "").replace("```", "")

            # Try direct parse first
            try:
                result = json.loads(clean)
            except json.JSONDecodeError:
                # Try to recover a JSON object embedded in surrounding prose
                start = clean.find("{")
                end = clean.rfind("}")
                if start != -1 and end != -1 and end > start:
                    candidate = clean[start:end + 1]
                    result = json.loads(candidate)
                else:
                    raise

            if "agent" not in result:
                result["agent"] = self.AGENT_NAME
            return result
        except json.JSONDecodeError as e:
            logger.error(f"[{self.AGENT_NAME}] JSON parse failed: {e}\nRaw: {raw[:200]}")
            return {"agent": self.AGENT_NAME, "error": "json_parse_failed", "score": None}
