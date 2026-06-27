from types import SimpleNamespace

import src.models.llm_factory as llm_factory


class DummyClient:
    def __init__(self, model_name):
        self.model_name = model_name

    def health_check(self):
        return True

    def get_model_name(self):
        return self.model_name


def test_direct_api_model_is_tried_before_local_fallback(monkeypatch):
    config = SimpleNamespace(
        agents={
            "fundamental": SimpleNamespace(
                model="claude-sonnet",
                fallback="gpt-4o-mini",
                fallback_2="qwen2.5-14b",
            )
        },
        ollama=SimpleNamespace(base_url="http://localhost:11434", office_model="gemma3:4b"),
        api_keys=SimpleNamespace(gemini="x", openai="x", anthropic="y"),
    )

    attempted = []

    def fake_get_llm(model_name, cfg):
        attempted.append(model_name)
        return DummyClient(model_name)

    monkeypatch.setattr(llm_factory, "get_llm", fake_get_llm)
    monkeypatch.setattr(llm_factory, "_get_available_ollama_models", lambda base_url: set())

    client = llm_factory.get_llm_with_fallback("fundamental", config)

    assert client.get_model_name() == "claude-sonnet"
    assert attempted[0] == "claude-sonnet"
