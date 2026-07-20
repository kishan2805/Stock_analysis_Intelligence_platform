"""Small, Telegram-safe views of SAIP output."""
from __future__ import annotations


def analysis_summary(result: dict, *, limit: int = 3500) -> str:
    cio = result.get("cio") or {}
    metadata = result.get("kg_metadata") or {}
    ticker = cio.get("ticker") or metadata.get("ticker") or "N/A"
    company = cio.get("company_name") or metadata.get("company") or "N/A"
    lines = [
        "SAIP stock analysis complete",
        f"{company} ({ticker})",
        f"Rating: {cio.get('final_rating', 'N/A')}/10 | Verdict: {cio.get('verdict', 'N/A')}",
        f"Conviction: {cio.get('conviction', 'N/A')} | Uncertainty: {cio.get('uncertainty', 'N/A')}",
        f"Expected CAGR: {cio.get('expected_cagr', 'N/A')}",
        f"Buy below: {cio.get('buy_below_price', 'N/A')} | Position size: {cio.get('recommended_position_size', 'N/A')}",
        "",
        "Key points:",
    ]
    points = cio.get("five_point_summary") or ["No summary was returned; see the attached report."]
    lines.extend(f"• {point}" for point in points[:5])
    data_gaps = metadata.get("data_gaps") or []
    if data_gaps:
        lines.append("")
        lines.append("Data quality: Degraded — " + ", ".join(map(str, data_gaps)))
    lines.extend(("", "Informational research only — not investment advice."))
    return "\n".join(lines)[:limit]


def report_filename(ticker: str) -> str:
    return f"saip_{ticker.replace('.', '_')}_report.pdf"


def video_scan_summary(result: dict, *, limit: int = 3500) -> str:
    reports = result.get("reports") or []
    unresolved = result.get("unresolved") or []
    errors = result.get("errors") or []
    lines = ["SAIP YouTube video analysis complete"]
    if reports:
        lines.append("Ranked stock calls:")
        for report in reports:
            lines.extend((
                f"• #{report.rank} {report.company_name} ({report.ticker}) — {report.ranking_score}/100",
                f"  Channel conviction: {report.conviction_score}/100 | SAIP rating: {report.saip_rating or 'N/A'}/10",
                f"  Action: {report.buy_side_view[:240]}",
            ))
    else:
        lines.append("No resolved, explicit stock calls were found in this video.")
    if unresolved:
        lines.append(f"Unresolved company names: {len(unresolved)} — see the PDF for details.")
    if errors:
        lines.append(f"Scan notes: {len(errors)} item(s) were skipped or unavailable.")
    lines.extend(("", "Informational research only — not investment advice."))
    return "\n".join(lines)[:limit]


def video_report_filename() -> str:
    return "saip_youtube_video_analysis.pdf"
