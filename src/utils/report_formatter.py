"""
src/utils/report_formatter.py  — v2.5.1

FIX: Agent score table was showing N/A for market_regime and risk_narrative
because those agents don't emit a "score" key (they have sector_regime_multiplier
and det_risk_score respectively). The table now shows the right value for each
agent type and uses _score_display set by stage2_parallel.py.
"""

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


def _agent_score_display(name: str, report: dict) -> str:
    """
    Return the best score string for an agent in the summary table.
    Each agent type stores its primary value under a different key.
    """
    if not isinstance(report, dict):
        return "[red]N/A[/red]"

    # Use pre-computed display score from stage2_parallel if available
    ds = report.get("_score_display")
    if ds is not None:
        try:
            return f"{float(ds):.1g}"
        except (TypeError, ValueError):
            pass

    # Fallback key checks by agent type
    if name == "market_regime":
        mult = report.get("sector_regime_multiplier")
        if mult is not None:
            try:
                return f"{float(mult):+.2f} ✕"
            except (TypeError, ValueError):
                pass
        return "[dim]n/s[/dim]"  # not scored — by design

    if name == "risk_narrative":
        ds2 = report.get("det_risk_score")
        if ds2 is not None:
            try:
                return f"{float(ds2):.1f} ⚠"
            except (TypeError, ValueError):
                pass
        return "[dim]n/s[/dim]"

    # Standard score keys
    for key in ("score", "moat_score", "growth_score"):
        val = report.get(key)
        if val is not None:
            try:
                return f"{float(val):.1g}"
            except (TypeError, ValueError):
                pass

    return "[red]N/A[/red]"


def _agent_status(report: dict) -> str:
    if not isinstance(report, dict):
        return "[red]ERROR: not a dict[/red]"
    err = report.get("error")
    if not err:
        return "[green]OK[/green]"
    return f"[red]ERROR: {str(err)[:40]}[/red]"


def print_final_report(
    cio: dict,
    debate: dict,
    audited: dict,
    agent_reports: dict = None,
):
    cio     = cio or {}
    debate  = debate or {}
    audited = audited or {}

    title  = f"SIAP v2.5 — {cio.get('ticker', '?')} ({cio.get('company_name', '?')})"
    scores = cio.get("scores") or {}
    calc   = cio.get("score_calculation") or {}

    final   = cio.get("final_rating")
    verdict = cio.get("verdict", "N/A")
    conv    = cio.get("conviction", "N/A")
    uncert  = cio.get("uncertainty", "N/A")
    horizon = cio.get("investment_horizon_months", "?")

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

    console.print(Panel(
        "\n".join(lines),
        title=title,
        border_style="blue",
        expand=True,
    ))

    # Agent scores table
    if agent_reports:
        print_agent_scores_table(agent_reports)


def print_agent_scores_table(agent_reports: dict):
    """
    Print the Agent Scores table with correct values for all agent types.

    Score column legend:
      7.5        → standard 0-10 investment score
      7.0 ✕(moat)→ moat_score
      -0.4 ✕     → sector_regime_multiplier (market_regime agent)
      2.2 ⚠      → det_risk_score (risk_narrative agent — lower = less risky)
      n/s        → not scored by design (market_regime, risk_narrative)
      N/A        → agent failed to return a valid value
    """
    table = Table(
        title="Agent Scores (Post-Audit)",
        box=box.ROUNDED,
        caption=(
            "✕ = sector regime multiplier (applied to final rating)  |  "
            "⚠ = deterministic risk score (lower = safer)  |  "
            "n/s = not scored by design"
        ),
    )
    table.add_column("Agent",      style="cyan", no_wrap=True)
    table.add_column("Score",      justify="right")
    table.add_column("Status",     style="dim")
    table.add_column("Model Used", style="dim")

    # Preferred display order
    _ORDER = ["fundamental", "macro", "moat", "growth",
              "market_regime", "risk_narrative"]

    shown = set()
    for name in _ORDER:
        report = agent_reports.get(name)
        if report is None:
            continue
        shown.add(name)
        score_str = _agent_score_display(name, report)
        status    = _agent_status(report)
        model     = report.get("_model_used", "N/A") if isinstance(report, dict) else "N/A"
        table.add_row(name, score_str, status, model)

    # Any extra agents not in the preferred order
    for name, report in agent_reports.items():
        if name in shown or name == "det_risk" or not isinstance(report, dict):
            continue
        score_str = _agent_score_display(name, report)
        status    = _agent_status(report)
        model     = report.get("_model_used", "N/A")
        table.add_row(name, score_str, status, model)

    console.print(table)
