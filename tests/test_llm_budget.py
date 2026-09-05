"""Phase G — budget/quota tests: persisted daily cap (UsageTracker) and the
tighter in-memory per-run cap (RunBudget). No network calls in this file."""

from __future__ import annotations

from pathlib import Path

import pytest

from research.llm.base import (
    BudgetExceededError,
    LLMUnavailableError,
    PerRunBudgetExceededError,
    RunBudget,
    UsageTracker,
)


class TestDailyBudgetPersistence:
    def test_persists_across_reload(self, tmp_path: Path):
        path = tmp_path / "usage.json"
        tracker1 = UsageTracker(path=path, max_per_day=40)
        tracker1.record_call()
        tracker1.record_call()
        tracker1.record_call()

        # Simulate a process restart: a brand-new UsageTracker instance
        # re-reading the same file must see the same count.
        tracker2 = UsageTracker(path=path, max_per_day=40)
        assert tracker2.calls_today() == 3

    def test_remaining_today(self, tmp_path: Path):
        tracker = UsageTracker(path=tmp_path / "usage.json", max_per_day=5)
        tracker.record_call()
        tracker.record_call()
        assert tracker.remaining_today() == 3

    def test_budget_exceeded_is_specific_subclass(self, tmp_path: Path):
        tracker = UsageTracker(path=tmp_path / "usage.json", max_per_day=1)
        tracker.record_call()
        with pytest.raises(BudgetExceededError):
            tracker.check_budget()
        # And still catchable via the broader base type existing callers use.
        tracker2 = UsageTracker(path=tmp_path / "usage2.json", max_per_day=1)
        tracker2.record_call()
        with pytest.raises(LLMUnavailableError):
            tracker2.check_budget()

    def test_default_max_per_day_is_40(self):
        from research.config import MAX_LLM_CALLS_PER_DAY

        assert MAX_LLM_CALLS_PER_DAY == 40


class TestPerRunBudget:
    def test_distinct_from_daily_cap(self):
        from research.config import MAX_LLM_CALLS_PER_DAY, MAX_LLM_CALLS_PER_RUN

        assert MAX_LLM_CALLS_PER_RUN < MAX_LLM_CALLS_PER_DAY

    def test_check_raises_when_exceeded(self):
        budget = RunBudget(max_calls=2)
        budget.record()
        budget.record()
        with pytest.raises(PerRunBudgetExceededError):
            budget.check()

    def test_not_persisted_across_instances(self):
        # Deliberate design: RunBudget is in-memory only, per process run.
        b1 = RunBudget(max_calls=1)
        b1.record()
        b2 = RunBudget(max_calls=1)
        b2.check()  # must not raise -- fresh instance, no shared state

    def test_remaining(self):
        budget = RunBudget(max_calls=5)
        budget.record()
        budget.record()
        assert budget.remaining() == 3
