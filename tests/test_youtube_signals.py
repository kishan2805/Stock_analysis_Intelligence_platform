from datetime import date

from src.youtube_signals.aggregator import aggregate
from src.youtube_signals.conviction_ranker import conviction_score, diversify, ranking_score, score
from src.youtube_signals.schemas import StockCall
from src.youtube_signals.ticker_resolver import _choose_nse_candidate, resolve
from src.youtube_signals.monitoring import ChannelStore


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


def test_rank_score_blends_channel_conviction_and_saip_rating():
    call = StockCall(video_id="one", channel_name="A", publish_date=date.today(), company_name_raw="Tata Motors", action="BUY")
    stock, _ = aggregate([resolve(call)])
    conviction = conviction_score(stock[0], 1)
    assert conviction == 100
    assert ranking_score(conviction, {"final_rating": 5}) == 80
    assert ranking_score(conviction, {"final_rating": 8}) == 92


def test_diversification_does_not_replace_the_overall_score_order():
    calls = [
        StockCall(video_id="one", channel_name="A", publish_date=date.today(), company_name_raw="Tata Motors", action="BUY"),
        StockCall(video_id="two", channel_name="A", publish_date=date.today(), company_name_raw="TCS", action="BUY"),
    ]
    stocks, _ = aggregate([resolve(call) for call in calls])
    rows = [(stock, {"final_rating": 8}, score(stock, 1, {"final_rating": 8})) for stock in stocks]
    overall = sorted(rows, key=lambda row: row[2], reverse=True)
    assert len(overall) == 2
    assert len(diversify(overall, 2, 1)) == 1


def test_known_names_in_the_reported_short_resolve_to_nse_symbols():
    names = {
        "Shyam Metallics": "SHYAMMETL.NS",
        "Divis Laboratories": "DIVISLAB.NS",
        "JSW Infra": "JSWINFRA.NS",
    }
    for name, expected in names.items():
        call = StockCall(video_id="one", channel_name="Groww", publish_date=date.today(), company_name_raw=name, action="BUY")
        assert resolve(call).ticker == expected


def test_ticker_search_requires_a_strong_unambiguous_nse_match():
    quotes = [
        {"symbol": "TATACONSUM.NS", "exchange": "NSE", "longname": "Tata Consumer Products Limited"},
        {"symbol": "TATAMOTORS.NS", "exchange": "NSE", "longname": "Tata Motors Limited"},
    ]
    assert _choose_nse_candidate("Tata Consumer", quotes) == "TATACONSUM.NS"
    assert _choose_nse_candidate("Tata", quotes) is None


def test_ticker_search_rejects_tied_candidates():
    quotes = [
        {"symbol": "ONE.NS", "exchange": "NSE", "longname": "Acme Industries Limited"},
        {"symbol": "TWO.NS", "exchange": "NSE", "longname": "Acme Industries Limited"},
    ]
    assert _choose_nse_candidate("Acme Industries", quotes) is None


def test_saved_channel_library_persists_enablement_and_removal(tmp_path):
    store = ChannelStore(str(tmp_path / "monitoring.sqlite3"))
    channel = store.add_channel("https://www.youtube.com/@example/videos", "Example")
    assert store.list_channels() == [channel]
    store.set_enabled(channel.id, False)
    assert not store.list_channels()[0].enabled
    store.delete_channel(channel.id)
    assert store.list_channels() == []
