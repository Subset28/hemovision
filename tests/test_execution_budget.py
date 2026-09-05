"""Phase-I-readiness HIGH finding #4: research/execution_budget.py's
deterministic GPU/runtime budget framework. No real GPU/training job is
launched anywhere in this file or in the module under test -- purely
deterministic authorization/limit-checking logic."""

from __future__ import annotations

import pytest

from research.execution_budget import (
    ExecutionBudgetConfig,
    ExecutionBudgetError,
    ResourceEstimate,
    require_execution_budget,
)


class TestFailClosedByDefault:
    def test_no_config_at_all_refuses(self):
        with pytest.raises(ExecutionBudgetError):
            require_execution_budget("train_exp_0006", config=None)

    def test_default_config_not_authorized_refuses(self):
        with pytest.raises(ExecutionBudgetError):
            require_execution_budget("train_exp_0006", config=ExecutionBudgetConfig())

    def test_authorized_but_no_limits_configured_still_allows(self):
        """gpu_execution_authorized=True with no other limits set is a
        legitimate (if permissive) configuration -- fail-closed applies to
        MISSING config, not to an operator's deliberate choice not to cap
        a particular dimension."""
        config = ExecutionBudgetConfig(gpu_execution_authorized=True)
        require_execution_budget("train_exp_0006", config=config)  # must not raise


class TestConcurrentJobLimit:
    def test_at_limit_refuses(self):
        config = ExecutionBudgetConfig(gpu_execution_authorized=True, max_concurrent_training_jobs=2)
        with pytest.raises(ExecutionBudgetError):
            require_execution_budget("train_x", config=config, current_running_training_jobs=2)

    def test_under_limit_allows(self):
        config = ExecutionBudgetConfig(gpu_execution_authorized=True, max_concurrent_training_jobs=2)
        require_execution_budget("train_x", config=config, current_running_training_jobs=1)


class TestWallClockLimit:
    def test_estimate_exceeding_per_experiment_limit_refuses(self):
        config = ExecutionBudgetConfig(gpu_execution_authorized=True, max_wall_clock_sec_per_experiment=3600)
        estimate = ResourceEstimate(estimated_wall_clock_sec=7200)
        with pytest.raises(ExecutionBudgetError):
            require_execution_budget("train_x", config=config, estimate=estimate)

    def test_estimate_within_per_experiment_limit_allows(self):
        config = ExecutionBudgetConfig(gpu_execution_authorized=True, max_wall_clock_sec_per_experiment=3600)
        estimate = ResourceEstimate(estimated_wall_clock_sec=1800)
        require_execution_budget("train_x", config=config, estimate=estimate)

    def test_cumulative_runtime_exceeding_cycle_limit_refuses(self):
        config = ExecutionBudgetConfig(gpu_execution_authorized=True, max_cumulative_runtime_sec_per_cycle=10000)
        estimate = ResourceEstimate(estimated_wall_clock_sec=3000)
        with pytest.raises(ExecutionBudgetError):
            require_execution_budget(
                "train_x", config=config, estimate=estimate, current_cumulative_runtime_sec=8000,
            )

    def test_cumulative_runtime_within_cycle_limit_allows(self):
        config = ExecutionBudgetConfig(gpu_execution_authorized=True, max_cumulative_runtime_sec_per_cycle=10000)
        estimate = ResourceEstimate(estimated_wall_clock_sec=1000)
        require_execution_budget(
            "train_x", config=config, estimate=estimate, current_cumulative_runtime_sec=8000,
        )

    def test_no_estimate_supplied_skips_wall_clock_checks(self):
        """An operation that doesn't (yet) know its own resource estimate
        cannot be checked against a wall-clock limit -- this is a distinct,
        documented case from "no config at all", not a bypass of the
        authorization/concurrency checks."""
        config = ExecutionBudgetConfig(gpu_execution_authorized=True, max_wall_clock_sec_per_experiment=1)
        require_execution_budget("train_x", config=config, estimate=None)


class TestImmutableConfig:
    def test_config_is_frozen(self):
        config = ExecutionBudgetConfig(gpu_execution_authorized=True)
        with pytest.raises(Exception):
            config.gpu_execution_authorized = False  # type: ignore[misc]
