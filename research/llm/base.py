"""Abstract LLM provider interface + graceful-failure error type + usage tracking.

Every concrete provider (research/llm/openrouter.py) and every test fake must
implement `LLMProvider.complete()`. Callers (research/llm/router.py) must
always be prepared for `LLMUnavailableError` — this is the designed,
expected failure mode when no API key is configured, not an edge case.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from research.config import LLM_USAGE_LOG, MAX_LLM_CALLS_PER_DAY


class LLMUnavailableError(RuntimeError):
    """Raised (never an uncaught crash) when an LLM role cannot be fulfilled —
    no API key configured, provider errored, or the daily call cap was hit.
    Callers MUST catch this and degrade gracefully (log + skip the LLM step),
    per the Phase C spec: the rest of the pipeline must not hard-depend on a
    working LLM call to make progress."""


@dataclass(frozen=True)
class LLMResponse:
    text: str
    tokens_used: Optional[int]
    cost_usd: Optional[float]
    model_used: str


class LLMProvider(ABC):
    """Abstract provider interface. `role` is a router role name
    (researcher/experiment_designer/reviewer/analyst) passed through for
    logging/prompt-selection purposes — providers are not required to change
    behavior based on it."""

    @abstractmethod
    def complete(self, prompt: str, role: str, **kwargs) -> LLMResponse:
        raise NotImplementedError


class UsageTracker:
    """Simple JSON-file daily call counter. Not a database — this is a
    lightweight guardrail, not a billing system."""

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
            raise LLMUnavailableError(
                f"daily LLM call cap reached ({self.max_per_day}/day) — "
                "refusing further calls today."
            )
