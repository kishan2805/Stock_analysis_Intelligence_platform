from collections import Counter
from .schemas import AggregatedStock, StockCall


def aggregate(calls: list[StockCall]) -> tuple[list[AggregatedStock], list[StockCall]]:
    groups: dict[str, list[StockCall]] = {}
    unresolved = []
    for call in calls:
        if not call.ticker:
            unresolved.append(call)
        else:
            groups.setdefault(call.ticker, []).append(call)
    stocks = []
    for ticker, members in groups.items():
        prices = [c.target_price for c in members if c.target_price is not None]
        stops = [c.stop_loss for c in members if c.stop_loss is not None]
        channels = sorted({c.channel_name for c in members})
        action = Counter(c.action for c in members).most_common(1)[0][0]
        stocks.append(AggregatedStock(ticker=ticker, company_name=members[0].company_name_raw, calls=members, mention_count=len({c.video_id for c in members}), channels=channels, consensus_action=action, tp_range=(min(prices), max(prices)) if prices else None, sl_range=(min(stops), max(stops)) if stops else None, sector=next((c.sector_mentioned for c in members if c.sector_mentioned), None)))
    return stocks, unresolved
