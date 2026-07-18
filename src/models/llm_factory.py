import logging
import os
import requests
from src.models.base_llm_client import BaseLLMClient
from src.models.ollama_client import OllamaClient
from src.models.gemini_client import GeminiClient
from src.models.openai_client import OpenAIClient
from src.models.claude_client import ClaudeClient

logger = logging.getLogger(__name__)


def _get_available_ollama_models(base_url: str) -> set:
    """Fetch list of available models from Ollama server.

    Returns a set of model names (e.g., {"qwen3.5:0.8b", "qwen2.5-14b"}).
    Returns empty set if the server is unreachable.
    """
    try:
        resp = requests.get(f"{base_url}/api/tags", timeout=2)
        if resp.status_code == 200:
            data = resp.json()
            return {m["name"] for m in data.get("models", [])}
    except Exception:
        pass
    return set()

# Direct API models mapping
DIRECT_API_MODELS = {
    "gemini-2.5-flash": lambda cfg: GeminiClient(cfg.api_keys.gemini),
    "gpt-4o-mini":      lambda cfg: OpenAIClient(cfg.api_keys.openai),
    "claude-sonnet":    lambda cfg: ClaudeClient(cfg.api_keys.anthropic),
}

def get_llm(model_name: str, config) -> BaseLLMClient:
    """Resolve a model name to an LLM client.

    Priority:
    1. Direct API models (Gemini, OpenAI, Claude)
    2. Ollama-served models (local or cloud)
    """
    if not model_name or model_name == "null":
        raise ValueError("Model name is null or empty")

    if model_name in DIRECT_API_MODELS:
        return DIRECT_API_MODELS[model_name](config)

    # Everything else goes through Ollama
    base_url = getattr(config.ollama, "base_url", "http://localhost:11434")
    gemma_context = getattr(config.ollama, "gemma3_context_tokens", None)
    override = gemma_context if model_name.lower().startswith("gemma3:") else None
    return OllamaClient(model_name, base_url, num_ctx_override=override)


def get_llm_with_fallback(agent_name: str, config) -> BaseLLMClient:
    """Smart fallback cascade:
    1. Primary (from config) — only if it exists locally in Ollama
    2. Fallback 1 — only if it exists locally in Ollama
    3. Fallback 2 — only if it exists locally in Ollama
    4. Office model (local Ollama, safe fallback)
    5. Gemini API — only if no Ollama models available locally

    Returns the first available model with a successful health_check.
    """
    agent_cfg = config.agents.get(agent_name, {})
    base_url = getattr(config.ollama, "base_url", "http://localhost:11434")
    available_ollama = _get_available_ollama_models(base_url)

    models_to_try = []

    def _should_try_model(model_name: str, office_model: str) -> bool:
        if not model_name or model_name == "null":
            return False
        if model_name in DIRECT_API_MODELS:
            return True
        if model_name == office_model:
            return True
        return not available_ollama or model_name in available_ollama

    # Tier 1–3: Try configured models, preferring direct API models first,
    # then local Ollama models if they exist, then the office model.
    primary = getattr(agent_cfg, "model", None)
    if _should_try_model(primary, getattr(config.ollama, "office_model", "qwen2.5-14b")):
        models_to_try.append((primary, "primary"))

    fb1 = getattr(agent_cfg, "fallback", None)
    if _should_try_model(fb1, getattr(config.ollama, "office_model", "qwen2.5-14b")):
        models_to_try.append((fb1, "fallback"))

    fb2 = getattr(agent_cfg, "fallback_2", None)
    if _should_try_model(fb2, getattr(config.ollama, "office_model", "qwen2.5-14b")):
        models_to_try.append((fb2, "fallback_2"))

    # Tier 4: Always try the office model (primary fallback)
    office = getattr(config.ollama, "office_model", "qwen2.5-14b")
    if office and office != "null":
        models_to_try.append((office, "office_model"))

    # Tier 5: Gemini API — only if no Ollama models are available locally
    if not available_ollama:
        fb3 = getattr(agent_cfg, "fallback_3", None)
        if fb3 and fb3 != "null":
            models_to_try.append((fb3, "fallback_3"))
        models_to_try.append(("gemini-2.5-flash", "gemini_api"))

    last_error = None
    for model_name, tier in models_to_try:
        try:
            client = get_llm(model_name, config)
            if client.health_check():
                logger.info(f"[LLM Factory] {agent_name} -> {model_name} ({tier})")
                return client
            else:
                logger.warning(f"[LLM Factory] {model_name} ({tier}) health_check failed for {agent_name}")
        except Exception as e:
            logger.warning(f"[LLM Factory] {model_name} ({tier}) error for {agent_name}: {e}")
            last_error = e

    raise RuntimeError(f"No LLM available for agent '{agent_name}'. Check your API keys and Ollama server.")
