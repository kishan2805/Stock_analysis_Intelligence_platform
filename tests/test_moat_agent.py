import asyncio
from types import SimpleNamespace

from src.agents.moat_agent import MoatAgent
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
        return (
            '{"agent":"moat_analyst","ticker":"AAPL","moat_score":7,'
            '"moat_category":"WIDE","moat_sources":{},"peer_comparison":[],'
            '"moat_durability":"5yr+","moat_trend":"stable","confidence":"medium"}'
        )


def test_gemma_moat_uses_compact_prompt_and_output_budget():
    llm = FakeGemma()
    config = SimpleNamespace(agents={"moat": SimpleNamespace(temperature=0.2, max_tokens=10000)})
    kg = KnowledgeGraph(ticker="AAPL", company_name="Apple Inc.", sector="Technology")

    result = asyncio.run(MoatAgent(llm, config).analyze(kg))

    assert result["moat_score"] == 7
    assert "<=12 words" in llm.system_prompt
    assert llm.max_tokens == 700
