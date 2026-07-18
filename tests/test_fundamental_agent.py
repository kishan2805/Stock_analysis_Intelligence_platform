import asyncio
from types import SimpleNamespace

from src.agents.fundamental_agent import FundamentalAgent
from src.data.knowledge_graph import KnowledgeGraph


class FakeGemma:
    def __init__(self):
        self.system_prompt = ""
        self.max_tokens = None

    def get_model_name(self):
        return "gemma3:4b"

    def complete(self, system_prompt, user_message, temperature, max_tokens, response_format):
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        return '{"agent":"fundamental_analyst","ticker":"AAPL","score":7,"score_breakdown":{},"bull_points":[],"bear_points":[]}'


def test_gemma_fundamental_uses_compact_prompt_and_requires_score():
    llm = FakeGemma()
    config = SimpleNamespace(agents={"fundamental": SimpleNamespace(temperature=0.1, max_tokens=10000)})
    kg = KnowledgeGraph(ticker="AAPL", company_name="Apple Inc.", sector="Technology")

    result = asyncio.run(FundamentalAgent(llm, config).analyze(kg))

    assert result["score"] == 7
    assert "Required shape" in llm.system_prompt
    assert llm.max_tokens == 700
