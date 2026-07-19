"""Run due SAIP YouTube channel schedules outside the Streamlit request process."""
from __future__ import annotations

import argparse
import time

from .monitoring import ChannelStore, queue_daily_approval


def _run_once() -> tuple[str | None, str | None]:
    return queue_daily_approval(ChannelStore())


def main() -> None:
    parser = argparse.ArgumentParser(description="SAIP YouTube schedule worker")
    parser.add_argument("--once", action="store_true", help="Queue today's daily approval request if due, then exit. It never starts a scan.")
    parser.add_argument("--poll-seconds", type=int, default=60, help="Delay between due-job checks in worker mode.")
    args = parser.parse_args()
    while True:
        scheduled_date, status = _run_once()
        if scheduled_date and status == "pending_approval":
            print(f"Daily run for {scheduled_date} is pending local-admin approval; no scan started.")
        if args.once:
            return
        time.sleep(max(10, args.poll_seconds))


if __name__ == "__main__":
    main()
