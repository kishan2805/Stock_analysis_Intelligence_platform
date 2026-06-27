import logging
from src.models.base_llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

class OpenAIClient(BaseLLMClient):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model = model
        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=api_key)
        except ImportError:
            logger.warning("openai not installed, OpenAIClient unavailable")
            self.client = None

    def complete(self, system_prompt, user_message, temperature=0.2,
                 max_tokens=2000, response_format="json"):
        if self.client is None:
            raise RuntimeError("OpenAI client not initialized")
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"} if response_format == "json" else None
            )
            return resp.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise

    def get_model_name(self) -> str:
        return self.model

    def health_check(self) -> bool:
        if self.client is None or not self.api_key:
            return False
        try:
            self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Hi"}],
                max_tokens=5
            )
            return True
        except Exception:
            return False
