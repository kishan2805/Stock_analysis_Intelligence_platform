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
        api_keys=SimpleNamespace(gemini="x", openai="x", anthropic="y", nvidia="z"),
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


def test_configured_fallbacks_are_tried_in_order(monkeypatch):
    config = SimpleNamespace(
        agents={
            "fundamental": SimpleNamespace(
                model="nvidia/nvidia-nemotron-nano-9b-v2",
                fallback="first-fallback",
                fallback_2="second-fallback",
                fallback_3="third-fallback",
                fallback_4="gemini-2.5-flash",
            )
        },
        ollama=SimpleNamespace(base_url="http://localhost:11434", office_model="office-model"),
        api_keys=SimpleNamespace(gemini="x", openai="x", anthropic="y", nvidia="z"),
    )

    attempted = []

    def fake_get_llm(model_name, cfg):
        attempted.append(model_name)
        client = DummyClient(model_name)
        client.health_check = lambda: model_name == "second-fallback"
        return client

    monkeypatch.setattr(llm_factory, "get_llm", fake_get_llm)
    monkeypatch.setattr(llm_factory, "_get_available_ollama_models", lambda base_url: set())

    client = llm_factory.get_llm_with_fallback("fundamental", config)

    assert client.get_model_name() == "second-fallback"
    assert attempted == [
        "nvidia/nvidia-nemotron-nano-9b-v2",
        "first-fallback",
        "second-fallback",
    ]


def test_nvidia_hosted_deepseek_uses_nvidia_client(monkeypatch):
    config = SimpleNamespace(
        ollama=SimpleNamespace(base_url="http://localhost:11434"),
        api_keys=SimpleNamespace(gemini="x", openai="x", anthropic="y", nvidia="nvidia-key"),
    )
    captured = {}

    class FakeNvidiaClient(DummyClient):
        def __init__(self, api_key, model):
            captured["api_key"] = api_key
            captured["model"] = model
            super().__init__(model)

    monkeypatch.setattr(llm_factory, "NvidiaClient", FakeNvidiaClient)

    client = llm_factory.get_llm("deepseek-ai/deepseek-v4-pro", config)

    assert captured == {
        "api_key": "nvidia-key",
        "model": "deepseek-ai/deepseek-v4-pro",
    }
    assert client.get_model_name() == "deepseek-ai/deepseek-v4-pro"
