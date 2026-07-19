import asyncio
import hmac
import os
from pathlib import Path
import sys

import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parents[1]))
from src.utils.config_loader import load_config
from src.youtube_signals.monitoring import ChannelStore, queue_daily_approval, run_all_enabled_channels, run_approved_daily_schedule

st.set_page_config(page_title="SAIP Admin", layout="wide")
st.title("🔐 SAIP Admin Controls")
st.caption("Local-admin approval is required before any all-user scan can use this laptop's compute.")
with st.sidebar:
    st.page_link("app.py", label="SAIP Stock Analysis", icon="📊")
    st.page_link("pages/2_📺_YouTube_Stock_Scanner.py", label="YouTube Stock Scanner", icon="📺")
    st.page_link("pages/3_🔐_SAIP_Admin.py", label="SAIP Admin", icon="🔐")

load_dotenv()
configured_password = os.getenv("ADMIN_PASSWORD")
if not configured_password:
    st.error("ADMIN_PASSWORD is not configured. Add it to your .env file, then restart Streamlit.")
    st.stop()

if not st.session_state.get("saip_admin_authenticated"):
    with st.form("saip_admin_login"):
        entered_password = st.text_input("Admin password", type="password")
        unlock = st.form_submit_button("Unlock admin controls", type="primary")
    if unlock:
        if hmac.compare_digest(entered_password, configured_password):
            st.session_state["saip_admin_authenticated"] = True
            st.rerun()
        st.error("Incorrect admin password.")
    st.stop()

left, right = st.columns([6, 1])
left.success("Admin controls unlocked for this browser session.")
if right.button("Lock"):
    st.session_state.pop("saip_admin_authenticated", None)
    st.rerun()

store = ChannelStore()
scheduled_date, daily_status = queue_daily_approval(store)
enabled_channels = store.list_enabled_channels()
subject_count = len({channel.owner_subject for channel in enabled_channels})
metric_col, refresh_col = st.columns([5, 1])
metric_col.metric("Enabled user channels", len(enabled_channels), help="Channels belonging to all subjects/users that would be included in an all-user scan.")
if refresh_col.button("Refresh"):
    st.rerun()
st.caption(f"Across {subject_count} unique subject/user ID(s).")
with st.expander("Saved user channels in database", expanded=True):
    if enabled_channels:
        st.dataframe([
            {
                "Subject / user ID": channel.owner_subject,
                "Channel": channel.label,
                "URL": channel.url,
                "Latest processed video": channel.last_processed_video_id or "N/S",
            }
            for channel in enabled_channels
        ], width="stretch", hide_index=True)
    else:
        st.caption("No enabled channels are stored yet.")

st.subheader("Daily approval")
st.caption("After 11:00 AM India time, the scheduler only creates a pending request. It cannot start a scan without your approval below.")
if scheduled_date:
    st.write(f"Daily scan for **{scheduled_date}**: **{daily_status.replace('_', ' ')}**")
else:
    st.info("The next daily approval window opens at 11:00 AM India time.")

confirm = st.checkbox("I understand this will run analysis for every enabled user channel and use this laptop's compute.", key="admin_compute_confirm")
run_daily = st.button("Approve and run today's daily full scan", type="primary", disabled=not (confirm and daily_status in {"pending_approval", "approved", "failed"}))
run_all_now = st.button("Run full latest-unseen scan for all users now", disabled=not confirm)

if run_daily and scheduled_date:
    store.approve_daily_schedule(scheduled_date)
    status = st.status("Running approved daily scan...", expanded=True)
    try:
        run_ids = asyncio.run(run_approved_daily_schedule(load_config(), store, scheduled_date, status.write))
        status.update(label="Approved daily scan complete", state="complete")
        st.success(f"Completed {len(run_ids)} user-channel run(s).")
    except Exception as exc:
        status.update(label="Approved daily scan failed", state="error")
        st.error(str(exc))

if run_all_now:
    status = st.status("Running admin-requested full scan...", expanded=True)
    try:
        run_ids = asyncio.run(run_all_enabled_channels(load_config(), store, status.write))
        status.update(label="Admin full scan complete", state="complete")
        st.success(f"Completed {len(run_ids)} user-channel run(s).")
    except Exception as exc:
        status.update(label="Admin full scan failed", state="error")
        st.error(str(exc))

with st.expander("How the daily approval works"):
    st.write("The scheduler records a pending approval after 11:00 AM India time. If the laptop is asleep or off, no scan happens. When the laptop or scheduler starts later, it can only queue the approval; this page remains the required human approval step.")
