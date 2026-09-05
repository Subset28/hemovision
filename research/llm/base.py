"""Abstract LLM provider interface + graceful-failure error types + usage
tracking.

Every concrete provider (research/llm/openrouter.py) and every test fake must
implement `LLMProvider.complete()`. Callers (research/llm/router.py) must
always be prepared for `LLMUnavailableError` — this is the designed,
expected failure mode when no API key is configured, the budget is
exhausted, or a call is not authorized, not an edge case.

Phase G extends this Phase C skeleton with:
  - `ErrorCategory` — a small, closed vocabulary of failure reasons so
    callers (and the router's retry/fallback logic) can tell "auth is
    broken" apart from "the network hiccuped" without parsing message text.
  - `BudgetExceededError` / `PerRunBudgetExceededError` — distinct,
    catchable subclasses of `LLMUnavailableError` so a caller can tell
    "budget" apart from "provider failure" if it cares, while everything
    that already just catches `LLMUnavailableError` keeps working unchanged.
  - `RunBudget` — a tighter, in-memory, per-process-run call cap, separate
    from `UsageTracker`'s persisted daily cap (see research/config.py's
    `MAX_LLM_CALLS_PER_RUN` vs `MAX_LLM_CALLS_PER_DAY`). A "run" is a single
    orchestrator/CLI invocation; there is deliberately no cross-process
    persistence for this counter — that's what the daily tracker is for.

Nothing outside `research/llm/` should ever touch a raw OpenRouter JSON
response shape — `LLMResponse` is the only value that crosses that boundary.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Optional

from research.config import LLM_USAGE_LOG, MAX_LLM_CALLS_PER_DAY, MAX_LLM_CALLS_PER_RUN


class ErrorCategory(str, Enum):
    """Closed vocabulary of LLM-call failure reasons (Phase G section 2).
    Provider code (research/llm/openrouter.py) is responsible for mapping
    every failure it can observe into exactly one of these — callers should
    never need to inspect a raw exception message to decide whether a
    failure is worth retrying."""

    TIMEOUT = "TIMEOUT"
    HTTP_ERROR = "HTTP_ERROR"
    RATE_LIMIT = "RATE_LIMIT"
    AUTH_ERROR = "AUTH_ERROR"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    MALFORMED_RESPONSE = "MALFORMED_RESPONSE"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    NETWORK_ERROR = "NETWORK_ERROR"
    UNKNOWN = "UNKNOWN"


# Error categories that are considered genuinely transient and therefore
# eligible for a bounded retry (Phase G section 11). Everything else (auth,
# malformed response, model-unavailable, empty response) fails immediately —
# retrying those wastes budget for a call that cannot succeed differently.
RETRYABLE_CATEGORIES = frozenset({ErrorCategory.TIMEOUT, ErrorCategory.NETWORK_ERROR})


class LLMUnavailableError(RuntimeError):
    """Raised (never an uncaught crash) when an LLM role cannot be fulfilled —
    no API key configured, provider errored, or a call budget was hit.
    Callers MUST catch this and degrade gracefully (log + skip the LLM step),
    per the Phase C spec: the rest of the pipeline must not hard-depend on a
    working LLM call to make progress.

    Carries an optional `category` (see `ErrorCategory`) so callers that want
    finer-grained handling than "it failed" can inspect it without parsing
    the message string. Message text is guaranteed to never contain a secret
    value (see research/llm/openrouter.py's redaction discipline)."""

    def __init__(
        self,
        message: str,
        category: ErrorCategory = ErrorCategory.UNKNOWN,
        diagnostics: "Optional[dict]" = None,
    ):
        super().__init__(message)
        self.category = category
        # Safe, non-secret diagnostic detail (narrow remediation build --
        # see reports/openrouter/OPENROUTER_INTEGRATION_AUDIT.md section 11).
        # NEVER contains an API key, an Authorization header value, raw
        # environment, private context, or the full prompt/completion text
        # -- see research/llm/openrouter.py::_build_diagnostics for exactly
        # what is (and is not) placed here.
        self.diagnostics: dict = diagnostics or {}


class BudgetExceededError(LLMUnavailableError):
    """Raised when the persisted daily call cap (UsageTracker) is hit."""

    def __init__(self, message: str):
        super().__init__(message, category=ErrorCategory.UNKNOWN)


class PerRunBudgetExceededError(LLMUnavailableError):
    """Raised when the tighter, in-memory per-run call cap (RunBudget) is
    hit. Distinct from BudgetExceededError so a caller can tell "this run
    itself is being too chatty" apart from "we're out of calls for today"."""

    def __init__(self, message: str):
        super().__init__(message, category=ErrorCategory.UNKNOWN)


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tokens_used: Optional[int]
    cost_usd: Optional[float]
    model_used: str
    # Phase G additions — all optional/defaulted so existing call sites
    # (LLMResponse(text=..., tokens_used=..., cost_usd=..., model_used=...))
    # keep working unchanged.
    provider: str = "openrouter"
    request_id: Optional[str] = None
    latency_ms: Optional[float] = None
    error_category: Optional[ErrorCategory] = None  # None on success
    # Safe diagnostic detail captured for a SUCCESSFUL call (narrow
    # remediation build) -- same safe-field discipline as
    # LLMUnavailableError.diagnostics; see research/llm/openrouter.py.
    diagnostics: Optional[dict] = None


class LLMProvider(ABC):
    """Abstract provider interface. `role` is a router role name
    (researcher/experiment_designer/reviewer/analyst) passed through for
    logging/prompt-selection purposes — providers are not required to change
    behavior based on it.

    `complete()` MUST require an explicit `authorized` argument with no
    default that silently authorizes a real network call (Phase G section
    6) — see research/llm/authorization.py."""

    @abstractmethod
    def complete(self, prompt: str, role: str, **kwargs) -> LLMResponse:
        raise NotImplementedError


class UsageTracker:
    """Simple JSON-file daily call counter. Not a database — this is a
    lightweight guardrail, not a billing system.

    Policy (Phase G section 5, stated explicitly): `record_call()` is called
    for BOTH a successful and a failed call attempt. A failed call still
    costs a real network round-trip (and, for a real provider, often
    provider-side accounting) even when it returns an error — so it counts
    against the budget the same as a success. This is a deliberate choice,
    not an oversight: it prevents a retry/fallback storm from looking free
    just because every attempt happened to fail.

    Persistence: a plain JSON file, re-read on every check/record call so
    the counter survives process restarts. This is a single-process CLI
    tool, not a concurrent service — read-check-write is sufficient and
    deliberately not made more complicated with file locking."""

    def __init__(self, path: Path = LLM_USAGE_LOG, max_per_day: int = MAX_LLM_CALLS_PER_DAY):
        self.path = Path(path)
        self.max_per_day = max_per_day

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def calls_today(self) -> int:
        today = date.today().isoformat()
        return self._load().get(today, 0)

    def record_call(self) -> int:
        today = date.today().isoformat()
        data = self._load()
        data[today] = data.get(today, 0) + 1
        self._save(data)
        return data[today]

    def check_budget(self) -> None:
        if self.calls_today() >= self.max_per_day:
            raise BudgetExceededError(
                f"daily LLM call cap reached ({self.max_per_day}/day) — "
                "refusing further calls today."
            )

    def remaining_today(self) -> int:
        return max(0, self.max_per_day - self.calls_today())


class RunBudget:
    """Tighter, in-memory, per-process-run call cap (Phase G section 5).

    Deliberately NOT persisted to disk: a "run" is one orchestrator/CLI
    process invocation. Cross-process accumulation is exactly what
    `UsageTracker`'s persisted daily cap already covers — adding a second
    persisted counter here would just be the same guardrail twice. Construct
    a fresh `RunBudget` per run and pass it through to every LLM call made
    during that run."""

    def __init__(self, max_calls: int = MAX_LLM_CALLS_PER_RUN):
        self.max_calls = max_calls
        self.calls_made = 0

    def check(self) -> None:
        if self.calls_made >= self.max_calls:
            raise PerRunBudgetExceededError(
                f"per-run LLM call cap reached ({self.max_calls}/run) — "
                "refusing further calls this run."
            )

    def record(self) -> int:
        self.calls_made += 1
        return self.calls_made

    def remaining(self) -> int:
        return max(0, self.max_calls - self.calls_made)
