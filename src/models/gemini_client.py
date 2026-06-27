import logging
from src.models.base_llm_client import BaseLLMClient

logger = logging.getLogger(__name__)

class GeminiClient(BaseLLMClient):
    def __init__(self, api_key: str):
        self.api_key = api_key
        self._model_name = "gemini-2.5-flash"
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self.client = genai.GenerativeModel("gemini-2.5-flash")
        except ImportError:
            logger.warning("google-generativeai not installed, GeminiClient unavailable")
            self.client = None

    def complete(self, system_prompt, user_message, temperature=0.2,
                 max_tokens=2000, response_format="json"):
        if self.client is None:
            raise RuntimeError("Gemini client not initialized")
        try:
            response = self.client.generate_content(
                f"{system_prompt}\n\n{user_message}",
                generation_config={
                    "temperature": temperature,
                    "max_output_tokens": max_tokens,
                    "response_mime_type": "application/json" if response_format == "json" else "text/plain",
                }
            )
            return response.text
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            raise

    def get_model_name(self) -> str:
        return self._model_name

    def health_check(self) -> bool:
        if self.client is None or not self.api_key:
            return False
        try:
            # Quick test call
            response = self.client.generate_content("Hi", generation_config={"max_output_tokens": 5})
            return response.text is not None
        except Exception:
            return False
