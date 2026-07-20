"""Human-readable SAIP PDF reports for the main analysis and YouTube scans."""
from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape


GLOSSARY = [
    ("N/A", "Not available. SAIP could not obtain a reliable value from the available data or analysis output."),
    ("N/S", "Not stated. The source video did not state a price, target, stop loss, or other requested item."),
    ("Unavailable", "A value was not returned by the selected model or data provider for this run."),
    ("Degraded", "The report is usable, but one or more data sources, agents, or debate steps failed or were missing."),
    ("ERROR", "The named component failed. Its output was not treated as evidence for the final assessment."),
]


def _packages():
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )
    return colors, TA_CENTER, A4, ParagraphStyle, getSampleStyleSheet, mm, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _document(title: str):
    colors, center, a4, paragraph_style, sample_styles, mm, page_break, paragraph, simple_doc, spacer, table, table_style = _packages()
    output = BytesIO()
    doc = simple_doc(output, pagesize=a4, rightMargin=16 * mm, leftMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm, title=title, author="SAIP")
    styles = sample_styles()
    styles.add(paragraph_style("SAIPTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=23, leading=28, textColor=colors.HexColor("#0B1F3A"), alignment=center, spaceAfter=12))
    styles.add(paragraph_style("SAIPH1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=colors.HexColor("#0B1F3A"), spaceBefore=10, spaceAfter=7))
    styles.add(paragraph_style("SAIPH2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=colors.HexColor("#173F5F"), spaceBefore=8, spaceAfter=4))
    styles.add(paragraph_style("SAIPBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=9, leading=13, spaceAfter=5))
    styles.add(paragraph_style("SAIPSmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=7.5, leading=10))
    return output, doc, styles, (colors, page_break, paragraph, spacer, table, table_style)


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColorRGB(.35, .35, .35)
    canvas.drawString(doc.leftMargin, 10 * 2.835, "SAIP - Stock Analysis Intelligence Platform | Informational analysis, not investment advice")
    canvas.drawRightString(doc.pagesize[0] - doc.rightMargin, 10 * 2.835, f"Page {doc.page}")
    canvas.restoreState()


def _paragraph(text, styles, key="SAIPBody"):
    paragraph = _packages()[7]
    safe_text = str(text or "N/A").replace("₹", "INR ")
    return paragraph(escape(safe_text).replace("\n", "<br/>"), styles[key])


def _table(rows, widths, styles, colors):
    table = _packages()[10]
    table_style = _packages()[11]
    data = [[_paragraph(value, styles, "SAIPSmall") for value in row] for row in rows]
    rendered = table(data, colWidths=widths, repeatRows=1, hAlign="LEFT")
    rendered.setStyle(table_style([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0B1F3A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), .35, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 1), (-1, -1), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return rendered


def _number(value, decimals: int = 2) -> str:
    try:
        return f"{float(value):,.{decimals}f}"
    except (TypeError, ValueError):
        return "N/A"


def _percent(value, decimals: int = 1, *, ratio: bool = False) -> str:
    try:
        numeric = float(value) * 100 if ratio else float(value)
        return f"{numeric:,.{decimals}f}%"
    except (TypeError, ValueError):
        return "N/A"


def _money(value, exchange: str, *, compact: bool = False) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "N/A"
    symbol = "$" if exchange == "US" else "INR "
    if compact:
        for divisor, suffix in ((1_000_000_000_000, "T"), (1_000_000_000, "B"), (1_000_000, "M")):
            if abs(numeric) >= divisor:
                return f"{symbol}{numeric / divisor:,.2f}{suffix}"
    return f"{symbol}{numeric:,.2f}"


def _financial_metric_rows(metadata: dict) -> list[list[str]]:
    exchange = str(metadata.get("exchange") or "IN").upper()
    metrics = metadata.get("key_metrics") or {}
    return [
        ["Current price", _money(metrics.get("current_price"), exchange)],
        ["Analyst target", _money(metrics.get("analyst_target"), exchange)],
        ["Target upside/(downside)", _percent(metrics.get("target_upside_pct"))],
        ["Market cap", _money(metrics.get("market_cap"), exchange, compact=True)],
        ["P/E", _number(metrics.get("pe_ratio")) + "x" if metrics.get("pe_ratio") is not None else "N/A"],
        ["P/B", _number(metrics.get("pb_ratio")) + "x" if metrics.get("pb_ratio") is not None else "N/A"],
        ["EV/EBITDA", _number(metrics.get("ev_ebitda")) + "x" if metrics.get("ev_ebitda") is not None else "N/A"],
        ["Free cash flow", _money(metrics.get("free_cash_flow"), exchange, compact=True)],
        ["FCF margin", _percent(metrics.get("fcf_margin"), ratio=True)],
        ["FCF yield", _percent(metrics.get("fcf_yield_pct"))],
        ["ROE", _percent(metrics.get("roe"), ratio=True)],
        ["Debt/equity", _number(metrics.get("debt_equity")) + "x" if metrics.get("debt_equity") is not None else "N/A"],
        ["Interest coverage", _number(metrics.get("interest_coverage")) + "x" if metrics.get("interest_coverage") is not None else "N/A"],
    ]


def build_main_analysis_pdf(result: dict, run_settings: dict) -> bytes:
    """Create a printable main-analysis report without raw JSON payloads."""
    output, doc, styles, items = _document("SAIP Stock Analysis Report")
    colors, page_break, paragraph, spacer, table, _ = items
    story = []
    cio = result.get("cio") or {}
    ticker = cio.get("ticker") or run_settings.get("ticker", "N/A")
    company = cio.get("company_name") or "N/A"
    story += [paragraph("SAIP", styles["SAIPTitle"]), paragraph("Stock Analysis Report", styles["SAIPH1"]), paragraph(f"{escape(str(company))} ({escape(str(ticker))})", styles["SAIPH2"]), paragraph("This report consolidates the final decision, key market data, agent scorecard, debate record, data-quality notices, and a legend for unavailable values.", styles["SAIPBody"]), spacer(1, 10)]
    story.append(_table([
        ["Run settings", "Value"],
        ["Exchange", run_settings.get("exchange", "N/A")], ["Horizon", f"{run_settings.get('duration', 'N/A')} months"],
        ["Depth", run_settings.get("depth", "N/A")], ["Debate", "Skipped" if run_settings.get("skip_debate") else "Enabled"],
    ], [130, 340], styles, colors))
    story.append(page_break())

    story.append(paragraph("Final Report", styles["SAIPH1"]))
    story.append(_table([
        ["Metric", "Value"], ["Final rating", f"{cio.get('final_rating', 'N/A')}/10"],
        ["Verdict", cio.get("verdict", "N/A")], ["Conviction", cio.get("conviction", "N/A")],
        ["Uncertainty", cio.get("uncertainty", "N/A")], ["Expected CAGR", cio.get("expected_cagr", "N/A")],
        ["Position size", cio.get("recommended_position_size", "N/A")], ["Buy below", cio.get("buy_below_price", "N/A")],
        ["Next catalyst", cio.get("next_catalyst_to_watch", "N/A")],
    ], [150, 320], styles, colors))
    story.append(paragraph("Key financials and valuation", styles["SAIPH2"]))
    story.append(_table([["Metric", "Value"]] + _financial_metric_rows(result.get("kg_metadata") or {}), [150, 320], styles, colors))
    story.append(paragraph("Five-point summary", styles["SAIPH2"]))
    for point in cio.get("five_point_summary", []) or ["N/A"]:
        story.append(_paragraph(f"- {point}", styles))
    gaps = list((result.get("kg_metadata") or {}).get("data_gaps", []))
    failures = [name for name, value in (result.get("agent_reports") or {}).items() if isinstance(value, dict) and value.get("error")]
    if gaps or failures or (result.get("audited_bundle") or {}).get("error"):
        story.append(paragraph("Data quality", styles["SAIPH2"]))
        story.append(_paragraph("Degraded: " + ", ".join(gaps + [f"agent:{name}" for name in failures] + (["evidence_auditor"] if (result.get("audited_bundle") or {}).get("error") else [])), styles))

    story.append(page_break())
    story.append(paragraph("Agent Scorecard", styles["SAIPH1"]))
    summary_rows = [["Agent", "Score", "Status"]]
    for name, report in (result.get("agent_reports") or {}).items():
        if not isinstance(report, dict):
            continue
        score = report.get("score", report.get("moat_score", "N/A"))
        summary_rows.append([name, score, "Unavailable for this run" if report.get("error") else "OK"])
    det_risk = result.get("det_risk") or {}
    if det_risk:
        summary_rows.append(["deterministic_risk", det_risk.get("det_risk_score", "N/A"), "OK"])
    story.append(_table(summary_rows, [170, 75, 300], styles, colors))

    story.append(paragraph("Debate", styles["SAIPH1"]))
    debate = result.get("debate") or {}
    if debate.get("error"):
        story.append(_paragraph("The debate was unavailable for this run.", styles))
    transcript = debate.get("transcript") or []
    if not debate.get("error") and transcript:
        for entry in transcript:
            story.append(paragraph(f"Round {entry.get('round', 'N/A')} - {str(entry.get('role', 'N/A')).upper()}", styles["SAIPH2"]))
            story.append(_paragraph(entry.get("content", "N/A"), styles))
        story.append(_table([["Bull conviction", "Bear conviction", "High uncertainty"], [f"{debate.get('bull_conviction', 'N/A')}/10", f"{debate.get('bear_conviction', 'N/A')}/10", "Yes" if debate.get("high_uncertainty") else "No"]], [155, 155, 155], styles, colors))
    elif not debate.get("error"):
        story.append(_paragraph("N/A - Debate was skipped or no debate transcript was produced.", styles))

    story.append(page_break())
    story.append(paragraph("Value Guide", styles["SAIPH1"]))
    story.append(_table([["Label", "Meaning"]] + GLOSSARY, [95, 375], styles, colors))
    story.append(_paragraph("Ratings and agent scores use a 0-10 scale unless explicitly shown otherwise. A displayed error means that component did not contribute usable evidence. This is informational analysis, not investment advice.", styles))
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return output.getvalue()


def build_scanner_pdf(result: dict, run_id: str) -> bytes:
    """Create the persisted PDF summary for a saved-channel monitoring run."""
    output, doc, styles, items = _document("SAIP YouTube Scan Report")
    colors, _, paragraph, spacer, _, _ = items
    story = [paragraph("SAIP YouTube Scanner", styles["SAIPTitle"]), paragraph("Saved Channel Monitoring Report", styles["SAIPH1"]), _paragraph(f"Run ID: {run_id}", styles), spacer(1, 8)]
    rows = [["Rank", "Ticker", "Company", "Rank score", "Conviction", "SAIP rating", "Channels"]]
    for report in result.get("all_reports", result.get("reports", [])):
        rows.append([report.rank, report.ticker, report.company_name, report.ranking_score, report.conviction_score, report.saip_rating or "N/A", "; ".join(report.source_channels)])
    story.append(_table(rows, [35, 73, 110, 60, 60, 58, 74], styles, colors))
    unresolved = result.get("unresolved", [])
    story.append(paragraph("Unresolved company names", styles["SAIPH1"]))
    if unresolved:
        story.append(_table([["Company", "Channel", "Action", "Video ID"]] + [[call.company_name_raw, call.channel_name, call.action, call.video_id] for call in unresolved], [150, 120, 70, 130], styles, colors))
    else:
        story.append(_paragraph("None", styles))
    story.append(paragraph("Value Guide", styles["SAIPH1"]))
    story.append(_table([["Label", "Meaning"]] + GLOSSARY, [95, 375], styles, colors))
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return output.getvalue()
