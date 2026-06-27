import streamlit as st
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.utils.config_loader import load_config
from src.pipeline.orchestrator import PipelineOrchestrator

st.set_page_config(page_title="SIAP v2.5", layout="wide")
st.title("Hedge Fund Intelligence Platform v2.5")
st.caption("AI-powered multi-agent stock analysis")

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
with st.form("analysis_form"):
    col1, col2, col3 = st.columns(3)
    ticker = col1.text_input("Ticker", placeholder="RELIANCE.NS or AAPL")
    exchange = col2.selectbox("Exchange", ["IN", "US"])
    duration = col3.selectbox("Horizon (months)", [6, 12, 18, 24, 36, 60], index=2)
    depth = st.radio("Analysis Depth", ["quick", "balanced", "premium"],
                     index=1, horizontal=True)
    skip_debate = st.checkbox("Skip debate (faster)")
    submitted = st.form_submit_button("Analyse", type="primary")

if submitted and config and ticker:
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
                        score = report.get("score") or report.get("moat_score") or "N/A"
                        model = report.get("_model_used", "N/A")
                        agent_data.append({"Agent": name, "Score": score, "Model": model})

                if agent_data:
                    st.dataframe(agent_data, use_container_width=True)

                st.subheader("Score Calculation")
                calc = cio.get("score_calculation", {})
                for k, v in calc.items():
                    st.write(f"**{k}**: {v}")

            with tab3:
                if debate and debate.get("transcript"):
                    for entry in debate["transcript"]:
                        with st.expander(f"Round {entry['round']} — {entry['role'].upper()}"):
                            st.write(entry["content"])

                    st.metric("Bull Conviction", f"{debate.get('bull_conviction', 'N/A')}/10")
                    st.metric("Bear Conviction", f"{debate.get('bear_conviction', 'N/A')}/10")
                    if debate.get("high_uncertainty"):
                        st.warning("HIGH UNCERTAINTY: Bull/Bear spread > 3 points")
                else:
                    st.info("Debate skipped or no transcript available.")

            with tab4:
                st.json(result)

        except Exception as e:
            st.error(f"Pipeline failed: {e}")
            import traceback
            st.code(traceback.format_exc())
