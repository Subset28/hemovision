"""Automatic rejection conditions, checked by research/orchestrator.py before
(and immediately after) an experiment's evaluation-policy verdict is even
computed. These are STRUCTURAL checks ("did the world stay sane while this
ran"), distinct from evaluation_policy.py's job of judging the RESULTS
("are these numbers actually good"). An experiment can fail a rejection
check even with great numbers (e.g. it touched an unrelated file) — that is
a REJECTED verdict, not a FAILED one, precisely because it was never a fair
test of the declared hypothesis.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from research.config import EVAL_MANIFEST_PATH
from research.db import Experiment
from research.experiment_registry import get_family


class RejectionReason:
    BENCHMARK_EXECUTION_FAILURE = "benchmark_execution_failure"
    TEST_FAILURE = "test_failure"
    MISSING_RESULTS = "missing_results"
    DATASET_MODIFIED = "unexpected_dataset_modification"
    BASELINE_NOT_REPRODUCIBLE = "baseline_non_reproducible"
    UNRELATED_FILES_TOUCHED = "diff_touches_unrelated_files"
    RESOURCE_LIMITS_EXCEEDED = "resource_limits_exceeded"
    UNCONTROLLED_VARIABLE = "uncontrolled_variable_changed"


@dataclass
class RejectionCheckResult:
    rejected: bool
    reasons: list[str]


def _sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_hash() -> str | None:
    return _sha256_file(EVAL_MANIFEST_PATH)


def check_dataset_unmodified(hash_before: str | None, hash_after: str | None) -> RejectionCheckResult:
    if hash_before != hash_after:
        return RejectionCheckResult(
            rejected=True,
            reasons=[f"{RejectionReason.DATASET_MODIFIED}: eval_manifest.jsonl hash changed "
                     f"({hash_before} -> {hash_after})"],
        )
    return RejectionCheckResult(rejected=False, reasons=[])


def check_touched_paths_allowlist(exp: Experiment, touched: list[str]) -> RejectionCheckResult:
    """A simple allowlist-of-touched-paths check per experiment family. This
    is necessarily a heuristic (documented limit): it only checks path
    PREFIXES, not semantic relevance — a change inside an allowed prefix that
    is still logically an uncontrolled second variable would not be caught
    here (see check_declared_variables_cover_diff for the complementary,
    also-heuristic check on that)."""
    family = get_family(exp.experiment_family)
    allowed = family.allowed_path_prefixes
    # Every experiment may always touch its own artifact directories.
    always_allowed = ("experiments/", "research/")
    bad = [
        p for p in touched
        if not p.startswith(always_allowed) and not p.startswith(allowed)
    ]
    if bad:
        return RejectionCheckResult(
            rejected=True,
            reasons=[
                f"{RejectionReason.UNRELATED_FILES_TOUCHED}: {exp.experiment_family!r} experiments may "
                f"only touch {allowed + always_allowed!r}, but the diff touched: {bad!r}"
            ],
        )
    return RejectionCheckResult(rejected=False, reasons=[])


def check_declared_variables_cover_diff(exp: Experiment, touched: list[str]) -> RejectionCheckResult:
    """Heuristic, judgment-based check: the experiment record must declare
    `controls` and `independent_variable`; if the diff is non-trivial (more
    than a couple of files) and the experiment declared NEITHER a controls
    dict nor a specific independent_variable string, flag it. This cannot
    truly verify "only one variable changed" from a file list alone — that
    would require semantic diffing — so this is documented as a heuristic,
    not a proof. A human/reviewer-role check should back this up for
    anything non-trivial (see research/llm/prompts/reviewer.md)."""
    if not exp.independent_variable.strip():
        return RejectionCheckResult(
            rejected=True,
            reasons=[f"{RejectionReason.UNCONTROLLED_VARIABLE}: no independent_variable declared"],
        )
    if len(touched) > 5 and not exp.controls:
        return RejectionCheckResult(
            rejected=True,
            reasons=[
                f"{RejectionReason.UNCONTROLLED_VARIABLE}: diff touches {len(touched)} files but "
                "no `controls` were declared — cannot verify only one variable changed "
                "(heuristic: this check does not semantically diff the changes, only counts files)"
            ],
        )
    return RejectionCheckResult(rejected=False, reasons=[])


def combine(*results: RejectionCheckResult) -> RejectionCheckResult:
    rejected = any(r.rejected for r in results)
    reasons = [r for res in results for r in res.reasons]
    return RejectionCheckResult(rejected=rejected, reasons=reasons)
