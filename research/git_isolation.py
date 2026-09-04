"""Git branch isolation for experiments.

Absolute rule (see research/README.md and the master Phase C spec): an
experiment's code changes MUST live only on an `experiment/EXP-XXXX` branch,
created from a clean `master`/`main` working tree. This module never merges,
never pushes, and never checks out `main`/`master`/`production`/`release*`
as an experiment TARGET (it only returns TO master when done).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from research.config import PROTECTED_BRANCHES, REPO_ROOT

MAIN_BRANCHES = ("master", "main")


class GitIsolationError(RuntimeError):
    """Raised when a safety precondition (clean tree, correct starting
    branch, etc.) is not met. Callers must not attempt to work around this —
    it exists to protect the production repo."""


def _run(args: list[str], cwd: Path = REPO_ROOT) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise GitIsolationError(
            f"git {' '.join(args)} failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return result.stdout.strip()


def current_branch(repo_root: Path = REPO_ROOT) -> str:
    return _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_root)


def is_clean(repo_root: Path = REPO_ROOT) -> bool:
    """True iff `git status --porcelain` is empty (no staged, unstaged, or
    untracked changes)."""
    return _run(["status", "--porcelain"], cwd=repo_root) == ""


def current_commit(repo_root: Path = REPO_ROOT) -> str:
    return _run(["rev-parse", "HEAD"], cwd=repo_root)


@dataclass
class ExperimentBranch:
    experiment_id: str
    branch_name: str
    start_commit: str
    repo_root: Path


def create_experiment_branch(experiment_id: str, repo_root: Path = REPO_ROOT) -> ExperimentBranch:
    """Create and check out `experiment/EXP-XXXX` from the current HEAD.

    Preconditions (raise GitIsolationError if violated, never worked around):
      1. `git status` must be clean (no staged/unstaged/untracked changes).
      2. The repo must currently be on `master` or `main` — refuses to branch
         an experiment off of another experiment branch or arbitrary ref.
    """
    if not is_clean(repo_root):
        raise GitIsolationError(
            f"refusing to create experiment branch for {experiment_id}: "
            "working tree is not clean (git status --porcelain is non-empty). "
            "Commit or stash changes first."
        )
    branch = current_branch(repo_root)
    if branch not in MAIN_BRANCHES:
        raise GitIsolationError(
            f"refusing to create experiment branch for {experiment_id}: "
            f"currently on {branch!r}, must start from one of {MAIN_BRANCHES!r}."
        )
    start_commit = current_commit(repo_root)
    branch_name = f"experiment/{experiment_id}"

    existing = _run(["branch", "--list", branch_name], cwd=repo_root)
    if existing:
        raise GitIsolationError(
            f"branch {branch_name!r} already exists — refusing to reuse/overwrite it. "
            "Delete it manually first if this is intentional, or use a different experiment_id."
        )

    _run(["checkout", "-b", branch_name], cwd=repo_root)
    return ExperimentBranch(
        experiment_id=experiment_id,
        branch_name=branch_name,
        start_commit=start_commit,
        repo_root=repo_root,
    )


def capture_diff(
    experiment_id: str, start_commit: str, output_path: Path, repo_root: Path = REPO_ROOT
) -> Path:
    """Write the full diff of the current working tree vs. start_commit to
    output_path (an experiment's patch.diff). Includes staged+unstaged
    changes relative to start_commit (does NOT require a commit to exist on
    the experiment branch — a no-op experiment yields an empty diff, which is
    valid and expected for e.g. an analysis-only experiment)."""
    diff = _run(["diff", start_commit, "--"], cwd=repo_root)
    # also include any untracked new files (diff above misses those)
    untracked = _run(["ls-files", "--others", "--exclude-standard"], cwd=repo_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    content = diff
    if untracked:
        content += (
            "\n\n# --- untracked files (not shown above; git diff does not include them) ---\n"
        )
        content += "\n".join(f"# {f}" for f in untracked.splitlines())
    output_path.write_text(content, encoding="utf-8")
    return output_path


def touched_paths(start_commit: str, repo_root: Path = REPO_ROOT) -> list[str]:
    """Return the list of file paths modified/added/deleted relative to
    start_commit, plus untracked new files. Used by the orchestrator's
    automatic-rejection allowlist check."""
    changed = _run(["diff", "--name-only", start_commit, "--"], cwd=repo_root)
    untracked = _run(["ls-files", "--others", "--exclude-standard"], cwd=repo_root)
    paths = set()
    if changed:
        paths.update(changed.splitlines())
    if untracked:
        paths.update(untracked.splitlines())
    return sorted(paths)


def discard_non_experiment_changes(
    repo_root: Path = REPO_ROOT,
    keep_prefixes: tuple = (
        "experiments/", "research/",
        # Measurement-only diagnostic SOURCE scripts and their derived JSON
        # outputs, regression tests, and human-readable reports are durable
        # lab deliverables, not a "candidate production change under test"
        # — they must survive the return-to-master isolation safety net the
        # same way experiments/ and research/ do (added for EXP-0003; kept
        # deliberately narrow — NOT a bare "benchmark/" prefix — so a real
        # candidate change to benchmark/config.py, benchmark/model.py, etc.
        # is still discarded as intended).
        "benchmark/diagnostics/", "benchmark/results/diagnostics/",
        "tests/", "reports/",
    ),
) -> list[str]:
    """Safety net called right before returning to master: git branches do
    NOT automatically isolate uncommitted working-tree changes (an
    uncommitted edit made while on `experiment/EXP-XXXX` survives a plain
    `git checkout master` if it doesn't conflict). This discards any tracked
    modification and removes any untracked file OUTSIDE keep_prefixes before
    switching back, so a code change under test (e.g. to benchmark/*.py)
    never leaks into master's working tree even though it was never
    committed. Files under keep_prefixes (the experiment's own bookkeeping —
    experiments/ artifacts, research/ memory updates) are deliberately left
    alone; they are the durable lab record this pipeline is supposed to
    produce, and get committed on master like any other project file.
    Returns the list of paths that were discarded/removed, for logging."""
    modified = _run(["diff", "--name-only", "HEAD", "--"], cwd=repo_root)
    untracked = _run(["ls-files", "--others", "--exclude-standard"], cwd=repo_root)
    discarded: list[str] = []

    to_checkout = [
        p for p in modified.splitlines() if p and not p.startswith(keep_prefixes)
    ]
    if to_checkout:
        _run(["checkout", "--", *to_checkout], cwd=repo_root)
        discarded.extend(to_checkout)

    to_remove = [
        p for p in untracked.splitlines() if p and not p.startswith(keep_prefixes)
    ]
    for p in to_remove:
        full = repo_root / p
        if full.exists():
            full.unlink()
        discarded.append(p)

    return discarded


def return_to_main_branch(repo_root: Path = REPO_ROOT, main_branch: str = "master") -> None:
    """Check out back to master/main. Never leaves the working tree on an
    experiment branch. Safe to call even if already on master (no-op)."""
    if main_branch not in MAIN_BRANCHES:
        raise GitIsolationError(f"refusing to return to non-main branch {main_branch!r}")
    branch = current_branch(repo_root)
    if branch == main_branch:
        return
    _run(["checkout", main_branch], cwd=repo_root)


def assert_never_targets_protected_branch(target: str) -> None:
    """Guard used anywhere a merge/push destination is about to be chosen.
    This module never calls merge/push itself, but this helper exists so
    orchestrator code has a single, obvious place to validate a destination
    before even considering such an operation (defense in depth)."""
    lowered = target.lower()
    if any(lowered == p or lowered.startswith(p) for p in PROTECTED_BRANCHES):
        raise GitIsolationError(
            f"refusing to target protected branch {target!r} — experiments never "
            "merge/push into master/main/production/release*."
        )
