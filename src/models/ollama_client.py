"""
src/models/ollama_client.py  — v2.5.1

FIX: Added num_ctx to Ollama options.
gemma3:4b defaults to 2048 token context. Without num_ctx in the request,
Ollama uses whatever the model was loaded with — often 2048.
We now set num_ctx explicitly based on the model name so the model
actually processes the full prompt we send. For gemma3:4b this is kept
at 2048 (hardware limit). For larger models we set higher values.

The real fix for gemma3:4b is the context budget in base_agent.py
which ensures we never send a prompt that exceeds 2048 tokens.
This num_ctx setting is a belt-and-suspenders guard.
"""

import httpx
import logging
from src.models.base_llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

# Model-specific context window sizes (in tokens)
# Set conservatively — Ollama needs VRAM to hold the full context.
_MODEL_NUM_CTX: dict[str, int] = {
    "gemma3:4b":    2048,
    "gemma3:8b":    4096,
    "gemma":        4096,
    "phi3":         4096,
    "phi":          4096,
    "llama3.2":     8192,
    "llama3":       8192,
    "llama":        8192,
    "mistral":      8192,
    "qwen2.5-14b": 16384,
    "qwen2.5":      8192,
    "qwen":         8192,
    "deepseek":    32768,
    "glm":         32768,
    "kimi":        32768,
    "minimax":     32768,
    "default":      8192,
}


def _get_num_ctx(model_name: str) -> int:
    model_lower = (model_name or "").lower()
    for prefix, ctx in _MODEL_NUM_CTX.items():
        if model_lower.startswith(prefix):
            return ctx
    return _MODEL_NUM_CTX["default"]


class OllamaClient(BaseLLMClient):
    def __init__(self, model: str, base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")

    def complete(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        response_format: str = "json",
    ) -> str:
        num_ctx = _get_num_ctx(self.model)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
                "num_ctx":     num_ctx,       # explicitly set context window
            },
            "stream": False,
        }
        if response_format == "json":
            payload["format"] = "json"

        try:
            r = httpx.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=180,  # increased from 120 — large models need more time
            )
            r.raise_for_status()
            content = r.json()["message"]["content"]
            logger.debug(
                f"[Ollama] {self.model}: "
                f"prompt~{len(system_prompt)+len(user_message)} chars "
                f"→ response {len(content)} chars (num_ctx={num_ctx})"
            )
            return content
        except httpx.TimeoutException:
            logger.error(f"[Ollama] {self.model}: request timed out after 180s")
            raise
        except Exception as e:
            logger.error(f"[Ollama] {self.model}: {e}")
            raise

    def get_model_name(self) -> str:
        return self.model

    def health_check(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            if r.status_code != 200:
                return False
            models = r.json().get("models", [])
            return any(
                m.get("name", "").startswith(self.model)
                or self.model in m.get("name", "")
                for m in models
            )
        except Exception:
            return False
