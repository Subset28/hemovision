"""Role -> model routing, configurable via research/llm/roles.yaml.

Tries the role's `primary` model; on any LLMUnavailableError, logs the
failure and tries `fallback`; if both fail (including the common case of "no
API key at all"), raises LLMUnavailableError — callers must catch this and
continue without the LLM step. Never crashes the CLI.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from research.config import LLM_ROLES_CONFIG
from research.llm.base import LLMProvider, LLMResponse, LLMUnavailableError, UsageTracker

logger = logging.getLogger("research.llm.router")


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

    def _models_for_role(self, role: str) -> tuple[str, Optional[str]]:
        cfg = self._roles.get(role)
        if not cfg:
            raise LLMUnavailableError(f"no roles.yaml entry for role {role!r}")
        return cfg["primary"], cfg.get("fallback")

    def complete(self, prompt: str, role: str, **kwargs) -> LLMResponse:
        """Route a completion request for `role`. Raises LLMUnavailableError
        (never a bare exception) if no model can serve the request — callers
        must catch this and proceed without the LLM step."""
        self.usage_tracker.check_budget()

        primary, fallback = self._models_for_role(role)
        errors: list[str] = []
        for model in (m for m in (primary, fallback) if m):
            try:
                response = self.provider.complete(prompt, role, model=model, **kwargs)
                self.usage_tracker.record_call()
                return response
            except LLMUnavailableError as e:
                errors.append(f"{model}: {e}")
                logger.warning("LLM role=%s model=%s unavailable, falling back: %s", role, model, e)
                continue

        raise LLMUnavailableError(
            f"role {role!r} unavailable — all configured models failed: {'; '.join(errors)}"
        )
