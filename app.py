import streamlit as st
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.utils.config_loader import load_config
from src.pipeline.orchestrator import PipelineOrchestrator
from src.data.intelligence_builder import MarketDataUnavailableError

st.set_page_config(page_title="SIAP v2.5", layout="wide")
st.title("Hedge Fund Intelligence Platform v2.5")
st.caption("AI-powered multi-agent stock analysis")
st.sidebar.info("📺 Scan public YouTube videos or channels from **YouTube Stock Scanner** in the page list.")

# Sidebar config
with st.sidebar:
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

            # Tab 1: Final Report
            tab1, tab2, tab3, tab4 = st.tabs(["Final Report", "Agent Scores", "Debate", "Raw JSON"])

            with tab1:
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
