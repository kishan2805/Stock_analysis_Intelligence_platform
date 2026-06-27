import logging
from src.models.base_llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

class ClaudeClient(BaseLLMClient):
    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20241022"):
        self.api_key = api_key
        self.model = model
        try:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
        except ImportError:
            logger.warning("anthropic not installed, ClaudeClient unavailable")
            self.client = None

    def complete(self, system_prompt, user_message, temperature=0.2,
                 max_tokens=2000, response_format="json"):
        if self.client is None:
            raise RuntimeError("Claude client not initialized")
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}]
            )
            return resp.content[0].text
        except Exception as e:
            logger.error(f"Claude API error: {e}")
            raise

    def get_model_name(self) -> str:
        return self.model

    def health_check(self) -> bool:
        if self.client is None or not self.api_key:
            return False
        try:
            self.client.messages.create(
                model=self.model,
                max_tokens=5,
                messages=[{"role": "user", "content": "Hi"}]
            )
            return True
        except Exception:
            return False
