"""Tests for research/git_isolation.py.

Uses a throwaway temp git repo fixture — never touches the real OmniSight
repo destructively, per the Phase C spec's explicit instruction.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from research.git_isolation import (
    GitIsolationError,
    capture_diff,
    create_experiment_branch,
    current_branch,
    is_clean,
    return_to_main_branch,
    touched_paths,
)


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture()
def temp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(["init", "-b", "master"], repo)
    _git(["config", "user.email", "test@example.com"], repo)
    _git(["config", "user.name", "Test"], repo)
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(["add", "README.md"], repo)
    _git(["commit", "-m", "initial"], repo)
    return repo


class TestCleanlinessGuard:
    def test_is_clean_true_on_fresh_repo(self, temp_repo: Path):
        assert is_clean(temp_repo) is True

    def test_is_clean_false_with_untracked_file(self, temp_repo: Path):
        (temp_repo / "new.txt").write_text("x", encoding="utf-8")
        assert is_clean(temp_repo) is False

    def test_refuses_dirty_tree(self, temp_repo: Path):
        (temp_repo / "dirty.txt").write_text("x", encoding="utf-8")
        with pytest.raises(GitIsolationError, match="not clean"):
            create_experiment_branch("EXP-0001", repo_root=temp_repo)


class TestStartingBranchGuard:
    def test_refuses_wrong_starting_branch(self, temp_repo: Path):
        _git(["checkout", "-b", "some-other-branch"], temp_repo)
        with pytest.raises(GitIsolationError, match="must start from"):
            create_experiment_branch("EXP-0001", repo_root=temp_repo)

    def test_allows_master(self, temp_repo: Path):
        eb = create_experiment_branch("EXP-0001", repo_root=temp_repo)
        assert eb.branch_name == "experiment/EXP-0001"
        assert current_branch(temp_repo) == "experiment/EXP-0001"

    def test_refuses_duplicate_branch(self, temp_repo: Path):
        create_experiment_branch("EXP-0001", repo_root=temp_repo)
        return_to_main_branch(temp_repo)
        with pytest.raises(GitIsolationError, match="already exists"):
            create_experiment_branch("EXP-0001", repo_root=temp_repo)


class TestReturnToMain:
    def test_returns_to_master(self, temp_repo: Path):
        create_experiment_branch("EXP-0001", repo_root=temp_repo)
        assert current_branch(temp_repo) == "experiment/EXP-0001"
        return_to_main_branch(temp_repo)
        assert current_branch(temp_repo) == "master"

    def test_noop_if_already_on_master(self, temp_repo: Path):
        return_to_main_branch(temp_repo)
        assert current_branch(temp_repo) == "master"

    def test_refuses_non_main_target(self, temp_repo: Path):
        with pytest.raises(GitIsolationError):
            return_to_main_branch(temp_repo, main_branch="experiment/EXP-0001")


class TestDiffCapture:
    def test_capture_diff_includes_tracked_changes(self, temp_repo: Path, tmp_path: Path):
        eb = create_experiment_branch("EXP-0001", repo_root=temp_repo)
        (temp_repo / "README.md").write_text("changed\n", encoding="utf-8")
        out = capture_diff("EXP-0001", eb.start_commit, tmp_path / "patch.diff", repo_root=temp_repo)
        content = out.read_text(encoding="utf-8")
        assert "changed" in content

    def test_capture_diff_notes_untracked_files(self, temp_repo: Path, tmp_path: Path):
        eb = create_experiment_branch("EXP-0001", repo_root=temp_repo)
        (temp_repo / "new_file.py").write_text("print(1)\n", encoding="utf-8")
        out = capture_diff("EXP-0001", eb.start_commit, tmp_path / "patch.diff", repo_root=temp_repo)
        content = out.read_text(encoding="utf-8")
        assert "new_file.py" in content

    def test_touched_paths_reports_untracked_and_modified(self, temp_repo: Path):
        eb = create_experiment_branch("EXP-0001", repo_root=temp_repo)
        (temp_repo / "README.md").write_text("changed\n", encoding="utf-8")
        (temp_repo / "extra.py").write_text("x = 1\n", encoding="utf-8")
        paths = touched_paths(eb.start_commit, repo_root=temp_repo)
        assert "README.md" in paths
        assert "extra.py" in paths
