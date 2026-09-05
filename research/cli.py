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


def _load_dotenv() -> None:
    """Minimal, dependency-free .env loading, same as research/llm/smoke_test.py."""
    import os
    from pathlib import Path

    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


def _setup_dry_run_execution(args: argparse.Namespace, roles_to_snapshot: tuple = ("researcher", "reviewer")):
    """Canonical initialization for ANY live Phase H call (`omnilab dry-run`
    and `omnilab dry-run-review` both call this -- the single, non-duplicated
    setup path is the whole point: a prior reviewer-only re-run failed
    because a standalone script bypassed this and forgot .env loading,
    causing a local-attempt-counter increment with zero real HTTP requests).

    Handles: .env loading, the --authorize refusal gate, the optional public
    catalog fetch, authorization/provider/router/budget construction, and
    per-role catalog-snapshot persistence. Returns
    `(authorization, router, run_budget, dry_run_budget, model_catalog)` or
    `None` if not authorized (caller should print its own refusal message
    and return 1)."""
    from research.dry_run.budget import DryRunCallBudget
    from research.llm.authorization import LLMCallAuthorization
    from research.llm.base import RunBudget, UsageTracker
    from research.llm.openrouter import OpenRouterProvider
    from research.llm.router import LLMRouter

    if not args.authorize:
        return None

    _load_dotenv()

    model_catalog = None
    if args.structured_output:
        # Public, unauthenticated GET -- no API key attached, not a chat
        # completion, does not touch UsageTracker/dry_run_budget/run_budget.
        # Fetched here (not inside research/dry_run/pipeline.py) so the
        # pipeline module itself never performs its own network I/O.
        import requests

        catalog_resp = requests.get("https://openrouter.ai/api/v1/models", timeout=30)
        catalog_resp.raise_for_status()
        model_catalog = {m["id"]: m for m in catalog_resp.json().get("data", [])}
        print(f"omnilab: fetched OpenRouter catalog ({len(model_catalog)} models, unauthenticated GET, "
              "not counted against LLM call budget)")

    authorization = LLMCallAuthorization.grant(reason=args.authorize)
    provider = OpenRouterProvider()
    router = LLMRouter(provider=provider, usage_tracker=UsageTracker())
    run_budget = RunBudget(max_calls=args.max_calls)
    dry_run_budget = DryRunCallBudget(max_calls=args.max_calls)

    if model_catalog is not None:
        # Persist a small, sanitized (public-metadata-only) snapshot for
        # every relevant role's currently-configured model, at THIS decision
        # point -- independently auditable evidence for "this model
        # supported X at call time" (Phase H catalog-verification audit,
        # section 5: an earlier WebFetch/LLM-summarized check made a claim
        # no raw snapshot survived to verify or refute).
        from research.llm.model_catalog import (
            ModelCapabilityError,
            ModelNotFreeError,
            evaluate_model_for_role,
            save_catalog_snapshot,
        )

        for role_name in roles_to_snapshot:
            preferred = router._role_config(role_name).preferred_model
            entry = model_catalog.get(preferred)
            try:
                evaluate_model_for_role(role_name, preferred, entry, require_structured_output=True)
                save_catalog_snapshot(preferred, entry, eligibility_result="ELIGIBLE")
            except (ModelNotFreeError, ModelCapabilityError) as e:
                save_catalog_snapshot(preferred, entry, eligibility_result="REJECTED", rejection_reason=str(e))

    return authorization, router, run_budget, dry_run_budget, model_catalog


def cmd_dry_run(args: argparse.Namespace) -> int:
    """Phase H — `omnilab dry-run`. Structurally incapable of executing
    anything (see research/dry_run/pipeline.py's module docstring): read-only
    against research/db.py and research/memory_db.py, pure-function schema
    validation, and up to `--max-calls` (default 3) LLM calls routed through
    research/llm/router.py. Never creates a git branch, never queues an
    experiment, never touches ios/ or benchmark/config.py.

    Real network calls require explicit --authorize REASON, mirroring
    research/llm/authorization.py's "a configured API key never authorizes a
    call by itself" discipline (same pattern as research/llm/smoke_test.py's
    one deliberate LLMCallAuthorization.grant()). Without --authorize, this
    command still loads real memory context and reports it, but refuses to
    make any LLM call — this is not a partial/fake run, it is the correct,
    safe behavior for "dry-run command invoked with no explicit go-ahead."
    """
    from research.dry_run.pipeline import run_dry_run_cycle, write_artifacts

    setup = _setup_dry_run_execution(args)
    if setup is None:
        print(
            "omnilab dry-run: no --authorize REASON given — refusing to make any LLM call "
            "(a configured OPENROUTER_API_KEY never authorizes a call by itself; see "
            "research/llm/authorization.py). Re-run with --authorize \"<reason>\" to permit "
            f"up to --max-calls (default {args.max_calls}) real, budget-capped calls."
        )
        return 1
    authorization, router, run_budget, dry_run_budget, model_catalog = setup

    result = run_dry_run_cycle(
        router=router, authorized=authorization, run_budget=run_budget, dry_run_budget=dry_run_budget,
        model_catalog=model_catalog, require_structured_output=args.structured_output,
    )
    json_path, report_path = write_artifacts(result)

    print(f"Dry-run {result.dryrun_id} complete. Calls made: {result.calls_made}/{result.calls_budget}")
    print(f"Artifact: {json_path}")
    print(f"Report:   {report_path}")
    if result.stopped_reason:
        print(f"Stopped early: {result.stopped_reason}")
    print("Actually queued: NO (never calls research/orchestrator.py::queue_experiment_from_spec)")
    return 0


def cmd_dry_run_review(args: argparse.Namespace) -> int:
    """Phase H — `omnilab dry-run-review`. Reviewer-only resume mode: critique
    an ALREADY-GENERATED, immutable proposal (loaded read-only from
    `research/dry_run_proposals/<id>.json`) without re-running the researcher
    step. Uses the exact same canonical initialization as `omnilab dry-run`
    (see `_setup_dry_run_execution`) -- .env loading, authorization gate,
    catalog preflight/snapshot, budget construction -- so there is no second,
    divergent code path. Never mutates the source proposal file; writes a
    separate `<id>-review.json` artifact. Never queues, never creates
    EXP-0006, never runs a revision."""
    from research.dry_run.pipeline import run_reviewer_only, write_review_artifact

    setup = _setup_dry_run_execution(args, roles_to_snapshot=("reviewer",))
    if setup is None:
        print(
            "omnilab dry-run-review: no --authorize REASON given — refusing to make any LLM call. "
            f"Re-run with --authorize \"<reason>\" to permit up to --max-calls (default {args.max_calls}) "
            "real, budget-capped calls."
        )
        return 1
    authorization, router, run_budget, dry_run_budget, model_catalog = setup

    additional_facts = ""
    if args.facts_file:
        from pathlib import Path

        additional_facts = Path(args.facts_file).read_text(encoding="utf-8")

    result = run_reviewer_only(
        dryrun_id=args.dryrun_id, router=router, authorized=authorization,
        run_budget=run_budget, dry_run_budget=dry_run_budget,
        model_catalog=model_catalog, require_structured_output=args.structured_output,
        additional_facts=additional_facts,
    )
    path = write_review_artifact(result)

    print(f"Review of {result.dryrun_id} complete. Calls made: {result.calls_made}/{result.calls_budget}")
    print(f"Artifact: {path}")
    if result.stopped_reason:
        print(f"Stopped early: {result.stopped_reason}")
    print("Actually queued: NO (never calls research/orchestrator.py::queue_experiment_from_spec)")
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

    p_dry_run = sub.add_parser(
        "dry-run",
        help="Phase H: memory -> problem selection -> hypothesis -> proposal -> review -> "
             "(maybe one revision) -> local schema validation -> report. Structurally incapable "
             "of executing anything — there is no 'wet' mode of this command.",
    )
    p_dry_run.add_argument(
        "--authorize", default=None,
        help="explicit reason string authorizing real LLM calls this run (required for any "
             "network activity — omitting this makes zero LLM calls, per "
             "research/llm/authorization.py's no-silent-default policy)",
    )
    p_dry_run.add_argument(
        "--max-calls", type=int, default=3,
        help="hard cap on external LLM calls for this run (default 3, per Phase H's live-"
             "demonstration budget)",
    )
    p_dry_run.add_argument(
        "--structured-output", action="store_true", default=False,
        help="opt-in: fetch OpenRouter's public, unauthenticated model catalog "
             "(GET /api/v1/models — no API key, not a chat-completion request, does not "
             "consume any LLM call budget) and require the configured researcher/reviewer "
             "models to support native response_format structured output before making any "
             "chat-completion request (research/llm/model_catalog.py's pre-flight gate). "
             "A model that fails this check is rejected locally with zero network/budget "
             "impact. Off by default so pre-remediation callers see unchanged behavior.",
    )
    p_dry_run.set_defaults(func=cmd_dry_run)

    p_dry_run_review = sub.add_parser(
        "dry-run-review",
        help="Phase H reviewer-only resume: critique an already-generated, immutable proposal "
             "(research/dry_run_proposals/<id>.json) without re-running the researcher step. "
             "Same canonical initialization as 'dry-run' -- never a standalone/duplicated setup.",
    )
    p_dry_run_review.add_argument("dryrun_id", help="e.g. DRYRUN-0007 -- must already exist and have a proposal")
    p_dry_run_review.add_argument("--authorize", default=None, help="see 'dry-run --authorize'")
    p_dry_run_review.add_argument("--max-calls", type=int, default=1, help="default 1 -- reviewer-only")
    p_dry_run_review.add_argument("--structured-output", action="store_true", default=False, help="see 'dry-run --structured-output'")
    p_dry_run_review.add_argument(
        "--facts-file", default=None,
        help="optional path to a text file of additional neutral factual context appended to the "
             "reviewer prompt verbatim (e.g. verified provenance/isolation gaps) -- never a "
             "conclusion the reviewer is told to reach",
    )
    p_dry_run_review.set_defaults(func=cmd_dry_run_review)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
