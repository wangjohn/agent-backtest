"""Command-line entry point for offline manual-pilot support."""

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from agent_backtest import __version__
from agent_backtest.pilot import inspect_export, plan_run, validate_package

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
            "Offline manual pilot checks are available; execution remains separate.\n\n"
            f"Planned commands:\n{planned}\n\nPlan: {PLAN_URL}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"agent-backtest {__version__}")
    commands = parser.add_subparsers(dest="command")
    pilot = commands.add_parser("pilot", help="offline checks for manually authored M1 packages")
    actions = pilot.add_subparsers(dest="action", required=True)
    inspect = actions.add_parser("inspect-export", help="summarize supported Agent Archive JSONL")
    inspect.add_argument("export", type=Path)
    validate = actions.add_parser("validate", help="check frozen package and evidence consistency")
    validate.add_argument("package", type=Path)
    plan = actions.add_parser("plan", help="print 2 contestants x tasks x 3 trials; never execute")
    plan.add_argument("config", type=Path)
    plan.add_argument("packages", type=Path, nargs="+")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    try:
        if args.action == "inspect-export":
            result = inspect_export(args.export)
        elif args.action == "validate":
            result = validate_package(args.package)
        else:
            result = plan_run(args.config, args.packages)
    except (ValueError, OSError, UnicodeError) as exc:
        print(f"backtest: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    if args.action == "validate" and result["state"] != "qualified":
        return 1
    return 0
