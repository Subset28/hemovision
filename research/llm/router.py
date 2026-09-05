"""Role -> model routing, configurable via research/llm/roles.yaml.

Tries the role's `preferred_model` first; on any LLMUnavailableError, logs
the failure and tries each of `fallback_models` in order; if all fail
(including the common case of "no API key at all"), raises
LLMUnavailableError — callers must catch this and continue without the LLM
step. Never crashes the CLI.

Phase G additions on top of the Phase C skeleton:
  - `authorized` is now a REQUIRED keyword-only argument (no silently-safe
    default — see research/llm/authorization.py) and is checked before
    anything else, including the budget check.
  - Budget accounting now happens after EVERY attempt (success or failure),
    not just successes — see research/llm/base.py::UsageTracker's docstring
    for the explicit policy rationale.
  - An optional `run_budget` (research/llm/base.py::RunBudget) enforces the
    tighter per-run cap alongside the persisted daily cap.
  - `roles.yaml` entries may use either the new field names
    (`preferred_model` / `fallback_models` (list) / `max_tokens` / `timeout`
    / `call_budget_category`) or the original Phase C names (`primary` /
    `fallback` (single)) — `_role_config()` normalizes both so existing
    fixtures/tests keep working unchanged.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from research.config import LLM_ROLES_CONFIG
from research.llm.authorization import AuthorizationLike, require_authorization
from research.llm.base import (
    LLMProvider,
    LLMResponse,
    LLMUnavailableError,
    RunBudget,
    UsageTracker,
)

logger = logging.getLogger("research.llm.router")


class RoleConfig:
    __slots__ = ("preferred_model", "fallback_models", "max_tokens", "timeout", "call_budget_category")

    def __init__(self, preferred_model, fallback_models, max_tokens, timeout, call_budget_category):
        self.preferred_model = preferred_model
        self.fallback_models = fallback_models
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.call_budget_category = call_budget_category

    def models_in_order(self):
        yield self.preferred_model
        for m in self.fallback_models:
            if m:
                yield m


class LLMRouter:
    def __init__(
        self,
        provider: LLMProvider,
        roles_config_path: Path = LLM_ROLES_CONFIG,
        usage_tracker: Optional[UsageTracker] = None,
    ):
        self.provider = provider
        self.roles_config_path = Path(roles_config_path)
        self.usage_tracker = usage_tracker or UsageTracker()
        self._roles: dict = {}
        if self.roles_config_path.exists():
            self._roles = yaml.safe_load(self.roles_config_path.read_text(encoding="utf-8")) or {}

    def _role_config(self, role: str) -> RoleConfig:
        cfg = self._roles.get(role)
        if not cfg:
            raise LLMUnavailableError(f"no roles.yaml entry for role {role!r}")

        preferred = cfg.get("preferred_model") or cfg.get("primary")
        if not preferred:
            raise LLMUnavailableError(f"roles.yaml entry for role {role!r} has no preferred_model/primary")

        fallback_models = cfg.get("fallback_models")
        if fallback_models is None:
            single = cfg.get("fallback")
            fallback_models = [single] if single else []

        return RoleConfig(
            preferred_model=preferred,
            fallback_models=list(fallback_models),
            max_tokens=cfg.get("max_tokens"),
            timeout=cfg.get("timeout"),
            call_budget_category=cfg.get("call_budget_category", "default"),
        )

    def complete(
        self,
        prompt: str,
        role: str,
        *,
        authorized: AuthorizationLike = None,
        run_budget: Optional[RunBudget] = None,
        messages: Optional[list] = None,
        **kwargs,
    ) -> LLMResponse:
        """Route a completion request for `role`. Raises LLMUnavailableError
        (never a bare exception) if no model can serve the request — callers
        must catch this and proceed without the LLM step.

        `authorized` is required (Phase G section 6) and is checked before
        the budget or any model is tried — an unauthorized call never touches
        the daily/per-run counters and never reaches the provider."""
        require_authorization(authorized)

        self.usage_tracker.check_budget()
        if run_budget is not None:
            run_budget.check()

        role_cfg = self._role_config(role)
        errors: list[str] = []

        for model in role_cfg.models_in_order():
            call_kwargs = dict(kwargs)
            if role_cfg.max_tokens is not None:
                call_kwargs.setdefault("max_tokens", role_cfg.max_tokens)
            if role_cfg.timeout is not None:
                call_kwargs.setdefault("timeout_sec", role_cfg.timeout)

            try:
                response = self.provider.complete(
                    prompt, role, model=model, authorized=authorized, messages=messages, **call_kwargs
                )
            except LLMUnavailableError as e:
                # Policy (Phase G section 5): a failed attempt still counts
                # against budget — it cost a real round-trip/attempt.
                self.usage_tracker.record_call()
                if run_budget is not None:
                    run_budget.record()
                errors.append(f"{model}: {e}")
                logger.warning("LLM role=%s model=%s unavailable, falling back: %s", role, model, e)
                continue
            else:
                self.usage_tracker.record_call()
                if run_budget is not None:
                    run_budget.record()
                return response

        raise LLMUnavailableError(
            f"role {role!r} unavailable — all configured models failed: {'; '.join(errors)}"
        )
