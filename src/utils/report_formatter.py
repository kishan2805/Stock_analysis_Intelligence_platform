from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()


def _fmt(val, suffix="", fallback="N/A") -> str:
    if val is None:
        return fallback
    if isinstance(val, float):
        return f"{val:.1f}{suffix}"
    return f"{val}{suffix}"


def print_final_report(
    cio: dict,
    debate: dict,
    audited: dict,
    agent_reports: dict = None,
):
    cio = cio or {}
    debate = debate or {}
    audited = audited or {}

    title = f"SIAP v2.5 — {cio.get('ticker', '?')} ({cio.get('company_name', '?')})"
    scores = cio.get("scores") or {}
    calc   = cio.get("score_calculation") or {}

    final   = cio.get("final_rating")
    verdict = cio.get("verdict", "N/A")
    conv    = cio.get("conviction", "N/A")
    uncert  = cio.get("uncertainty", "N/A")
    horizon = cio.get("investment_horizon_months", "?")

    # Colour the rating
    if isinstance(final, (int, float)):
        colour = "green" if final >= 7.5 else ("yellow" if final >= 5.0 else "red")
        rating_str = f"[bold {colour}]{final}/10  [{verdict} — {conv} CONVICTION][/]"
    else:
        rating_str = "N/A"

    agent_scores_used = calc.get("agent_scores") or {}
    weights           = calc.get("weights") or {}

    lines = [
        f"[bold yellow]FINAL RATING: {rating_str}[/]",
        f"Investment Horizon: {horizon} months  |  Uncertainty: {uncert}",
        f"Evidence Reliability: {_fmt(audited.get('reliability_score'))}/10"
        f"  (confidence penalty: {_fmt(calc.get('confidence_penalty'), fallback='0')} applied)",
        "",
        "[bold]MULTIDIMENSIONAL SCORES:[/]",
        f"  Business Quality:    {_fmt(scores.get('business_quality'))}/10",
        f"  Investment Quality:  {_fmt(scores.get('investment_quality'))}/10",
        f"  Valuation:           {_fmt(scores.get('valuation_score'))}/10",
        f"  Macro Risk:          {_fmt(scores.get('macro_risk'))}/10  (lower = better macro env)",
        f"  Execution Risk:      {_fmt(scores.get('execution_risk'))}/10  (lower = safer)",
        f"  Catalyst Score:      {_fmt(scores.get('catalyst_score'))}/10",
        "",
        "[bold]FORMULA (deterministic):[/]",
        f"  fundamental={_fmt(agent_scores_used.get('fundamental'))}×{_fmt(weights.get('fundamental'))}  "
        f"macro={_fmt(agent_scores_used.get('macro'))}×{_fmt(weights.get('macro'))}  "
        f"moat={_fmt(agent_scores_used.get('moat'))}×{_fmt(weights.get('moat'))}",
        f"  growth={_fmt(agent_scores_used.get('growth'))}×{_fmt(weights.get('growth'))}  "
        f"risk(inverted)={(10 - (agent_scores_used.get('det_risk') or 5)):.1f}×{_fmt(weights.get('risk'))}",
        f"  Weighted Raw: {_fmt(calc.get('weighted_raw'))}  "
        f"+ Confidence: {_fmt(calc.get('confidence_penalty'), fallback='0')}  "
        f"+ Debate adj: {_fmt(calc.get('debate_adjustment'), fallback='0')}  "
        f"+ Regime: {_fmt(calc.get('regime_multiplier'), fallback='0')}  "
        f"= [bold]Final: {_fmt(final)}[/]",
        "",
        "[bold]5-POINT SUMMARY:[/]",
    ]

    summary = cio.get("five_point_summary") or []
    if summary:
        for pt in summary:
            lines.append(f"  {pt}")
    else:
        lines.append("  [dim]No summary generated — check agent logs[/dim]")

    lines.extend([
        "",
        f"[bold]EXPECTED CAGR:[/] {_fmt(cio.get('expected_cagr'))}  |  "
        f"[bold]POSITION SIZE:[/] {_fmt(cio.get('recommended_position_size'))}",
        f"[bold]BUY BELOW:[/] {_fmt(cio.get('buy_below_price'))}  |  "
        f"[bold]NEXT CATALYST:[/] {_fmt(cio.get('next_catalyst_to_watch'))}",
        f"[bold]THESIS RISK:[/] {_fmt(cio.get('thesis_invalidating_risk'))}",
    ])

    geo_flags = cio.get("geopolitical_regime_flags") or []
    if geo_flags:
        lines.append("")
        lines.append("[bold]GEOPOLITICAL / REGIME FLAGS:[/]")
        for flag in geo_flags:
            lines.append(f"  • {flag}")

    if debate and (debate.get("bull_conviction") or debate.get("bear_conviction")):
        lines.extend([
            "",
            "[bold]BULL vs BEAR:[/]",
            f"  Bull final: {_fmt(debate.get('bull_conviction'))}/10",
            f"  Bear final: {_fmt(debate.get('bear_conviction'))}/10",
        ])
        if debate.get("high_uncertainty"):
            lines.append("  [bold red]⚠ HIGH UNCERTAINTY — position size halved[/]")

    # Contradictions flagged by Evidence Auditor
    contradictions = audited.get("contradictions") or []
    if contradictions:
        lines.append("")
        lines.append(f"[bold yellow]EVIDENCE AUDIT CONTRADICTIONS ({len(contradictions)}):[/]")
        for c in contradictions[:3]:
            lines.append(f"  • {c.get('verdict', str(c))}")

    console.print(Panel("\n".join(lines), title=title, border_style="gold1"))


def print_agent_scores_table(agent_reports: dict):
    table = Table(title="Agent Scores (Post-Audit)", box=box.ROUNDED)
    table.add_column("Agent",      style="cyan",  no_wrap=True)
    table.add_column("Score",      justify="right")
    table.add_column("Status",     style="dim")
    table.add_column("Model Used", style="dim")

    for name, report in agent_reports.items():
        if not isinstance(report, dict):
            continue

        # Score — try multiple keys
        score_val = (
            report.get("score")
            or report.get("moat_score")
            or report.get("det_risk_score")
        )
        score_str = _fmt(score_val) if score_val is not None else "[red]N/A[/red]"

        # Status
        if report.get("error"):
            status = f"[red]ERROR: {str(report['error'])[:40]}[/red]"
        else:
            status = "[green]OK[/green]"

        model = report.get("_model_used", "N/A")
        table.add_row(name, score_str, status, model)

    console.print(table)
