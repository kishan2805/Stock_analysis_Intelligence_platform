from src.agents.base_agent import BaseAgent


def test_base_agent_recovers_multiline_string_content():
    agent = BaseAgent.__new__(BaseAgent)
    agent.AGENT_NAME = "dummy"

    raw = '''
    {
      "agent": "dummy",
      "summary": "Apple maintains a premium pricing
      strategy and strong ecosystem",
      "score": 7
    }
    '''

    result = agent._parse_and_validate(raw)

    assert result["agent"] == "dummy"
    assert result["score"] == 7
    assert result["summary"] == "Apple maintains a premium pricing strategy and strong ecosystem"
