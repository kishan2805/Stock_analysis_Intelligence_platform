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
st.caption("Controlled beta — public videos only. Channel levels are source evidence, not investment advice.")
with st.form("youtube_scan"):
    urls_text = st.text_area("Video or channel URLs (one per line)", placeholder="https://www.youtube.com/watch?v=...\nhttps://www.youtube.com/@Channel/videos")
    c1, c2, c3 = st.columns(3)
    lookback = c1.selectbox("Channel lookback", [7, 14, 30], index=1)
    max_videos = c2.slider("Videos per channel", 1, 10, 4)
    top_n = c3.slider("Ranked stocks", 1, 6, 5)
    submitted = st.form_submit_button("Scan public videos", type="primary")

if submitted:
    urls = [line.strip() for line in urls_text.splitlines() if line.strip()]
    if not urls:
        st.error("Add at least one public YouTube video or channel URL.")
    else:
        status = st.status("Starting scan...", expanded=True)
        def progress(message): status.write(message)
        try:
            result = asyncio.run(YouTubeScannerService(load_config(), progress).scan(urls, lookback, max_videos, top_n))
            st.session_state["youtube_result"] = result
            status.update(label="Scan complete", state="complete")
        except Exception as exc:
            status.update(label="Scan failed", state="error")
            st.error(str(exc))

result = st.session_state.get("youtube_result")
if result:
    reports = result["reports"]
    if not reports: st.warning("No resolved, explicit Indian-stock calls were found.")
    for report in reports:
        with st.container(border=True):
            st.subheader(f"#{report.rank} {report.company_name} ({report.ticker}) — {report.conviction_score}/100")
            a, b, c = st.columns(3)
            a.metric("Channel entry", report.suggested_buy_price or "Not stated")
            b.metric("Channel target", report.target_price or "Not stated")
            c.metric("Channel stop loss", report.stop_loss or "Not stated")
            st.caption(f"{report.mention_count} video(s) · {', '.join(report.source_channels)} · HFIP rating: {report.hfip_rating or 'Unavailable'}/10 · HFIP model: {report.hfip_model or 'Unavailable'}")
            if report.data_quality == "Complete":
                st.success("Data quality: Complete")
            else:
                st.warning("Data quality: Degraded — " + "; ".join(report.data_quality_notes))
            st.write("**Buy-side evidence:** " + report.buy_side_view)
            st.write("**Risk view:** " + report.sell_side_view)
            st.caption(report.channel_price_note)
            if st.button(f"Deep-dive in main analyser: {report.ticker}", key=report.ticker):
                st.session_state["prefill_ticker"] = report.ticker
                st.switch_page("app.py")
    with st.expander("All resolved stocks"):
        st.dataframe([{"Ticker": s.ticker, "Company": s.company_name, "Videos": s.mention_count, "Channels": ", ".join(s.channels), "Action": s.consensus_action} for s in result["stocks"]], width="stretch")
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
    if reports:
        buffer = StringIO(); writer = csv.writer(buffer); writer.writerow(["rank", "ticker", "company", "conviction", "channel_entry", "channel_target", "channel_stop", "hfip_rating", "channels"])
        for r in reports: writer.writerow([r.rank, r.ticker, r.company_name, r.conviction_score, r.suggested_buy_price, r.target_price, r.stop_loss, r.hfip_rating, "; ".join(r.source_channels)])
        st.download_button("Export ranked results CSV", buffer.getvalue(), "youtube_stock_scan.csv", "text/csv")
    if result["errors"]:
        with st.expander("Skipped videos and scan issues"):
            for error in result["errors"]: st.write("• " + error)

with st.expander("Planned channel monitoring", expanded=False):
    st.info("Later: choose channels, schedule a daily scan of their newest video, and configure delivery. Telegram/WhatsApp delivery is not connected in this release.")
