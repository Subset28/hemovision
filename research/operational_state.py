"""Centralized fail-closed operational-state gate (the OmniLab kill switch).

Covers EVERY state-changing or cost-incurring OmniLab operation -- not just
real benchmark execution (research/orchestrator.py::run_experiment) but also
every LLM call (researcher/reviewer/revision), queue operations, branch
creation, and future training/benchmarking code paths.

Previously (Phase C through Phase H): research/orchestrator.py's own
pause/resume/stop only gated run_experiment() -- a paused/stopped
orchestrator had ZERO effect on Phase H's dry-run LLM calls. This was
CRITICAL finding #1 in reports/phase_i/PHASE_I_READINESS_AUDIT.md
(2026-09-05). This module is the fix: ONE state file, ONE gate function,
imported and called by every protected-operation call site (see
research/dry_run/pipeline.py::_call_llm, research/orchestrator.py::
run_experiment/queue_experiment_from_spec) immediately before the actual
protected action -- never only once at CLI startup.

Fail-closed semantics:
  RUNNING  -- protected operations may proceed, subject to their OWN other
              authorization/budget/capability gates (this module grants no
              permission by itself; it only refuses when the state says no).
  PAUSED   -- no NEW protected operation may begin. An operation already
              past this checkpoint when pause is issued is not interrupted
              (no mid-flight cancellation is attempted -- same honest
              limitation research/orchestrator.py has always documented for
              run_experiment()).
  STOPPED  -- no NEW protected operation may begin. Unlike PAUSED, a plain
              resume() does NOT clear STOPPED -- only the explicit,
              reason-carrying restart_from_stopped() can.

Read-only operations (status, memory queries, deterministic validation,
report rendering) must never call check_gate() and remain available in
any state.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from research.config import REPO_ROOT

STATE_PATH = REPO_ROOT / "research" / "orchestrator_state.json"


@dataclass
class OperationalState:
    paused: bool = False
    stopped: bool = False
    last_transition: str = ""
    last_transition_reason: str = ""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_state() -> OperationalState:
    if not STATE_PATH.exists():
        return OperationalState()
    data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    # Tolerate older state files written before last_transition(_reason) existed.
    return OperationalState(
        paused=bool(data.get("paused", False)),
        stopped=bool(data.get("stopped", False)),
        last_transition=data.get("last_transition", ""),
        last_transition_reason=data.get("last_transition_reason", ""),
    )


def _save_state(state: OperationalState) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state.__dict__, indent=2), encoding="utf-8")


def current_state() -> OperationalState:
    return _load_state()


def pause(reason: str = "") -> None:
    state = _load_state()
    state.paused = True
    state.last_transition = f"PAUSE@{_now()}"
    state.last_transition_reason = reason
    _save_state(state)


def resume() -> None:
    """Clears PAUSED only. Does NOT clear STOPPED -- deliberately: STOPPED
    is meant to be harder to leave by accident than PAUSED. See
    restart_from_stopped()."""
    state = _load_state()
    state.paused = False
    state.last_transition = f"RESUME@{_now()}"
    _save_state(state)


def stop(reason: str = "") -> None:
    state = _load_state()
    state.stopped = True
    state.last_transition = f"STOP@{_now()}"
    state.last_transition_reason = reason
    _save_state(state)


def restart_from_stopped(reason: str) -> None:
    """The ONLY way to clear STOPPED. Requires a non-empty reason -- an
    explicit, audited transition, not a silent one-line flag flip."""
    if not reason or not reason.strip():
        raise ValueError("restart_from_stopped() requires a non-empty reason")
    state = _load_state()
    state.stopped = False
    state.paused = False
    state.last_transition = f"RESTART@{_now()}"
    state.last_transition_reason = reason
    _save_state(state)


class OperationalGateError(RuntimeError):
    """Base class for a protected operation refused by the operational-state
    gate. Never raised for a read-only operation -- those never call
    check_gate()."""


class OperationalPausedError(OperationalGateError):
    pass


class OperationalStoppedError(OperationalGateError):
    pass


def check_gate(operation: str = "operation") -> None:
    """Raise if the current operational state forbids a NEW protected
    operation from beginning. Call this IMMEDIATELY before the actual
    protected action (an LLM HTTP request, a DB write that queues/creates a
    branch, a training/benchmark invocation) -- not just once at CLI
    startup -- so a pause/stop issued mid-preparation still blocks the final
    step. Raises before any budget/network/DB side effect of the caller's
    own -- this function itself performs no I/O beyond reading the small
    local state file."""
    state = _load_state()
    if state.stopped:
        raise OperationalStoppedError(
            f"operational state is STOPPED -- refusing to start {operation}. "
            "Run `omnilab restart --reason \"...\"` to explicitly clear STOPPED "
            "(plain `omnilab resume` does not)."
        )
    if state.paused:
        raise OperationalPausedError(
            f"operational state is PAUSED -- refusing to start {operation}. "
            "Run `omnilab resume` first."
        )
