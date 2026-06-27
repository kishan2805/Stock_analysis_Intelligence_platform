from abc import ABC, abstractmethod

class BaseLLMClient(ABC):
    @abstractmethod
    def complete(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.2,
        max_tokens: int = 2000,
        response_format: str = "json"
    ) -> str:
        ...

    @abstractmethod
    def get_model_name(self) -> str:
        ...

    @abstractmethod
    def health_check(self) -> bool:
        ...
