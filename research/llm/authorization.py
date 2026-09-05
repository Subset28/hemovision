"""Phase G — the authorization gate.

This module exists to make one fact structurally true, not just documented:
**having `OPENROUTER_API_KEY` configured does not authorize a real network
call.** A key present in the environment answers "can we?", not "should we,
right now, for this specific call?" — those are deliberately kept as two
separate, independently-checkable conditions.

`OpenRouterProvider.complete()` (research/llm/openrouter.py) and
`LLMRouter.complete()` (research/llm/router.py) both require an explicit
`authorized` argument with NO default that silently authorizes anything.
Omitting it, or passing a falsy value, refuses the call before any network
code runs — `require_authorization()` below is the single choke point both
of those call through, so the refusal logic lives in exactly one place.

`LLMCallAuthorization` is an optional richer alternative to a bare
`authorized=True` boolean — it carries a human-readable `reason` so a caller
that grants authorization (e.g. research/llm/smoke_test.py) leaves a visible,
auditable trail of *why* this particular call was allowed to happen. Passing
a plain `bool` to `require_authorization()` still works; there is no
behavioral difference for the gate itself, `reason` is purely for
observability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


class LLMCallNotAuthorizedError(RuntimeError):
    """Raised when a real LLM network call is attempted without explicit,
    per-call authorization — regardless of whether an API key is configured.
    This is a refusal, not a provider failure: it is never counted against
    any call budget (research/llm/base.py's UsageTracker/RunBudget), because
    no network round-trip was attempted."""


@dataclass(frozen=True)
class LLMCallAuthorization:
    """An explicit, auditable grant for exactly one call (or a small,
    caller-defined scope of calls). `authorized=False` (the default if you
    construct one with no arguments) is deliberately the safe default —
    constructing this dataclass does not itself authorize anything; only
    `LLMCallAuthorization.grant(reason)` does."""

    authorized: bool = False
    reason: str = ""

    @staticmethod
    def grant(reason: str) -> "LLMCallAuthorization":
        if not reason or not reason.strip():
            raise ValueError(
                "LLMCallAuthorization.grant() requires a non-empty reason — "
                "authorization must be auditable, not silent."
            )
        return LLMCallAuthorization(authorized=True, reason=reason)

    @staticmethod
    def none() -> "LLMCallAuthorization":
        return LLMCallAuthorization(authorized=False, reason="")

    def __bool__(self) -> bool:
        return self.authorized


AuthorizationLike = Union[bool, LLMCallAuthorization, None]


def require_authorization(auth: AuthorizationLike) -> None:
    """The single choke point for the authorization gate. Raises
    `LLMCallNotAuthorizedError` unless `auth` is truthy authorization.

    Accepts:
      - `None` or omitted -> always refused (no silent default).
      - `False` / `True`  -> refused / allowed.
      - `LLMCallAuthorization` -> refused / allowed per its `.authorized`.

    This function makes no network call and has no side effects other than
    raising — it is safe (and expected) to call before any budget check or
    HTTP request is attempted."""
    if auth is None:
        raise LLMCallNotAuthorizedError(
            "LLM call refused: no authorization was supplied (omitted/None). "
            "Pass authorized=True or an LLMCallAuthorization.grant(reason) "
            "explicitly — a configured API key alone never authorizes a call."
        )
    ok = bool(auth)
    if not ok:
        raise LLMCallNotAuthorizedError(
            "LLM call refused: authorized=False. A configured API key alone "
            "never authorizes a call — this must be explicitly granted per call."
        )
