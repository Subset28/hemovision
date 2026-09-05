"""Deterministic baseline-metrics lookup (Phase H schema-mapping fix,
post-DRYRUN-0007-revision audit).

research/experiment_spec.py::ExperimentProposal.baseline_metrics is
documented as something that "must resolve to a real artifact, not
hand-typed numbers" -- but until this fix, nothing in
research/dry_run/pipeline.py ever populated it: every dry-run proposal
shipped with `baseline_metrics == {}` regardless of what the actual baseline
run recorded. This module is the one place that resolves a baseline_run_id
to its ALREADY-COMPUTED metrics, by reading the real
benchmark/results/baseline/metrics.json artifact -- never an LLM guess,
never a hand-typed number.
"""

from __future__ import annotations

import json

from research.config import REPO_ROOT

BASELINE_RESULTS_DIR = REPO_ROOT / "benchmark" / "results" / "baseline"


def load_baseline_metrics(baseline_run_id: str) -> dict:
    """Return the recorded metrics for `baseline_run_id`, read directly from
    benchmark/results/baseline/metrics.json. Returns {} (an honest "not
    resolved" signal, never a guess) if:
      - the metrics artifact is missing or unreadable, or
      - its recorded run_id does not match `baseline_run_id` (this repo
        currently has exactly one baseline artifact on disk; an id that
        doesn't match it is never silently paired with a different run's
        numbers).
    """
    metrics_path = BASELINE_RESULTS_DIR / "metrics.json"
    if not metrics_path.exists():
        return {}
    try:
        data = json.loads(metrics_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if data.get("run_id") != baseline_run_id:
        return {}
    hazard = data.get("hazard_classes_only") or {}
    overall = data.get("overall") or {}
    return {
        "run_id": data.get("run_id"),
        "num_images_evaluated": data.get("num_images_evaluated"),
        "hazard_precision": hazard.get("precision"),
        "hazard_recall": hazard.get("recall"),
        "hazard_f1": hazard.get("f1"),
        "hazard_map50": hazard.get("map50"),
        "overall_precision": overall.get("precision"),
        "overall_recall": overall.get("recall"),
    }
