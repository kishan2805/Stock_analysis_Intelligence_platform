import streamlit as st
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.utils.config_loader import load_config
from src.pipeline.orchestrator import PipelineOrchestrator
from src.data.intelligence_builder import MarketDataUnavailableError
from src.telegram_bot.notifications import send_cancellation_notification, send_rejection_notification
from src.telegram_bot.store import TelegramStore
from src.telegram_bot.worker import TelegramWorkerManager
from src.utils.pdf_report import GLOSSARY, build_main_analysis_pdf

st.set_page_config(page_title="SAIP — Stock Analysis Intelligence Platform", layout="wide")
st.title("SAIP — Stock Analysis Intelligence Platform")
st.caption("SAIP (Stock Analysis Intelligence Platform) · AI-powered multi-agent stock analysis")

# Sidebar config
with st.sidebar:
    st.page_link("app.py", label="SAIP Stock Analysis Intelligence Platform", icon="📊")
    st.page_link("pages/2_📺_YouTube_Stock_Scanner.py", label="YouTube Stock Scanner", icon="📺")
    st.page_link("pages/3_🔐_SAIP_Admin.py", label="SAIP Admin", icon="🔐")
    st.divider()
    st.header("Configuration")
    config_path = st.text_input("Config file", value="config/settings.yaml")
    try:
        config = load_config(config_path)
        st.success("Config loaded")
    except Exception as e:
        st.error(f"Config error: {e}")
        config = None

# Main form
if "prefill_ticker" in st.session_state:
    st.session_state["main_ticker"] = st.session_state.pop("prefill_ticker")
with st.form("analysis_form"):
    col1, col2, col3 = st.columns(3)
    ticker_input = col1.text_input("Ticker", key="main_ticker", placeholder="RELIANCE.NS or AAPL")
    exchange = col2.selectbox("Exchange", ["IN", "US"])
    duration = col3.selectbox("Horizon (months)", [6, 12, 18, 24, 36, 60], index=2)
    depth = st.radio("Analysis Depth", ["quick", "balanced", "premium"],
                     index=1, horizontal=True)
    skip_debate = st.checkbox("Skip debate (faster)", value=False)
    submitted = st.form_submit_button("Analyse", type="primary")

if submitted and config and ticker_input.strip():
    # Keep Streamlit handoffs identical to CLI runs (AAPL, not aapl).
    ticker = ticker_input.strip().upper()
    st.caption(f"Run settings: {ticker} · {exchange} · {duration} months · {depth} · debate {'skipped' if skip_debate else 'enabled'}")
    with st.spinner("Running SIAP pipeline..."):
        try:
            result = asyncio.run(
                PipelineOrchestrator(config).run(
                    ticker, exchange, duration, depth,
                    skip_debate=skip_debate
                )
            )

            cio = result["cio"]
            debate = result.get("debate", {})
            audited = result.get("audited_bundle", {})
            report_pdf = build_main_analysis_pdf(result, {
                "ticker": ticker, "exchange": exchange, "duration": duration,
                "depth": depth, "skip_debate": skip_debate,
            })

            # Tab 1: Final Report
            tab1, tab2, tab3, tab4 = st.tabs(["Final Report", "Agent Scores", "Debate", "Raw JSON"])

            with tab1:
                st.download_button(
                    "Download full SAIP PDF report", report_pdf,
                    file_name=f"saip_{ticker.replace('.', '_')}_report.pdf",
                    mime="application/pdf", type="primary",
                )
                st.caption("The PDF includes the final report, agent scorecard, deterministic risk summary, debate transcript, data-quality notes, and the value guide. Raw JSON remains in this app only.")
                data_gaps = result.get("kg_metadata", {}).get("data_gaps", [])
                failed_agents = [
                    name for name, report in result.get("agent_reports", {}).items()
                    if isinstance(report, dict) and report.get("error")
                ]
                data_gaps = list(data_gaps) + [f"agent:{name}" for name in failed_agents]
                if result.get("audited_bundle", {}).get("error"):
                    data_gaps.append("evidence_auditor")
                if data_gaps:
                    st.warning("Data quality: Degraded — missing " + ", ".join(data_gaps))
                col_l, col_r = st.columns([2, 1])
                with col_l:
                    st.metric("Final Rating", f"{cio.get('final_rating', 'N/A')}/10")
                    st.metric("Verdict", cio.get('verdict', 'N/A'))
                    st.metric("Conviction", cio.get('conviction', 'N/A'))
                    st.metric("Uncertainty", cio.get('uncertainty', 'N/A'))
                with col_r:
                    st.metric("Business Quality", cio.get('scores', {}).get('business_quality', 'N/A'))
                    st.metric("Investment Quality", cio.get('scores', {}).get('investment_quality', 'N/A'))
                    st.metric("Valuation", cio.get('scores', {}).get('valuation_score', 'N/A'))
                    st.metric("Macro Risk", cio.get('scores', {}).get('macro_risk', 'N/A'))

                st.subheader("5-Point Summary")
                for pt in cio.get("five_point_summary", []):
                    st.write(f"• {pt}")

                cols = st.columns(4)
                cols[0].metric("Expected CAGR", cio.get('expected_cagr', 'N/A'))
                cols[1].metric("Position Size", cio.get('recommended_position_size', 'N/A'))
                cols[2].metric("Buy Below", cio.get('buy_below_price', 'N/A'))
                cols[3].metric("Next Catalyst", cio.get('next_catalyst_to_watch', 'N/A'))

            with tab2:
                st.caption("Value guide: N/A = not available; N/S = not stated by a source; ERROR = that component failed and was not used as evidence.")
                agent_data = []
                for name, report in result.get("agent_reports", {}).items():
                    if isinstance(report, dict):
                        if name == "market_regime":
                            score = f"multiplier {report.get('sector_regime_multiplier', 'N/A')}"
                        elif name == "risk_narrative":
                            score = "narrative only"
                        else:
                            score = report.get("score")
                            if score is None:
                                score = report.get("moat_score")
                            if score is None:
                                score = "N/A"
                        model = report.get("_model_used", "N/A")
                        # Keep a single Arrow-compatible type; some agents do
                        # not have a numeric score and use the N/A marker.
                        agent_data.append({
                            "Agent": str(name),
                            "Score": str(score),
                            "Status": "ERROR: " + str(report["error"])[:60] if report.get("error") else "OK",
                            "Model": str(model),
                        })

                det_risk = result.get("det_risk") or {}
                if det_risk:
                    agent_data.append({
                        "Agent": "deterministic_risk",
                        "Score": str(det_risk.get("det_risk_score", "N/A")),
                        "Status": "OK",
                        "Model": "Python rules",
                    })

                if agent_data:
                    st.dataframe(agent_data, width="stretch")

                st.subheader("Score Calculation")
                calc = cio.get("score_calculation", {})
                for k, v in calc.items():
                    st.write(f"**{k}**: {v}")

            with tab3:
                if debate and debate.get("error"):
                    st.error(f"Debate failed: {debate['error']}")
                    if debate.get("transcript"):
                        st.caption("The partial transcript is shown below.")
                if debate and debate.get("transcript"):
                    for entry in debate["transcript"]:
                        with st.expander(f"Round {entry['round']} — {entry['role'].upper()}"):
                            st.write(entry["content"])

                    st.metric("Bull Conviction", f"{debate.get('bull_conviction', 'N/A')}/10")
                    st.metric("Bear Conviction", f"{debate.get('bear_conviction', 'N/A')}/10")
                    if debate.get("high_uncertainty"):
                        st.warning("HIGH UNCERTAINTY: Bull/Bear spread > 3 points")
                elif not (debate and debate.get("error")):
                    st.info("Debate was skipped because the checkbox was selected.")

            with tab4:
                st.json(result)

        except MarketDataUnavailableError as e:
            st.error(str(e))
        except Exception as e:
            st.error(f"Pipeline failed: {e}")
            import traceback
            st.code(traceback.format_exc())

with st.expander("How to read values", expanded=False):
    for label, meaning in GLOSSARY:
        st.write(f"**{label}** - {meaning}")

if st.session_state.get("saip_admin_authenticated"):
    st.divider()
    st.subheader("Queued Telegram analysis")
    st.caption("Admin-only controls. Queued work can be rejected; a running request can be rejected or restarted to retry it.")
    telegram_store = TelegramStore()
    telegram_worker = TelegramWorkerManager()
    actionable_jobs = [job for job in telegram_store.admin_job_activity() if job["status"] in {"queued", "running"}]
    if not actionable_jobs:
        st.caption("No queued or running stock or YouTube video analysis is awaiting a decision.")
    for job in actionable_jobs:
        left, reject_col, restart_col = st.columns([5, 1, 1])
        left.write(f"**{job['kind']}** — {job['target']}  \\nRequested: {job['created_at']}")
        is_running = job["status"] == "running"
        reject_clicked = reject_col.button("Reject", key=f"main-reject-telegram-job-{job['id']}")
        restart_clicked = is_running and restart_col.button("Restart", key=f"main-restart-telegram-job-{job['id']}")
        if reject_clicked or restart_clicked:
            handled = None
            if reject_clicked:
                handled = (
                    telegram_store.cancel_running_job(job["job_type"], job["id"])
                    if is_running
                    else telegram_store.reject_queued_job(job["job_type"], job["id"])
                )
            if reject_clicked and not handled:
                st.warning("That request has already started or was handled. Refresh and try again.")
            elif restart_clicked:
                try:
                    restart_status = telegram_worker.restart_active_worker()
                    st.success(f"Worker restarted: {restart_status.message}. The running request will retry from the queue.")
                except Exception as exc:
                    st.warning(f"Worker could not restart: {exc}")
            else:
                if is_running:
                    follow_up = []
                    try:
                        restart_status = telegram_worker.restart_active_worker()
                        follow_up.append(f"worker: {restart_status.message}")
                    except Exception as exc:
                        follow_up.append(f"worker restart failed: {exc}")
                    try:
                        asyncio.run(send_cancellation_notification(handled.chat_id, job["job_type"], job["target"]))
                        follow_up.append("user notified")
                    except Exception as exc:
                        follow_up.append(f"Telegram notification failed: {exc}")
                    st.success("Running request cancelled — " + "; ".join(follow_up))
                else:
                    try:
                        asyncio.run(send_rejection_notification(handled.chat_id, job["job_type"], job["target"]))
                        st.success("Request rejected and the Telegram user was notified.")
                    except Exception as exc:
                        st.warning(f"Request rejected, but the Telegram message could not be delivered: {exc}")
            st.rerun()
else:
    st.caption("Telegram requests can be reviewed or rejected after unlocking SAIP Admin.")
