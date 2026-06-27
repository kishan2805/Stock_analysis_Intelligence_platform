import json
from dataclasses import dataclass, field
from typing import Any

@dataclass
class KnowledgeGraph:
    # Identity
    ticker: str = ""
    exchange: str = "IN"
    company_name: str = ""
    sector: str = ""
    industry: str = ""
    fetch_timestamp: str = ""
    data_gaps: list = field(default_factory=list)

    # Fundamentals
    balance_sheet: dict = field(default_factory=dict)
    income_statement: dict = field(default_factory=dict)
    cash_flow: dict = field(default_factory=dict)
    key_ratios: dict = field(default_factory=dict)
    valuation_metrics: dict = field(default_factory=dict)

    # Ownership
    promoter_holding: list = field(default_factory=list)
    fii_holding: list = field(default_factory=list)
    dii_holding: list = field(default_factory=list)
    insider_transactions: list = field(default_factory=list)

    # News & Sentiment
    news_headlines: list = field(default_factory=list)
    analyst_ratings: dict = field(default_factory=dict)
    earnings_surprises: list = field(default_factory=list)

    # Competitive
    peers: list = field(default_factory=list)
    market_position: dict = field(default_factory=dict)

    # Governance
    governance_flags: list = field(default_factory=list)
    debt_schedule: dict = field(default_factory=dict)

    # Regime
    regime_data: dict = field(default_factory=dict)
    fii_flow_30d: float = None
    geopolitical_headlines: list = field(default_factory=list)
    macro_indicators: dict = field(default_factory=dict)

    # Session
    investment_duration_months: int = 18
    analysis_depth: str = "balanced"

    def extract(self, fields: list[str]) -> dict:
        return {f: getattr(self, f) for f in fields if hasattr(self, f)}

    def to_json(self) -> str:
        def _convert_keys(obj: Any) -> Any:
            # Recursively convert dict keys to strings so json.dumps accepts them
            if isinstance(obj, dict):
                new = {}
                for k, v in obj.items():
                    new_key = k if isinstance(k, (str, int, float, bool)) or k is None else str(k)
                    new[new_key] = _convert_keys(v)
                return new
            if isinstance(obj, (list, tuple, set)):
                return [_convert_keys(x) for x in obj]
            return obj

        converted = _convert_keys(self.__dict__)
        return json.dumps(converted, default=str, indent=2)

    @classmethod
    def from_json(cls, json_str: str) -> "KnowledgeGraph":
        data = json.loads(json_str)
        # Filter to only known fields
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
