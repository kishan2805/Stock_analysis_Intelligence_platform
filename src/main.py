import asyncio
import argparse
import json
import logging
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.utils.config_loader import load_config
from src.pipeline.orchestrator import PipelineOrchestrator
from src.utils.report_formatter import print_final_report, print_agent_scores_table
from rich.console import Console
from rich.json import JSON

console = Console()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser(description="HFIP v2.2 — Hedge Fund Intelligence Platform")
    parser.add_argument("--ticker", required=True, help="Stock ticker (e.g., RELIANCE.NS, AAPL)")
    parser.add_argument("--exchange", default="IN", choices=["IN", "US"], help="Exchange: IN or US")
    parser.add_argument("--duration", type=int, default=18, help="Investment horizon in months")
    parser.add_argument("--depth", default="balanced", choices=["quick", "balanced", "premium"],
                        help="Analysis depth")
    parser.add_argument("--no-debate", action="store_true", help="Skip debate, go straight to CIO")
    parser.add_argument("--format", default="rich", choices=["rich", "json"],
                        help="Output format")
    parser.add_argument("--output", type=str, default=None, help="Save JSON output to file")
    parser.add_argument("--config", type=str, default="config/settings.yaml", help="Config file path")
    args = parser.parse_args()

    config = load_config(args.config)

    console.print(f"\n[bold green]HFIP v2.2[/] — Analysing [cyan]{args.ticker}[/] ([cyan]{args.exchange}[/])")
    console.print(f"Duration: {args.duration} months | Depth: {args.depth}\n")

    try:
        result = asyncio.run(
            PipelineOrchestrator(config).run(
                args.ticker, args.exchange,
                args.duration, args.depth,
                skip_debate=args.no_debate
            )
        )

        if args.format == "json":
            output = json.dumps(result, default=str, indent=2)
            console.print(output)
            if args.output:
                with open(args.output, "w") as f:
                    f.write(output)
                console.print(f"\n[green]Saved to {args.output}[/]")
        else:
            # Rich formatted output
            print_final_report(
                result["cio"],
                result.get("debate"),
                result.get("audited_bundle", {}),
                result.get("agent_reports")
            )

            if result.get("agent_reports"):
                print_agent_scores_table(result["agent_reports"])

            if args.output:
                with open(args.output, "w") as f:
                    json.dump(result, f, default=str, indent=2)
                console.print(f"\n[green]Saved JSON to {args.output}[/]")

    except Exception as e:
        logger.exception("Pipeline failed")
        console.print(f"\n[bold red]ERROR: {e}[/]")
        sys.exit(1)

if __name__ == "__main__":
    main()
