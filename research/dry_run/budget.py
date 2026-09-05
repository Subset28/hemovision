"""Phase H — the dry-run-scoped external-call budget.

This is a SECOND, tighter counter than research/llm/base.py's `UsageTracker`
(persisted daily cap) and `RunBudget` (in-memory per-run cap, defaults to
`MAX_LLM_CALLS_PER_RUN` == 10). The dry-run pipeline additionally threads a
`DryRunCallBudget(max_calls=3)` through every call it makes, so the "3 live
calls max for the whole demonstration" ceiling (section 9) is enforced
independent of whatever `MAX_LLM_CALLS_PER_RUN`/`MAX_LLM_CALLS_PER_DAY`
happen to be configured to. `check()` raises BEFORE a 4th attempt regardless
of daily-budget headroom — this is checked first, before the router/provider
are ever touched, so a refusal here makes zero network calls.

Policy (matches research/llm/base.py::UsageTracker's documented policy
exactly, Phase G section 5): a FAILED call attempt still counts against this
budget — `record()` is called for both a successful and a failed attempt."""

from __future__ import annotations


class DryRunBudgetExceededError(RuntimeError):
    """Raised when the dry-run pipeline attempts a call beyond its
    configured max_calls. Never counted as a call itself — no network
    activity happens when this is raised."""


class DryRunCallBudget:
    def __init__(self, max_calls: int = 3):
        self.max_calls = max_calls
        self.calls_made = 0

    def check(self) -> None:
        if self.calls_made >= self.max_calls:
            raise DryRunBudgetExceededError(
                f"dry-run call budget reached ({self.max_calls}/{self.max_calls}) — "
                "refusing to make another LLM call this run, regardless of daily/"
                "per-run budget headroom elsewhere."
            )

    def record(self) -> int:
        self.calls_made += 1
        return self.calls_made

    def remaining(self) -> int:
        return max(0, self.max_calls - self.calls_made)
