import asyncio
from types import SimpleNamespace

from src.agents.growth_valuation_agent import GrowthValuationAgent
from src.data.knowledge_graph import KnowledgeGraph


class FakeGemma:
    def __init__(self):
        self.temperature = None
        self.max_tokens = None

    def get_model_name(self):
        return "gemma3:4b"

    def complete(self, system_prompt, user_message, temperature, max_tokens, response_format):
        self.temperature = temperature
        self.max_tokens = max_tokens
        return '{"agent":"growth_valuation_analyst","ticker":"AAPL","score":7,"valuation_verdict":"FAIR"}'


def test_gemma_growth_uses_compact_deterministic_prompt():
    llm = FakeGemma()
    config = SimpleNamespace(agents={"growth_valuation": SimpleNamespace(temperature=0.2, max_tokens=10000)})
    kg = KnowledgeGraph(ticker="AAPL", company_name="Apple Inc.", sector="Technology")

    result = asyncio.run(GrowthValuationAgent(llm, config).analyze(kg))

    assert result["score"] == 7
    assert llm.temperature == 0.0
    assert llm.max_tokens == 700
