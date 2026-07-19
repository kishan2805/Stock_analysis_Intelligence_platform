import logging

from src.models.base_llm_client import BaseLLMClient

logger = logging.getLogger(__name__)


class NvidiaClient(BaseLLMClient):
    """NVIDIA NIM client using NVIDIA's OpenAI-compatible chat API."""

    BASE_URL = "https://integrate.api.nvidia.com/v1"

    def __init__(
        self,
        api_key: str,
        model: str = "nvidia/nvidia-nemotron-nano-9b-v2",
    ):
        self.api_key = api_key
        self.model = model
        try:
            from openai import OpenAI

            self.client = OpenAI(base_url=self.BASE_URL, api_key=api_key)
        except ImportError:
            logger.warning("openai not installed, NvidiaClient unavailable")
            self.client = None

    def complete(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        response_format: str = "json",
    ) -> str:
        if self.client is None:
            raise RuntimeError("NVIDIA client not initialized")

        # SAIP agents require machine-readable structured output.  Nemotron's
        # reasoning mode is enabled by default, so disable it for this workflow.
        system_message = "/no_think\n" + system_prompt
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"}
                if response_format == "json"
                else None,
            )
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError("NVIDIA API returned an empty response")
            return content
        except Exception as exc:
            logger.error("NVIDIA API error: %s", exc)
            raise

    def get_model_name(self) -> str:
        return self.model

    def health_check(self) -> bool:
        if self.client is None or not self.api_key:
            return False
        try:
            self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "/no_think"},
                    {"role": "user", "content": "Reply with OK."},
                ],
                temperature=0,
                max_tokens=8,
            )
            return True
        except Exception as exc:
            logger.warning("NVIDIA health check failed: %s", exc)
            return False
