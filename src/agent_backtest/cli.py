"""Command-line entry point.

Only ``--version`` and ``--help`` work today. The planned commands are listed
so the shape of the tool is visible; see docs/specs/v0-plan.md.
"""

import argparse
from collections.abc import Sequence

from agent_backtest import __version__

PLAN_URL = "https://github.com/wangjohn/agent-backtest/blob/main/docs/specs/v0-plan.md"

PLANNED_COMMANDS: dict[str, str] = {
    "init": "create a workspace and backtest.toml",
    "doctor": "check Docker, Harbor, agent-archive, agent CLIs, and credentials",
    "candidates": "pick sessions worth turning into tasks",
    "build": "build Harbor tasks from candidates",
    "check": "run the automatic gates on built tasks",
    "review": "approve or reject tasks",
    "run": "run contestants on approved tasks",
    "grade": "grade a finished run (rubric and pairwise layers)",
    "calibrate": "measure judge agreement with you",
    "report": "report quality and cost per task type",
}


def build_parser() -> argparse.ArgumentParser:
    planned = "\n".join(f"  {name:<11} {desc}" for name, desc in PLANNED_COMMANDS.items())
    parser = argparse.ArgumentParser(
        prog="backtest",
        description="Backtest coding agents on benchmarks built from your own past sessions.",
        epilog=(
            "agent-backtest is in early development; no commands are implemented yet.\n\n"
            f"Planned commands:\n{planned}\n\nPlan: {PLAN_URL}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"agent-backtest {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
