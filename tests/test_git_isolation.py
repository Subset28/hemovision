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
    dirty_paths,
    discard_non_experiment_changes,
    is_clean,
    require_clean_tree,
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


class TestDirtyPathsAndRequireCleanTree:
    def test_dirty_paths_empty_on_clean_repo(self, temp_repo: Path):
        assert dirty_paths(temp_repo) == []

    def test_dirty_paths_reports_untracked_file(self, temp_repo: Path):
        (temp_repo / "untracked.txt").write_text("x", encoding="utf-8")
        assert "untracked.txt" in dirty_paths(temp_repo)

    def test_dirty_paths_reports_modified_tracked_file(self, temp_repo: Path):
        (temp_repo / "README.md").write_text("changed\n", encoding="utf-8")
        assert "README.md" in dirty_paths(temp_repo)

    def test_require_clean_tree_raises_and_names_the_dirty_path(self, temp_repo: Path):
        (temp_repo / "uncommitted.py").write_text("x = 1\n", encoding="utf-8")
        with pytest.raises(GitIsolationError, match="uncommitted.py"):
            require_clean_tree("test_operation", temp_repo)

    def test_require_clean_tree_passes_on_clean_repo(self, temp_repo: Path):
        require_clean_tree("test_operation", temp_repo)  # must not raise

    def test_require_clean_tree_never_stashes_or_discards(self, temp_repo: Path):
        """BLOCK and report, never auto-resolve -- the file must survive
        untouched after a refusal."""
        (temp_repo / "uncommitted.py").write_text("x = 1\n", encoding="utf-8")
        with pytest.raises(GitIsolationError):
            require_clean_tree("test_operation", temp_repo)
        assert (temp_repo / "uncommitted.py").read_text(encoding="utf-8") == "x = 1\n"

    def test_gitignored_runtime_artifact_does_not_block_clean_tree(self, temp_repo: Path):
        """Generated/gitignored runtime artifacts (research/omnilab.db-style
        files) must never count as 'dirty' -- git itself already excludes
        gitignored, untracked files from `git status --porcelain` output."""
        (temp_repo / ".gitignore").write_text("ignored_runtime_artifact.db\n", encoding="utf-8")
        _git(["add", ".gitignore"], temp_repo)
        _git(["commit", "-m", "add gitignore"], temp_repo)
        (temp_repo / "ignored_runtime_artifact.db").write_text("binary-ish content", encoding="utf-8")
        assert dirty_paths(temp_repo) == []
        require_clean_tree("test_operation", temp_repo)  # must not raise
        create_experiment_branch("EXP-0001", repo_root=temp_repo)  # must also succeed


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


class TestDiscardNonExperimentChanges:
    def test_discards_tracked_modification_outside_keep_prefixes(self, temp_repo: Path):
        create_experiment_branch("EXP-0001", repo_root=temp_repo)
        (temp_repo / "README.md").write_text("code-under-test change\n", encoding="utf-8")
        discarded = discard_non_experiment_changes(repo_root=temp_repo)
        assert "README.md" in discarded
        assert (temp_repo / "README.md").read_text(encoding="utf-8") == "hello\n"

    def test_removes_untracked_file_outside_keep_prefixes(self, temp_repo: Path):
        create_experiment_branch("EXP-0001", repo_root=temp_repo)
        (temp_repo / "leaked_code.py").write_text("x = 1\n", encoding="utf-8")
        discarded = discard_non_experiment_changes(repo_root=temp_repo)
        assert "leaked_code.py" in discarded
        assert not (temp_repo / "leaked_code.py").exists()

    def test_keeps_experiment_bookkeeping_files(self, temp_repo: Path):
        create_experiment_branch("EXP-0001", repo_root=temp_repo)
        (temp_repo / "experiments").mkdir()
        (temp_repo / "experiments" / "EXP-0001-notes.md").write_text("kept\n", encoding="utf-8")
        (temp_repo / "research").mkdir()
        (temp_repo / "research" / "memory.md").write_text("kept too\n", encoding="utf-8")
        discarded = discard_non_experiment_changes(repo_root=temp_repo)
        assert discarded == []
        assert (temp_repo / "experiments" / "EXP-0001-notes.md").exists()
        assert (temp_repo / "research" / "memory.md").exists()

    def test_survives_full_lifecycle_leaving_master_clean(self, temp_repo: Path):
        """End-to-end: branch -> leak a code change + bookkeeping file ->
        discard -> return to master -> master's working tree carries only
        the bookkeeping file, never the leaked code change."""
        eb = create_experiment_branch("EXP-0001", repo_root=temp_repo)
        (temp_repo / "README.md").write_text("leaked change\n", encoding="utf-8")
        (temp_repo / "experiments").mkdir()
        (temp_repo / "experiments" / "record.md").write_text("kept\n", encoding="utf-8")
        discard_non_experiment_changes(repo_root=temp_repo)
        return_to_main_branch(temp_repo)
        assert current_branch(temp_repo) == "master"
        assert (temp_repo / "README.md").read_text(encoding="utf-8") == "hello\n"
        assert (temp_repo / "experiments" / "record.md").exists()
