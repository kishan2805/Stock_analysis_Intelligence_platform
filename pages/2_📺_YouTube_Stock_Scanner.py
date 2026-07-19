import asyncio
import csv
from io import StringIO
from pathlib import Path
import sys
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
from src.utils.config_loader import load_config
from src.youtube_signals import YouTubeScannerService

st.set_page_config(page_title="YouTube Stock Scanner", layout="wide")
st.title("📺 YouTube Stock Scanner")
st.caption("Controlled beta — public videos only. Final rank score = 60% channel conviction + 40% HFIP rating. The shortlist is shown first; the CSV contains every deep-dived stock from the scan.")
with st.form("youtube_scan"):
    urls_text = st.text_area("Video or channel URLs (one per line)", placeholder="https://www.youtube.com/watch?v=...\nhttps://www.youtube.com/@Channel/videos")
    c1, c2, c3 = st.columns(3)
    lookback = c1.selectbox("Channel lookback", [7, 14, 30], index=1)
    max_videos = c2.slider("Videos per channel", 1, 10, 4)
    top_n = c3.slider("Ranked stocks", 1, 6, 5)
    skip_debate = st.checkbox("Skip HFIP bull/bear debate (faster)", value=False)
    submitted = st.form_submit_button("Scan public videos", type="primary")

if submitted:
    urls = [line.strip() for line in urls_text.splitlines() if line.strip()]
    if not urls:
        st.error("Add at least one public YouTube video or channel URL.")
    else:
        status = st.status("Starting scan...", expanded=True)
        def progress(message): status.write(message)
        try:
            result = asyncio.run(YouTubeScannerService(load_config(), progress).scan(
                urls, lookback, max_videos, top_n, skip_debate=skip_debate
            ))
            st.session_state["youtube_result"] = result
            status.update(label="Scan complete", state="complete")
        except Exception as exc:
            status.update(label="Scan failed", state="error")
            st.error(str(exc))

result = st.session_state.get("youtube_result")
if result:
    reports = result["reports"]
    all_reports = result.get("all_reports", reports)
    if not reports: st.warning("No resolved, explicit Indian-stock calls were found.")
    for report in reports:
        with st.container(border=True):
            st.subheader(f"#{report.rank} {report.company_name} ({report.ticker}) — rank score {report.ranking_score}/100")
            a, b, c = st.columns(3)
            a.metric("Channel entry", report.suggested_buy_price or "Not stated")
            b.metric("Channel target", report.target_price or "Not stated")
            c.metric("Channel stop loss", report.stop_loss or "Not stated")
            st.caption(f"Channel conviction: {report.conviction_score}/100 · {report.mention_count} video(s) · {', '.join(report.source_channels)} · HFIP {report.hfip_execution_mode} rating: {report.hfip_rating or 'Unavailable'}/10 · HFIP model: {report.hfip_model or 'Unavailable'}")
            if report.data_quality == "Complete":
                st.success("Data quality: Complete")
            else:
                st.warning("Data quality: Degraded — " + "; ".join(report.data_quality_notes))
            st.write("**Buy-side evidence:** " + report.buy_side_view)
            st.write("**Risk view:** " + report.sell_side_view)
            st.caption(report.channel_price_note)
            st.caption("The main analyser defaults to balanced analysis; its rating may differ from this quick screen.")
            if st.button(f"Open full analysis: {report.ticker}", key=report.ticker):
                st.session_state["prefill_ticker"] = report.ticker
                st.switch_page("app.py")
    with st.expander("All resolved stocks"):
        report_by_ticker = {report.ticker: report for report in all_reports}
        st.dataframe([{
            "Overall rank": report_by_ticker.get(s.ticker).rank if s.ticker in report_by_ticker else "Not deep-dived",
            "Ticker": s.ticker,
            "Company": s.company_name,
            "Rank score": report_by_ticker.get(s.ticker).ranking_score if s.ticker in report_by_ticker else None,
            "Conviction": report_by_ticker.get(s.ticker).conviction_score if s.ticker in report_by_ticker else None,
            "HFIP rating": report_by_ticker.get(s.ticker).hfip_rating if s.ticker in report_by_ticker else None,
            "Videos": s.mention_count,
            "Channels": ", ".join(s.channels),
            "Action": s.consensus_action,
        } for s in result["stocks"]], width="stretch")
    with st.expander("Unresolved company names"):
        if not result["unresolved"]:
            st.caption("None")
        for call in result["unresolved"]:
            left, right = st.columns([2, 1])
            left.write(f"**{call.company_name_raw}** — {call.channel_name} ({call.action})")
            ticker = right.text_input("Confirmed NSE ticker", key=f"ticker-{call.video_id}-{call.company_name_raw}", placeholder="e.g. ABC.NS")
            if right.button("Open main analyser", key=f"open-{call.video_id}-{call.company_name_raw}", disabled=not ticker.strip()):
                st.session_state["prefill_ticker"] = ticker.strip().upper()
                st.switch_page("app.py")
    if all_reports or result["unresolved"]:
        buffer = StringIO(); writer = csv.writer(buffer); writer.writerow(["rank", "ticker", "company", "resolution_status", "rank_score", "conviction", "hfip_rating", "channel_entry", "channel_target", "channel_stop", "channels", "channel_action", "video_ids"])
        for r in all_reports:
            writer.writerow([r.rank, r.ticker, r.company_name, "Resolved", r.ranking_score, r.conviction_score, r.hfip_rating, r.suggested_buy_price, r.target_price, r.stop_loss, "; ".join(r.source_channels), "", ""])
        unresolved_by_name = {}
        for call in result["unresolved"]:
            key = call.company_name_raw.strip().casefold()
            item = unresolved_by_name.setdefault(key, {"company": call.company_name_raw, "channels": set(), "actions": set(), "video_ids": set()})
            item["channels"].add(call.channel_name)
            item["actions"].add(call.action)
            item["video_ids"].add(call.video_id)
        for item in unresolved_by_name.values():
            writer.writerow(["", "", item["company"], "Unresolved — confirm NSE ticker", "", "", "", "", "", "", "; ".join(sorted(item["channels"])), "; ".join(sorted(item["actions"])), "; ".join(sorted(item["video_ids"]))])
        st.download_button("Export all ranked stocks CSV", buffer.getvalue(), "youtube_stock_scan.csv", "text/csv")
    if result["errors"]:
        with st.expander("Skipped videos and scan issues"):
            for error in result["errors"]: st.write("• " + error)

with st.expander("Planned channel monitoring", expanded=False):
    st.info("Later: choose channels, schedule a daily scan of their newest video, and configure delivery. Telegram/WhatsApp delivery is not connected in this release.")
