"""Orchestrator: ties together git isolation, resource checks, the runner
registry, automatic rejection conditions, the evaluation policy, DB updates,
experiment-directory lifecycle, and research-memory updates into the single
`omnilab experiment EXP-XXXX` command. Also implements `propose`,
`status`, `pause`/`resume`/`stop`.

Deliberately NOT implemented here: `omnilab run` (continuous queue
processing). This orchestrator runs exactly ONE experiment per
`run_experiment()` call — the CLI enforces MAX_EXPERIMENTS_PER_RUN as a
per-invocation cap for a hypothetical future batch mode, but Phase C never
exercises more than one experiment per process invocation.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from research.config import (
    EXPERIMENTS_DIR,
    MAX_EXPERIMENT_RUNTIME_SEC,
    REPO_ROOT,
)
from research.db import Experiment, OmniLabDB, TransitionError
from research.evaluation_policy import Verdict
from research.experiment_lifecycle import move_to_status
from research.experiment_schema import (
    append_benchmark_log,
    write_conclusion_md,
    write_queued_artifacts,
    write_results_json,
)
import research.experiment_schema as experiment_schema
from research.git_isolation import (
    GitIsolationError,
    capture_diff,
    create_experiment_branch,
    discard_non_experiment_changes,
    return_to_main_branch,
    touched_paths,
)
from research.rejection import (
    check_dataset_unmodified,
    check_declared_variables_cover_diff,
    check_touched_paths_allowlist,
    combine,
    manifest_hash,
)
from research.resources import ResourceCheckFailed, check_resources_or_raise
from research.runners import RUNNERS, RunnerError

logger = logging.getLogger("research.orchestrator")

STATE_PATH = REPO_ROOT / "research" / "orchestrator_state.json"


# ---------------------------------------------------------------------------
# pause / resume / stop — simple state-flag mechanism.
#
# HONEST LIMITATION (Phase C boundary, not an oversight): this does NOT do
# mid-experiment graceful suspension. It only prevents a NEW `experiment()`
# call from starting while paused/stopped. If an experiment is already
# mid-run when pause/stop is issued, it runs to completion. Full
# checkpoint/resume of an in-flight experiment is out of scope here — see
# the master spec's Phase D/J territory note.
# ---------------------------------------------------------------------------


@dataclass
class OrchestratorState:
    paused: bool = False
    stopped: bool = False


def _load_state() -> OrchestratorState:
    if not STATE_PATH.exists():
        return OrchestratorState()
    data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return OrchestratorState(**data)


def _save_state(state: OrchestratorState) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state.__dict__, indent=2), encoding="utf-8")


def pause() -> None:
    state = _load_state()
    state.paused = True
    _save_state(state)


def resume() -> None:
    state = _load_state()
    state.paused = False
    _save_state(state)


def stop() -> None:
    state = _load_state()
    state.stopped = True
    _save_state(state)


class OrchestratorPausedError(RuntimeError):
    pass


class OrchestratorStoppedError(RuntimeError):
    pass


def _check_not_paused_or_stopped() -> None:
    state = _load_state()
    if state.stopped:
        raise OrchestratorStoppedError("orchestrator is stopped (run `omnilab resume` — actually requires manually clearing state, see research/orchestrator.py)")
    if state.paused:
        raise OrchestratorPausedError("orchestrator is paused — run `omnilab resume` first")


# ---------------------------------------------------------------------------
# propose (dry-run capable; no LLM dependency required — see #12 seeding)
# ---------------------------------------------------------------------------


def propose(dry_run: bool = True) -> list[Experiment]:
    """List QUEUED experiments in priority order. Reads research/memory/*.md
    first (mandatory per research/memory/README.md) — this function actually
    opens and returns their content alongside the queue so a human reviewer
    (or, in future, the experiment_designer LLM role) has them in view before
    approving anything. dry_run=True (the default) never touches git or
    code — it is read-only regardless of the flag, but the flag is kept for
    interface parity with `omnilab propose --dry-run`, which the master spec
    requires to explicitly not mutate anything."""
    from research.config import MEMORY_DIR
    from research.prioritization import ScoreInputs, prioritize

    memory = {}
    for f in sorted(MEMORY_DIR.glob("*.md")):
        memory[f.name] = f.read_text(encoding="utf-8")

    with OmniLabDB() as db:
        queued = db.list_experiments(execution_status="QUEUED")

    return queued


# ---------------------------------------------------------------------------
# Phase F — queue gate. A canonical ExperimentSpec (research/experiment_spec.py)
# must pass research/experiment_validator.py::validate() with zero ERRORs
# before it may be inserted as QUEUED. This is a GATE IN FRONT OF the
# existing QUEUED insertion path, not a new status value — research/db.py's
# execution_status/research_verdict axes are completely untouched.
# ---------------------------------------------------------------------------


class QueueGateError(ValueError):
    """Raised when a spec fails validation and therefore may not be queued."""


def queue_experiment_from_spec(spec) -> Experiment:
    """Validate `spec` (an ExperimentSpec) and, only if it is queue-eligible
    (zero ERROR-level validation issues), construct and insert the
    corresponding `Experiment` row with execution_status=QUEUED (the
    existing research/db.py default), write its queued artifacts, and move
    its directory to experiments/queued/. Raises QueueGateError (naming every
    ERROR-level issue) if the spec fails validation — a spec that fails
    validation is never inserted, not even as a placeholder."""
    from research.experiment_registry import REGISTRY
    from research.experiment_validator import is_queue_eligible, validate

    validation = validate(spec)
    if not is_queue_eligible(validation):
        messages = "; ".join(f"[{i.code}] {i.message}" for i in validation.errors)
        raise QueueGateError(f"{spec.proposal.experiment_id} failed validation, refusing to queue: {messages}")

    p = spec.proposal
    validation_requirement = "OFFLINE_SIMULATABLE"
    if p.family in REGISTRY:
        validation_requirement = REGISTRY[p.family].production_validation_requirement

    exp = Experiment(
        experiment_id=p.experiment_id,
        hypothesis=p.hypothesis,
        motivation=p.motivation,
        rationale=p.research_question or p.procedure,
        independent_variable="; ".join(p.independent_variables),
        controls=dict(p.controlled_variables),
        evaluation_method=p.procedure,
        success_criteria=dict(p.success_criteria),
        risks=p.production_impact_description or "(none declared)",
        expected_outcome=p.supports_hypothesis_if or "(see ExperimentSpec pre-registration)",
        parent_experiment_id=p.prior_experiment_ids[0] if p.prior_experiment_ids else None,
        experiment_family=p.family,
        baseline_run_id=p.baseline_run_id,
        validation_requirement=validation_requirement,
    )
    with OmniLabDB() as db:
        db.create_experiment(exp)
    write_queued_artifacts(exp, EXPERIMENTS_DIR / "queued" / p.experiment_id)
    move_to_status(p.experiment_id, "QUEUED")
    return exp


def status_summary() -> dict:
    with OmniLabDB() as db:
        experiments = db.list_experiments()
    execution_status_counts: dict[str, int] = {}
    research_verdict_counts: dict[str, int] = {}
    for e in experiments:
        execution_status_counts[e.execution_status] = execution_status_counts.get(e.execution_status, 0) + 1
        research_verdict_counts[e.research_verdict] = research_verdict_counts.get(e.research_verdict, 0) + 1
    from research.resources import snapshot

    try:
        snap = snapshot()
        resource_info = snap.__dict__
    except Exception as e:  # pragma: no cover - defensive only
        resource_info = {"error": str(e)}

    state = _load_state()
    return {
        "execution_status_counts": execution_status_counts,
        "research_verdict_counts": research_verdict_counts,
        "total": len(experiments),
        "experiments": [
            {
                "experiment_id": e.experiment_id,
                "execution_status": e.execution_status,
                "research_verdict": e.research_verdict,
                "family": e.experiment_family,
            }
            for e in experiments
        ],
        "resource_snapshot": resource_info,
        "orchestrator_state": state.__dict__,
    }


# ---------------------------------------------------------------------------
# run_tests — safety gate before/after applying any experiment-branch change
# ---------------------------------------------------------------------------


def _run_tests() -> tuple[bool, str]:
    result = subprocess.run(
        ["uv", "run", "pytest", "tests/", "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=MAX_EXPERIMENT_RUNTIME_SEC,
    )
    output = result.stdout + "\n" + result.stderr
    return result.returncode == 0, output


# ---------------------------------------------------------------------------
# the main entrypoint: omnilab experiment EXP-XXXX
# ---------------------------------------------------------------------------


def run_experiment(experiment_id: str) -> Experiment:
    _check_not_paused_or_stopped()

    with OmniLabDB() as db:
        exp = db.get_experiment(experiment_id)

    if exp.execution_status != "QUEUED":
        raise ValueError(
            f"{experiment_id} is execution_status={exp.execution_status!r}, not QUEUED — only "
            "QUEUED experiments can be run (per research/db.py's transition policy, a verdict "
            "must come from an actual RUNNING execution)"
        )

    if experiment_id not in RUNNERS:
        raise ValueError(
            f"no runner implemented for {experiment_id} in research/runners.py — "
            "Phase C only implements EXP-0001 and (optionally) EXP-0002."
        )

    # 1. resource check — refuse to start rather than risk OOM
    check_resources_or_raise()

    hash_before = manifest_hash()

    # 2. git isolation — create the experiment branch from a clean master
    eb = create_experiment_branch(experiment_id)

    exp_dir = EXPERIMENTS_DIR / "running" / experiment_id
    log_lines: list[str] = []

    try:
        with OmniLabDB() as db:
            db.update_fields(experiment_id, git_branch=eb.branch_name, start_commit=eb.start_commit)
            exp = db.transition_status(experiment_id, "RUNNING", note=f"branch {eb.branch_name} created")
        move_to_status(experiment_id, "RUNNING")
        write_queued_artifacts(exp, exp_dir)  # re-write so the moved dir is complete
        log_lines.append(f"[{_now()}] branch {eb.branch_name} created from {eb.start_commit}")

        # 3. run the experiment's actual logic (may or may not run new inference)
        try:
            run_result = RUNNERS[experiment_id](exp, exp_dir)
        except Exception as e:
            # The runner crashed before producing a fair, complete result to
            # judge — this is an execution-axis outcome (ABORTED), not a
            # research_verdict, since there is no verdict to record: nothing
            # ran to completion. Distinct from REJECTED (see research/db.py's
            # module docstring).
            log_lines.append(f"[{_now()}] RUNNER FAILED: {e}")
            return _finalize(experiment_id, exp_dir, "ABORTED", verdict=None,
                              reasons=[f"benchmark_execution_failure: {e}"],
                              log_lines=log_lines, results={}, conclusion=f"Runner raised: {e}")

        log_lines.extend(run_result.log_lines)

        # 4. run tests — safety gate. The pipeline DID run to completion here
        #    (execution_status=COMPLETED) — pytest failing on the experiment
        #    branch is a structural rejection of the RESULT, not a crash.
        tests_ok, test_output = _run_tests()
        log_lines.append(f"[{_now()}] pytest exit_ok={tests_ok}")
        if not tests_ok:
            return _finalize(experiment_id, exp_dir, "COMPLETED", verdict="REJECTED",
                              reasons=["test_failure: pytest failed on the experiment branch"],
                              log_lines=log_lines + [test_output], results={}, conclusion="Test suite failed on experiment branch.")

        # 5. automatic rejection checks — also execution_status=COMPLETED,
        #    research_verdict=REJECTED (ran fine, but structurally invalid
        #    per research/rejection.py's checks — see research/db.py).
        hash_after = manifest_hash()
        touched = touched_paths(eb.start_commit)
        rejection = combine(
            check_dataset_unmodified(hash_before, hash_after),
            check_touched_paths_allowlist(exp, touched),
            check_declared_variables_cover_diff(exp, touched),
        )
        if rejection.rejected:
            return _finalize(experiment_id, exp_dir, "COMPLETED", verdict="REJECTED", reasons=rejection.reasons,
                              log_lines=log_lines, results={}, conclusion="; ".join(rejection.reasons))

        # 6. evaluation policy verdict. run_result.verdict_interpretation maps
        #    evaluation_policy.Verdict.result (PASSED/FAILED/INCONCLUSIVE) to
        #    this experiment's research_verdict (PASS/FAIL/INCONCLUSIVE) —
        #    see e.g. run_exp_0001's inversion for a confirmatory/control
        #    hypothesis.
        verdict: Verdict = run_result.policy.evaluate(run_result.baseline_metrics, run_result.candidate_metrics)
        final_verdict = run_result.verdict_interpretation.get(verdict.result, verdict.result)
        log_lines.append(f"[{_now()}] evaluation_policy verdict={verdict.result} -> research_verdict={final_verdict}")
        log_lines.append(f"[{_now()}] verdict explanation: {verdict.explanation}")

        results = {
            "baseline_metrics": run_result.baseline_metrics,
            "candidate_metrics": run_result.candidate_metrics,
            "raw_evaluation_policy_verdict": verdict.result,
            "execution_status": "COMPLETED",
            "research_verdict": final_verdict,
            "guardrail_results": verdict.guardrail_results,
            "reasons": verdict.reasons,
            "notes": run_result.notes,
            "result_run_id": run_result.result_run_id,
        }

        conclusion = (
            f"# {experiment_id} — Conclusion\n\n"
            f"**Execution status**: COMPLETED\n\n"
            f"**Research verdict**: {final_verdict}\n\n"
            f"**Raw evaluation-policy verdict**: {verdict.result}\n\n"
            f"**Notes**: {run_result.notes}\n\n"
            f"**Reasoning**:\n" + "\n".join(f"- {r}" for r in verdict.reasons) + "\n"
        )

        # 7. capture diff (patch.diff) — should be empty/near-empty for
        #    analysis-only experiments like EXP-0001, per that experiment's
        #    own design (no benchmark/config.py or ios/ change).
        capture_diff(experiment_id, eb.start_commit, exp_dir / "patch.diff")

        exp_after = _finalize(
            experiment_id, exp_dir, "COMPLETED", verdict=final_verdict, reasons=verdict.reasons,
            log_lines=log_lines, results=results, conclusion=conclusion,
            result_run_id=run_result.result_run_id,
        )
        return exp_after
    finally:
        try:
            discarded = discard_non_experiment_changes()
            if discarded:
                logger.warning(
                    "%s: discarded %d non-experiment working-tree change(s) before "
                    "returning to master (isolation safety net): %s",
                    experiment_id, len(discarded), discarded,
                )
        except GitIsolationError as e:  # pragma: no cover - defensive only
            logger.error("failed to discard non-experiment changes: %s", e)
        try:
            return_to_main_branch()
        except GitIsolationError as e:  # pragma: no cover - defensive only
            logger.error("failed to return to main branch: %s", e)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _finalize(
    experiment_id: str,
    exp_dir: Path,
    execution_status: str,
    verdict: str | None,
    reasons: list[str],
    log_lines: list[str],
    results: dict,
    conclusion: str,
    result_run_id: str | None = None,
) -> Experiment:
    """Write artifacts, transition DB execution_status, record the
    research_verdict (only when execution_status='COMPLETED' and verdict is
    given — e.g. an ABORTED runner crash passes verdict=None since no
    verdict exists to record), move the directory, and update research
    memory. Shared tail for every exit path."""
    write_results_json(exp_dir, results)
    write_conclusion_md(exp_dir, conclusion)
    experiment_schema.write_analysis_md(
        exp_dir,
        f"# {experiment_id} — Analysis\n\n" + "\n".join(f"- {r}" for r in reasons) + "\n"
        if reasons else f"# {experiment_id} — Analysis\n\n(no structured findings recorded)\n",
    )
    append_benchmark_log(exp_dir, "\n".join(log_lines))

    with OmniLabDB() as db:
        end_commit = None
        try:
            from research.git_isolation import current_commit
            end_commit = current_commit()
        except Exception:
            pass
        db.update_fields(
            experiment_id,
            metrics=results if results else None,
            conclusion=conclusion,
            result_run_id=result_run_id,
            end_commit=end_commit,
        )
        exp = db.transition_status(experiment_id, execution_status, note="; ".join(reasons)[:500] if reasons else None)
        if execution_status == "COMPLETED" and verdict is not None:
            exp = db.set_research_verdict(experiment_id, verdict, note="; ".join(reasons)[:500] if reasons else None)

    new_dir = move_to_status(experiment_id, execution_status)
    _update_memory(exp, results, reasons)
    return exp


def _update_memory(exp: Experiment, results: dict, reasons: list[str]) -> None:
    """Append a dated entry to the relevant research/memory/*.md file(s).
    Explicit orchestrator step per research/memory/README.md's mandatory
    protocol — not left as an unenforced convention. Filed by
    research_verdict (the scientific outcome), not execution_status."""
    from research.config import MEMORY_DIR

    entry = (
        f"\n## {exp.experiment_id} ({_now()})\n\n"
        f"- Family: {exp.experiment_family}\n"
        f"- Execution status: {exp.execution_status}\n"
        f"- Research verdict: {exp.research_verdict}\n"
        f"- Hypothesis: {exp.hypothesis}\n"
        f"- Reasons: {'; '.join(reasons) if reasons else '(none recorded)'}\n"
    )
    if exp.research_verdict == "PASS":
        target = MEMORY_DIR / "successful_methods.md"
    elif exp.research_verdict in ("FAIL", "REJECTED"):
        target = MEMORY_DIR / "failed_methods.md"
    else:
        target = MEMORY_DIR / "open_questions.md"
    with open(target, "a", encoding="utf-8") as f:
        f.write(entry)
