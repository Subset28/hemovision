"""omnilab CLI.

Invoke as:  uv run python -m research.cli <command>

Commands:
  propose [--dry-run]     list QUEUED experiments in priority order (read-only,
                          never touches git or code regardless of the flag)
  experiment EXP-XXXX     run ONE specific approved experiment end-to-end
  status                  DB summary: queue/running/completed counts, resources
  pause / resume / stop   simple state-flag mechanism (see research/orchestrator.py
                          for the honest limitation on what this does NOT do)

Deliberately NOT implemented: `omnilab run` (continuous queue processing) —
Phase C boundary, see research/README.md.
"""

from __future__ import annotations

import argparse
import json
import sys

from research import orchestrator
from research.db import OmniLabDB


def cmd_propose(args: argparse.Namespace) -> int:
    experiments = orchestrator.propose(dry_run=args.dry_run)
    if not experiments:
        print("No QUEUED experiments.")
        return 0
    print(f"{len(experiments)} QUEUED experiment(s) (dry_run={args.dry_run}, read-only regardless):\n")
    for e in experiments:
        print(f"  {e.experiment_id} [{e.experiment_family}] {e.hypothesis[:90]}")
    return 0


def cmd_experiment(args: argparse.Namespace) -> int:
    try:
        exp = orchestrator.run_experiment(args.experiment_id)
    except Exception as e:
        print(f"ERROR running {args.experiment_id}: {e}", file=sys.stderr)
        return 1
    print(f"{exp.experiment_id}: execution_status={exp.execution_status} research_verdict={exp.research_verdict}")
    print(f"conclusion: {exp.conclusion[:300] if exp.conclusion else '(none)'}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    summary = orchestrator.status_summary()
    print(json.dumps(summary, indent=2, default=str))
    return 0


def cmd_pause(args: argparse.Namespace) -> int:
    orchestrator.pause()
    print("orchestrator paused (new `experiment` calls will refuse to start).")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    orchestrator.resume()
    print("orchestrator resumed.")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    orchestrator.stop()
    print("orchestrator stopped (new `experiment` calls will refuse to start until state is manually reset).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="omnilab")
    sub = parser.add_subparsers(dest="command", required=True)

    p_propose = sub.add_parser("propose", help="list QUEUED experiments in priority order")
    p_propose.add_argument("--dry-run", action="store_true", default=True)
    p_propose.set_defaults(func=cmd_propose)

    p_exp = sub.add_parser("experiment", help="run one approved experiment end-to-end")
    p_exp.add_argument("experiment_id")
    p_exp.set_defaults(func=cmd_experiment)

    p_status = sub.add_parser("status", help="DB + resource summary")
    p_status.set_defaults(func=cmd_status)

    p_pause = sub.add_parser("pause")
    p_pause.set_defaults(func=cmd_pause)
    p_resume = sub.add_parser("resume")
    p_resume.set_defaults(func=cmd_resume)
    p_stop = sub.add_parser("stop")
    p_stop.set_defaults(func=cmd_stop)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
