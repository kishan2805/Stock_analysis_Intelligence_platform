from src.agents.base_agent import BaseAgent


def test_parse_and_validate_extracts_json_from_prose():
    agent = BaseAgent.__new__(BaseAgent)
    agent.AGENT_NAME = "fundamental"

    raw = 'Sure — here is the output: {"agent": "fundamental", "score": 7.5, "summary": "ok"}'
    result = agent._parse_and_validate(raw)

    assert result["agent"] == "fundamental"
    assert result["score"] == 7.5
    assert result["summary"] == "ok"
