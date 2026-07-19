import asyncio
from pathlib import Path
import sys
import streamlit as st

sys.path.insert(0, str(Path(__file__).parents[1]))
from src.utils.config_loader import load_config
from src.utils.pdf_report import GLOSSARY
from src.youtube_signals import YouTubeScannerService
from src.youtube_signals.exports import build_scan_csv
from src.youtube_signals.monitoring import ChannelMonitoringService, ChannelStore, persist_run_artifacts

st.set_page_config(page_title="YouTube Stock Scanner", layout="wide")
st.title("📺 YouTube Stock Scanner")
st.caption("Controlled beta — public videos only. Final rank score = 60% channel conviction + 40% SAIP rating. The shortlist is shown first; the CSV contains every deep-dived stock from the scan.")
subject_id = st.text_input("Unique subject / user ID", key="youtube_subject_id", placeholder="e.g. client-001 or telegram-chat-123456", help="All saved channels, videos, runs, and artifacts are partitioned by this ID.")
with st.expander("How to read values", expanded=False):
    for label, meaning in GLOSSARY:
        st.write(f"**{label}** - {meaning}")

channel_store = ChannelStore()
with st.expander("Saved channel library - latest one video per channel", expanded=False):
    st.caption("Every enabled channel becomes eligible for a daily admin-approved run after 11:00 AM India time. Manual scans remain available anytime.")
    with st.form("add_saved_channel", clear_on_submit=True):
        saved_url = st.text_input("Channel URL", placeholder="https://www.youtube.com/@Channel/videos")
        saved_label = st.text_input("Label (optional)", placeholder="e.g. Groww")
        add_channel = st.form_submit_button("Save channel")
    if add_channel:
        try:
            channel_store.add_channel(subject_id, saved_url, saved_label)
            st.success("Channel saved.")
        except Exception as exc:
            st.error(str(exc))
    saved_channels = channel_store.list_channels(subject_id) if subject_id.strip() else []
    if saved_channels:
        for channel in saved_channels:
            left, middle, right = st.columns([5, 1, 1])
            left.write(f"**{channel.label}**  \\n{channel.url}")
            if middle.button("Disable" if channel.enabled else "Enable", key=f"saved-channel-toggle-{channel.id}"):
                channel_store.set_enabled(subject_id, channel.id, not channel.enabled)
                st.rerun()
            if right.button("Remove", key=f"saved-channel-delete-{channel.id}"):
                channel_store.delete_channel(subject_id, channel.id)
                st.rerun()
        if st.button("Analyse latest unseen video from every enabled channel", type="primary"):
            status = st.status("Starting saved-channel run...", expanded=True)
            try:
                def progress(message): status.write(message)
                run_id, monitored_result, monitored_videos = asyncio.run(
                    ChannelMonitoringService(load_config(), channel_store, subject_id, progress).run_latest()
                )
                artifact_paths = persist_run_artifacts(channel_store, subject_id, run_id, monitored_result)
                st.session_state["youtube_result"] = monitored_result
                st.session_state["youtube_monitoring_artifacts"] = {"run_id": run_id, "csv": artifact_paths["csv"], "pdf": artifact_paths["pdf"], "video_count": len(monitored_videos)}
                status.update(label="Saved-channel run complete", state="complete")
            except Exception as exc:
                status.update(label="Saved-channel run failed", state="error")
                st.error(str(exc))
    else:
        st.caption("No saved channels yet. Add public channel links above.")

with st.form("youtube_scan"):
    urls_text = st.text_area("Video or channel URLs (one per line)", placeholder="https://www.youtube.com/watch?v=...\nhttps://www.youtube.com/@Channel/videos")
    c1, c2, c3 = st.columns(3)
    lookback = c1.selectbox("Channel lookback", [7, 14, 30], index=1)
    max_videos = c2.slider("Videos per channel", 1, 10, 4)
    top_n = c3.slider("Ranked stocks", 1, 6, 5)
    skip_debate = st.checkbox("Skip SAIP bull/bear debate (faster)", value=False)
    submitted = st.form_submit_button("Scan public videos", type="primary")

if submitted:
    urls = [line.strip() for line in urls_text.splitlines() if line.strip()]
    if not subject_id.strip():
        st.error("Enter a unique subject / user ID before starting a scan.")
    elif not urls:
        st.error("Add at least one public YouTube video or channel URL.")
    else:
        status = st.status("Starting scan...", expanded=True)
        run_id = channel_store.start_run(subject_id, "manual_links")
        def progress(message): status.write(message)
        try:
            result = asyncio.run(YouTubeScannerService(load_config(), progress).scan(
                urls, lookback, max_videos, top_n, skip_debate=skip_debate
            ))
            channel_store.finish_run(subject_id, run_id, result, result.get("errors", []))
            artifact_paths = persist_run_artifacts(channel_store, subject_id, run_id, result)
            st.session_state["youtube_result"] = result
            st.session_state["youtube_monitoring_artifacts"] = {"run_id": run_id, "csv": artifact_paths["csv"], "pdf": artifact_paths["pdf"], "video_count": len(result.get("videos", []))}
            status.update(label="Scan complete", state="complete")
        except Exception as exc:
            channel_store.finish_run(subject_id, run_id, None, [str(exc)], failed=True)
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
            a.metric("Channel entry", report.suggested_buy_price or "N/S")
            b.metric("Channel target", report.target_price or "N/S")
            c.metric("Channel stop loss", report.stop_loss or "N/S")
            st.caption(f"Channel conviction: {report.conviction_score}/100 · {report.mention_count} video(s) · {', '.join(report.source_channels)} · SAIP {report.saip_execution_mode} rating: {report.saip_rating or 'Unavailable'}/10 · SAIP model: {report.saip_model or 'Unavailable'}")
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
            "SAIP rating": report_by_ticker.get(s.ticker).saip_rating if s.ticker in report_by_ticker else None,
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
        st.download_button("Export all ranked stocks CSV", build_scan_csv(result), "youtube_stock_scan.csv", "text/csv")
    if result["errors"]:
        with st.expander("Skipped videos and scan issues"):
            for error in result["errors"]: st.write("• " + error)

artifacts = st.session_state.get("youtube_monitoring_artifacts")
if artifacts:
    st.success(f"Saved-channel run {artifacts['run_id']} processed {artifacts['video_count']} latest video(s).")
    left, right = st.columns(2)
    left.download_button("Download saved-run CSV", Path(artifacts["csv"]).read_bytes(), "youtube_stock_scan.csv", "text/csv")
    right.download_button("Download saved-run PDF", Path(artifacts["pdf"]).read_bytes(), "youtube_stock_scan.pdf", "application/pdf")
