"""
src/models/ollama_client.py  — v2.5.1

FIX: Added num_ctx to Ollama options.
  Gemma 3 4B supports a large model context, but local hardware determines
  the practical request size. The configured default is 2,048 tokens.
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

# A 4B local model can accept a 10k context, but asking it to produce 10k
# tokens makes ordinary agent calls painfully slow and risks incomplete JSON.
_MODEL_MAX_OUTPUT_TOKENS: dict[str, int] = {
    "gemma3:4b": 900,
}

_MODEL_TIMEOUT_SECONDS: dict[str, int] = {
    "gemma3:4b": 180,
}


def _get_num_ctx(model_name: str) -> int:
    model_lower = (model_name or "").lower()
    for prefix, ctx in _MODEL_NUM_CTX.items():
        if model_lower.startswith(prefix):
            return ctx
    return _MODEL_NUM_CTX["default"]


def _get_max_output_tokens(model_name: str, requested: int) -> int:
    model_lower = (model_name or "").lower()
    for prefix, limit in _MODEL_MAX_OUTPUT_TOKENS.items():
        if model_lower.startswith(prefix):
            return min(requested, limit)
    return requested


def _get_timeout_seconds(model_name: str) -> int:
    model_lower = (model_name or "").lower()
    for prefix, timeout in _MODEL_TIMEOUT_SECONDS.items():
        if model_lower.startswith(prefix):
            return timeout
    return 180


class OllamaClient(BaseLLMClient):
    def __init__(self, model: str, base_url: str = "http://localhost:11434", num_ctx_override: int | None = None):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.num_ctx_override = num_ctx_override

    def complete(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        response_format: str = "json",
    ) -> str:
        num_ctx = self.num_ctx_override or _get_num_ctx(self.model)
        output_tokens = _get_max_output_tokens(self.model, max_tokens)
        timeout_seconds = _get_timeout_seconds(self.model)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_message},
            ],
            "options": {
                "temperature": temperature,
                "num_predict": output_tokens,
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
                timeout=timeout_seconds,
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
            logger.error(f"[Ollama] {self.model}: request timed out after {timeout_seconds}s")
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
