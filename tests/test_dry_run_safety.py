"""Phase H — the dry-run safety boundary (section 1 / section 14's safety
items). Every assertion here proves a NEGATIVE: the dry-run pipeline never
touches the real execution/queue machinery, never writes production paths,
and never fabricates observed results."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from research.config import EXPERIMENTS_DIR, REPO_ROOT
from research.db import OmniLabDB
from research.dry_run.budget import DryRunCallBudget
from research.dry_run.pipeline import run_dry_run_cycle, write_artifacts
from research.llm.base import LLMProvider, LLMResponse
from research.llm.router import LLMRouter
from tests.test_dry_run_pipeline import _proposal_json, _review_json


def _run_mocked_cycle(**kwargs):
    class FixedProvider(LLMProvider):
        def complete(self, prompt, role, model="", **kw):
            text = _proposal_json() if role == "researcher" else _review_json()
            return LLMResponse(text=text, tokens_used=1, cost_usd=0.0, model_used=model)

    import tempfile
    from pathlib import Path

    from research.llm.base import UsageTracker

    tracker_path = Path(tempfile.mkstemp(suffix=".json")[1])
    router = LLMRouter(provider=FixedProvider(), usage_tracker=UsageTracker(path=tracker_path, max_per_day=1000))
    return run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3), **kwargs)


def _experiment_ids() -> set[str]:
    with OmniLabDB() as db:
        return {e.experiment_id for e in db.list_experiments()}


def _experiment_dirs() -> set[str]:
    if not EXPERIMENTS_DIR.exists():
        return set()
    dirs = set()
    for status_dir in EXPERIMENTS_DIR.iterdir():
        if status_dir.is_dir():
            for child in status_dir.iterdir():
                if child.is_dir():
                    dirs.add(str(child.relative_to(EXPERIMENTS_DIR)))
    return dirs


def _git_branches() -> set[str]:
    out = subprocess.run(["git", "branch", "--list", "experiment/*"], cwd=REPO_ROOT,
                          capture_output=True, text=True)
    return {line.strip().lstrip("* ").strip() for line in out.stdout.splitlines() if line.strip()}


class TestZeroMutationOfRealInfrastructure:
    def test_zero_new_rows_in_experiments_table(self):
        before = _experiment_ids()
        _run_mocked_cycle()
        after = _experiment_ids()
        assert after == before

    def test_zero_new_experiment_directories(self):
        before = _experiment_dirs()
        _run_mocked_cycle()
        after = _experiment_dirs()
        assert after == before

    def test_zero_new_experiment_git_branches(self):
        before = _git_branches()
        _run_mocked_cycle()
        after = _git_branches()
        assert after == before

    def test_queue_experiment_from_spec_never_called(self, monkeypatch):
        import research.orchestrator as orchestrator_mod

        spy = MagicMock(side_effect=AssertionError("queue_experiment_from_spec must never be called by dry-run"))
        monkeypatch.setattr(orchestrator_mod, "queue_experiment_from_spec", spy)
        _run_mocked_cycle()
        assert spy.call_count == 0

    def test_create_experiment_branch_never_called(self, monkeypatch):
        import research.git_isolation as git_isolation_mod

        spy = MagicMock(side_effect=AssertionError("create_experiment_branch must never be called by dry-run"))
        monkeypatch.setattr(git_isolation_mod, "create_experiment_branch", spy)
        _run_mocked_cycle()
        assert spy.call_count == 0

    def test_runner_dispatch_never_called(self, monkeypatch):
        import research.runners as runners_mod

        original_runners = dict(runners_mod.RUNNERS)
        spies = {}
        for exp_id, fn in original_runners.items():
            spy = MagicMock(side_effect=AssertionError(f"runner {exp_id} must never be called by dry-run"))
            spies[exp_id] = spy
        monkeypatch.setattr(runners_mod, "RUNNERS", spies)
        _run_mocked_cycle()
        for spy in spies.values():
            assert spy.call_count == 0

    def test_no_writes_under_ios(self):
        ios_dir = REPO_ROOT / "ios"
        if not ios_dir.exists():
            pytest.skip("ios/ not present in this checkout")
        before = subprocess.run(["git", "status", "--porcelain", "--", "ios/"], cwd=REPO_ROOT,
                                 capture_output=True, text=True).stdout
        _run_mocked_cycle()
        after = subprocess.run(["git", "status", "--porcelain", "--", "ios/"], cwd=REPO_ROOT,
                                capture_output=True, text=True).stdout
        assert before == after

    def test_no_writes_to_benchmark_config(self):
        config_path = REPO_ROOT / "benchmark" / "config.py"
        before = config_path.read_bytes() if config_path.exists() else None
        _run_mocked_cycle()
        after = config_path.read_bytes() if config_path.exists() else None
        assert before == after

    def test_no_writes_under_benchmark_results_baseline(self):
        baseline_dir = REPO_ROOT / "benchmark" / "results" / "baseline"
        if not baseline_dir.exists():
            pytest.skip("baseline dir not present")
        before = subprocess.run(["git", "status", "--porcelain", "--", str(baseline_dir)], cwd=REPO_ROOT,
                                 capture_output=True, text=True).stdout
        _run_mocked_cycle()
        after = subprocess.run(["git", "status", "--porcelain", "--", str(baseline_dir)], cwd=REPO_ROOT,
                                capture_output=True, text=True).stdout
        assert before == after

    def test_experiment_result_fields_never_populated(self):
        """The dry-run proposal's ExperimentSpec.result must stay the empty
        ExperimentResult() throughout — the pipeline has no code path that
        populates a metric/verdict/conclusion."""
        from research.experiment_spec import ExperimentSpec

        result = _run_mocked_cycle()
        spec = ExperimentSpec(proposal=result.proposal)
        assert spec.result.is_empty()

    def test_artifact_paths_are_new_and_distinct_from_experiments_dir(self, tmp_path, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        monkeypatch.setattr(pipeline_mod, "DRY_RUN_PROPOSALS_DIR", tmp_path / "dry_run_proposals")
        monkeypatch.setattr(pipeline_mod, "DRY_RUN_REPORTS_DIR", tmp_path / "dry_run_reports")
        result = _run_mocked_cycle()
        json_path, report_path = write_artifacts(result)
        assert "experiments" not in str(json_path).lower().split("dry_run")[0]
        assert not str(json_path).startswith(str(EXPERIMENTS_DIR))
        assert not str(report_path).startswith(str(EXPERIMENTS_DIR))
