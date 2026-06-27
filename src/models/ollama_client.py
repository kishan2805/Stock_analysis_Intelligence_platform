import httpx
import logging
from src.models.base_llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

class OllamaClient(BaseLLMClient):
    def __init__(self, model: str, base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    def complete(self, system_prompt, user_message, temperature=0.2,
                 max_tokens=2000, response_format="json"):
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "stream": False,
            "format": "json" if response_format == "json" else None
        }
        try:
            r = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=120)
            r.raise_for_status()
            return r.json()["message"]["content"]
        except Exception as e:
            logger.error(f"Ollama error for {self.model}: {e}")
            raise

    def get_model_name(self) -> str:
        return self.model

    def health_check(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            if r.status_code != 200:
                return False
            models = r.json().get("models", [])
            return any(m.get("name", "").startswith(self.model) or self.model in m.get("name", "") for m in models)
        except Exception:
            return False
