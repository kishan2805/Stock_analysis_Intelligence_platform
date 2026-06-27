from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()

def print_final_report(cio: dict, debate: dict, audited: dict, agent_reports: dict = None):
    title = f"SIAP v2.5 — {cio.get('ticker')} ({cio.get('company_name')})"
    scores = cio.get("scores", {})
    calc = cio.get("score_calculation", {})

    lines = [
        f"[bold yellow]FINAL RATING: {cio.get('final_rating')}/10  [{cio.get('verdict')} — {cio.get('conviction')} CONVICTION][/]",
        f"Investment Horizon: {cio.get('investment_horizon_months')} months  |  Uncertainty: {cio.get('uncertainty')}",
        f"Evidence Reliability: {audited.get('reliability_score', 'N/A')}/10  (confidence penalty: {calc.get('confidence_penalty', 0)} applied)",
        "",
        "[bold]MULTIDIMENSIONAL SCORES:[/]",
        f"  Business Quality:    {scores.get('business_quality', 'N/A')}/10",
        f"  Investment Quality:  {scores.get('investment_quality', 'N/A')}/10",
        f"  Valuation:           {scores.get('valuation_score', 'N/A')}/10",
        f"  Macro Risk:          {scores.get('macro_risk', 'N/A')}/10",
        f"  Execution Risk:      {scores.get('execution_risk', 'N/A')}/10",
        f"  Catalyst Score:      {scores.get('catalyst_score', 'N/A')}/10",
        "",
        "[bold]FORMULA:[/]",
        f"  Weighted Raw: {calc.get('weighted_raw', 'N/A')}  |  Confidence: {calc.get('confidence_penalty', 0)}  |  Debate adj: {calc.get('debate_adjustment', 0)}  |  Regime: {calc.get('regime_multiplier', 0)}  |  Final: {calc.get('final', 'N/A')}",
        "",
        "[bold]5-POINT SUMMARY:[/]",
    ]

    for pt in cio.get("five_point_summary", []):
        lines.append(f"  {pt}")

    lines.extend([
        "",
        f"[bold]EXPECTED CAGR:[/] {cio.get('expected_cagr', 'N/A')}  |  [bold]POSITION SIZE:[/] {cio.get('recommended_position_size', 'N/A')}",
        f"[bold]BUY BELOW:[/] {cio.get('buy_below_price', 'N/A')}  |  [bold]NEXT CATALYST:[/] {cio.get('next_catalyst_to_watch', 'N/A')}",
        f"[bold]THESIS RISK:[/] {cio.get('thesis_invalidating_risk', 'N/A')}",
    ])

    if debate:
        lines.extend([
            "",
            f"[bold]BULL vs BEAR:[/]",
            f"  Bull final: {debate.get('bull_conviction', 'N/A')}/10",
            f"  Bear final: {debate.get('bear_conviction', 'N/A')}/10",
        ])

    console.print(Panel("\n".join(lines), title=title, border_style="gold1"))

def print_agent_scores_table(agent_reports: dict):
    table = Table(title="Agent Scores (Post-Audit)", box=box.ROUNDED)
    table.add_column("Agent", style="cyan")
    table.add_column("Score", justify="right")
    table.add_column("Model Used", style="dim")

    for name, report in agent_reports.items():
        if isinstance(report, dict):
            score = report.get("score", report.get("moat_score", "N/A"))
            model = report.get("_model_used", "N/A")
            table.add_row(name, str(score), model)

    console.print(table)
