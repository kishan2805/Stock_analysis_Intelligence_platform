from __future__ import annotations

import csv
from io import StringIO


def build_scan_csv(result: dict) -> str:
    """Create the scanner CSV, retaining unresolved names without inventing a ticker."""
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["rank", "ticker", "company", "resolution_status", "rank_score", "conviction", "saip_rating", "channel_entry", "channel_target", "channel_stop", "channels", "channel_action", "video_ids"])
    for report in result.get("all_reports", result.get("reports", [])):
        writer.writerow([report.rank, report.ticker, report.company_name, "Resolved", report.ranking_score, report.conviction_score, report.saip_rating, report.suggested_buy_price, report.target_price, report.stop_loss, "; ".join(report.source_channels), "", ""])
    unresolved_by_name = {}
    for call in result.get("unresolved", []):
        key = call.company_name_raw.strip().casefold()
        item = unresolved_by_name.setdefault(key, {"company": call.company_name_raw, "channels": set(), "actions": set(), "video_ids": set()})
        item["channels"].add(call.channel_name)
        item["actions"].add(call.action)
        item["video_ids"].add(call.video_id)
    for item in unresolved_by_name.values():
        writer.writerow(["", "", item["company"], "Unresolved - confirm NSE ticker", "", "", "", "", "", "", "; ".join(sorted(item["channels"])), "; ".join(sorted(item["actions"])), "; ".join(sorted(item["video_ids"]))])
    return buffer.getvalue()
