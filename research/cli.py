"""omnilab CLI.

Invoke as:  uv run python -m research.cli <command>

Commands:
  propose [--dry-run]        list QUEUED experiments in priority order (read-only,
                             never touches git or code regardless of the flag)
  experiment run EXP-XXXX    run ONE specific approved experiment end-to-end (Phase C)
  experiment validate EXP-XXXX  Phase F: validate EXP-XXXX's canonical spec
                             (research/experiment_specs/EXP-XXXX.json) — errors,
                             warnings, NEEDS_HUMAN_REVIEW flags, queue eligibility.
                             No LLM call anywhere in this path.
  experiment show EXP-XXXX [--json]  Phase F: print EXP-XXXX's normalized
                             canonical schema fields (hypothesis, evidence
                             references, pre-registered success criteria,
                             validation summary, queue eligibility).
  status                     DB summary: queue/running/completed counts, resources
  pause / resume / stop      simple state-flag mechanism (see research/orchestrator.py
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
from research.memory_context import write_context_packet
from research.memory_db import MemoryDB
from research.memory_query import QUESTION_TYPES, records_for_experiment, render_query_result


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


def cmd_memory_query(args: argparse.Namespace) -> int:
    db = MemoryDB()
    try:
        if args.question_type == "for-experiment":
            if not args.experiment_id:
                print("ERROR: --experiment-id is required for 'for-experiment'", file=sys.stderr)
                return 1
            result = records_for_experiment(db, args.experiment_id)
        else:
            result = QUESTION_TYPES[args.question_type](db)
    finally:
        db.close()
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(render_query_result(result))
    return 0


def cmd_memory_context(args: argparse.Namespace) -> int:
    db = MemoryDB()
    try:
        packet = write_context_packet(db)
    finally:
        db.close()
    if args.json:
        print(json.dumps(packet, indent=2, default=str))
    else:
        print(f"Context packet written to research/memory/CONTEXT_PACKET.md "
              f"({len(packet['rejected_directions'])} rejected direction(s), "
              f"{len(packet['unresolved_questions'])} open question(s)).")
    return 0


def _load_experiment_spec(experiment_id: str):
    """Load a canonical spec (backfilled or queued) for `experiment_id`.
    Phase F — research/experiment_specs/EXP-XXXX.json."""
    from research.backfill_experiment_specs import load_spec
    return load_spec(experiment_id)


def cmd_experiment_validate(args: argparse.Namespace) -> int:
    from research.experiment_validator import is_queue_eligible, validate

    try:
        spec = _load_experiment_spec(args.experiment_id)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    result = validate(spec)
    print(f"{args.experiment_id}: schema_version={spec.proposal.schema_version} status={spec.status}")
    print(f"  errors: {len(result.errors)}  warnings: {len(result.warnings)}  needs_human_review: {len(result.needs_human_review)}")
    for issue in result.issues:
        print(f"  [{issue.level}] {issue.code}: {issue.message}")
    print(f"queue_eligible: {is_queue_eligible(result)}")
    return 0 if is_queue_eligible(result) else 1


def cmd_experiment_show(args: argparse.Namespace) -> int:
    from research.experiment_validator import is_queue_eligible, validate

    try:
        spec = _load_experiment_spec(args.experiment_id)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(spec.to_json())
        return 0

    p = spec.proposal
    print(f"=== {p.experiment_id}: {p.title} ===")
    print(f"schema_version={p.schema_version}  family={p.family}  spec_status={spec.status}")
    print(f"\nHypothesis: {p.hypothesis}")
    print(f"Motivation: {p.motivation}")
    print(f"Research question: {p.research_question}")
    print(f"\nEvidence references: {list(p.evidence_references) or '(none)'}")
    print(f"Prior experiments: {list(p.prior_experiment_ids) or '(none)'}")
    print(f"\nBaseline run: {p.baseline_run_id}")
    print(f"Independent variables: {list(p.independent_variables)}")
    print(f"Dependent variables: {list(p.dependent_variables)}")
    print(f"Control condition: {p.control_condition}")
    print(f"\nPre-registered success criteria:")
    for k, v in p.success_criteria.items():
        print(f"  {k}: {v}")
    print(f"\nInterpretation (pre-registered):")
    print(f"  supports_hypothesis_if: {p.supports_hypothesis_if}")
    print(f"  rejects_hypothesis_if: {p.rejects_hypothesis_if}")
    print(f"  inconclusive_if: {p.inconclusive_if}")
    print(f"\nRisk/safety: production_impact={p.production_impact} external_api_required={p.external_api_required} "
          f"mac_iphone_required={p.mac_iphone_required} data_privacy_classification={p.data_privacy_classification}")
    print(f"Amendments: {len(spec.amendments)}")
    if spec.result.execution_status:
        print(f"\nResult: execution_status={spec.result.execution_status} research_verdict={spec.result.research_verdict}")
    else:
        print("\nResult: (not yet executed)")
    result = validate(spec)
    print(f"\nvalidation: errors={len(result.errors)} warnings={len(result.warnings)} needs_human_review={len(result.needs_human_review)}")
    print(f"queue_eligible: {is_queue_eligible(result)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="omnilab")
    sub = parser.add_subparsers(dest="command", required=True)

    p_propose = sub.add_parser("propose", help="list QUEUED experiments in priority order")
    p_propose.add_argument("--dry-run", action="store_true", default=True)
    p_propose.set_defaults(func=cmd_propose)

    p_exp = sub.add_parser("experiment", help="run/validate/show an experiment (Phase C execution + Phase F canonical schema)")
    exp_sub = p_exp.add_subparsers(dest="experiment_command", required=True)

    p_exp_run = exp_sub.add_parser("run", help="run one approved experiment end-to-end (Phase C)")
    p_exp_run.add_argument("experiment_id")
    p_exp_run.set_defaults(func=cmd_experiment)

    p_exp_validate = exp_sub.add_parser("validate", help="Phase F: validate EXP-XXXX's canonical spec (no LLM call)")
    p_exp_validate.add_argument("experiment_id")
    p_exp_validate.set_defaults(func=cmd_experiment_validate)

    p_exp_show = exp_sub.add_parser("show", help="Phase F: print EXP-XXXX's normalized canonical schema fields")
    p_exp_show.add_argument("experiment_id")
    p_exp_show.add_argument("--json", action="store_true", default=False)
    p_exp_show.set_defaults(func=cmd_experiment_show)

    p_status = sub.add_parser("status", help="DB + resource summary")
    p_status.set_defaults(func=cmd_status)

    p_pause = sub.add_parser("pause")
    p_pause.set_defaults(func=cmd_pause)
    p_resume = sub.add_parser("resume")
    p_resume.set_defaults(func=cmd_resume)
    p_stop = sub.add_parser("stop")
    p_stop.set_defaults(func=cmd_stop)

    p_memory = sub.add_parser("memory", help="Phase E structured research memory")
    memory_sub = p_memory.add_subparsers(dest="memory_command", required=True)

    p_mem_query = memory_sub.add_parser("query", help="deterministic query over research/memory.db")
    p_mem_query.add_argument(
        "question_type",
        choices=list(QUESTION_TYPES.keys()) + ["for-experiment"],
    )
    p_mem_query.add_argument("--experiment-id", default=None, help="required for 'for-experiment'")
    p_mem_query.add_argument("--json", action="store_true", default=False)
    p_mem_query.set_defaults(func=cmd_memory_query)

    p_mem_context = memory_sub.add_parser("context", help="regenerate research/memory/CONTEXT_PACKET.md")
    p_mem_context.add_argument("--json", action="store_true", default=False)
    p_mem_context.set_defaults(func=cmd_memory_context)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
