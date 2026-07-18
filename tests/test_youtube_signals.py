from datetime import date

from src.youtube_signals.aggregator import aggregate
from src.youtube_signals.conviction_ranker import diversify, score
from src.youtube_signals.schemas import StockCall
from src.youtube_signals.ticker_resolver import resolve


def test_aggregates_resolved_calls_and_retains_unresolved_calls():
    calls = [
        StockCall(video_id="one", channel_name="A", publish_date=date.today(), company_name_raw="Tata Motors", action="BUY", target_price=900),
        StockCall(video_id="two", channel_name="B", publish_date=date.today(), company_name_raw="Tata Motors", action="BUY", target_price=920),
        StockCall(video_id="three", channel_name="A", publish_date=date.today(), company_name_raw="Not A Listed Company", action="WATCH"),
    ]
    stocks, unresolved = aggregate([resolve(call) for call in calls])
    assert stocks[0].ticker == "TATAMOTORS.NS"
    assert stocks[0].mention_count == 2
    assert len(unresolved) == 1


def test_ranking_is_bounded_and_sector_cap_is_applied():
    call = StockCall(video_id="one", channel_name="A", publish_date=date.today(), company_name_raw="Tata Motors", action="BUY")
    stock, _ = aggregate([resolve(call)])
    value = score(stock[0], 1, {"final_rating": 8})
    assert 0 <= value <= 100
    assert len(diversify([(stock[0], {"final_rating": 8}, value)], 1, 1)) == 1


def test_known_names_in_the_reported_short_resolve_to_nse_symbols():
    names = {
        "Shyam Metallics": "SHYAMMETL.NS",
        "Divis Laboratories": "DIVISLAB.NS",
        "JSW Infra": "JSWINFRA.NS",
    }
    for name, expected in names.items():
        call = StockCall(video_id="one", channel_name="Groww", publish_date=date.today(), company_name_raw=name, action="BUY")
        assert resolve(call).ticker == expected
