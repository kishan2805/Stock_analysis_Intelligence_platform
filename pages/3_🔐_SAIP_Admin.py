import asyncio
import hmac
import os
from pathlib import Path
import sys

import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parents[1]))
from src.utils.config_loader import load_config
from src.telegram_bot.notifications import send_cancellation_notification, send_rejection_notification
from src.telegram_bot.store import TelegramStore
from src.telegram_bot.worker import TelegramWorkerManager
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

st.subheader("Telegram bot worker")
telegram_worker = TelegramWorkerManager()
telegram_status = telegram_worker.status()
worker_col, start_col, stop_col, log_col = st.columns([3, 2, 2, 2])
worker_col.metric("Bot status", telegram_status.message, telegram_status.pid or "—")
if start_col.button("Start Telegram bot", type="primary", disabled=telegram_status.running):
    try:
        telegram_status = telegram_worker.start()
        if telegram_status.running:
            st.success(f"Telegram bot started (PID {telegram_status.pid}).")
        else:
            st.error(telegram_status.message)
    except Exception as exc:
        st.error(f"Telegram bot could not start: {exc}")
if stop_col.button("Stop Telegram bot", disabled=not telegram_status.running):
    try:
        telegram_status = telegram_worker.stop()
        st.info(telegram_status.message)
    except Exception as exc:
        st.error(f"Telegram bot could not stop: {exc}")
if log_col.button("Refresh bot status"):
    st.rerun()
st.caption("Starting the worker makes the bot receive Telegram messages and resume any queued analyses. It does not rerun completed reports. The bot stops when this machine is off.")
with st.expander("Recent Telegram worker log", expanded=False):
    st.code(telegram_worker.recent_log(), language="text")

st.subheader("Telegram analysis activity")
telegram_store = TelegramStore()
telegram_jobs = telegram_store.admin_job_activity()
queued_count = sum(job["status"] == "queued" for job in telegram_jobs)
running_jobs = [job for job in telegram_jobs if job["status"] == "running"]
completed_count = sum(job["status"] == "completed" for job in telegram_jobs)
activity_metrics, activity_refresh = st.columns([6, 1])
with activity_metrics:
    one, two, three = st.columns(3)
    one.metric("Queued", queued_count)
    two.metric("Running", len(running_jobs))
    three.metric("Completed", completed_count)
if activity_refresh.button("Refresh analysis activity"):
    st.rerun()
if running_jobs:
    for job in running_jobs:
        st.info(f"{job['kind']} analysis in progress: **{job['target']}** — {job['progress_text'] or 'Working'}")
else:
    st.caption("No Telegram analysis is currently running.")
if telegram_jobs:
    st.dataframe([
        {
            "Type": job["kind"],
            "Target": job["target"],
            "Status": job["status"],
            "Current stage": job["progress_text"] or "N/A",
            "Requested": job["created_at"],
            "Updated": job["updated_at"] or job["completed_at"] or job["started_at"] or "N/A",
            "Issue": job["error"] or "",
        }
        for job in telegram_jobs
    ], width="stretch", hide_index=True)
else:
    st.caption("No Telegram stock or video analysis has been requested yet.")

actionable_jobs = [job for job in telegram_jobs if job["status"] in {"queued", "running"}]
with st.expander("Reject or restart Telegram analysis", expanded=False):
    st.caption("Queued work can be rejected. For running work, Reject cancels the request; Restart preserves the request and retries it after restarting the worker.")
    if not actionable_jobs:
        st.caption("No queued or running Telegram analysis is awaiting a decision.")
    for job in actionable_jobs:
        left, reject_col, restart_col = st.columns([5, 1, 1])
        left.write(f"**{job['kind']}** — {job['target']}  \\nRequested: {job['created_at']}")
        is_running = job["status"] == "running"
        reject_clicked = reject_col.button("Reject", key=f"reject-telegram-job-{job['id']}")
        restart_clicked = is_running and restart_col.button("Restart", key=f"restart-telegram-job-{job['id']}")
        if reject_clicked or restart_clicked:
            handled = None
            if reject_clicked:
                handled = (
                    telegram_store.cancel_running_job(job["job_type"], job["id"])
                    if is_running
                    else telegram_store.reject_queued_job(job["job_type"], job["id"])
                )
            if reject_clicked and not handled:
                st.warning("That request has already started or was handled. Refresh the activity list.")
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
