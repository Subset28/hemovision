"""Multi-objective evaluation policy: turns (baseline_metrics, candidate_metrics)
into a reasoned PASSED/FAILED/INCONCLUSIVE Verdict.

Deliberately NOT a single invented final-weights formula (per the master
spec). Configurable via EvaluationPolicy: a primary metric, a list of
guardrails, and INCONCLUSIVE triggers for small/noisy deltas and thin sample
sizes. This module only judges RESULTS that already exist — it is not the
place for structural pre-checks like "did the benchmark even run" or "does
the diff touch unrelated files" (see research/orchestrator.py's automatic
rejection conditions for that; this module assumes it is being handed
legitimate, already-produced metrics).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal

Comparator = Literal["gte", "lte", "gt", "lt", "eq"]

_COMPARATORS: dict[str, Callable[[float, float], bool]] = {
    "gte": lambda a, b: a >= b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "lt": lambda a, b: a < b,
    "eq": lambda a, b: a == b,
}


@dataclass(frozen=True)
class Guardrail:
    metric: str  # dotted path, e.g. "hazard.precision"
    comparator: Comparator  # candidate must satisfy comparator(candidate_value, threshold)
    threshold: float
    # If threshold is expressed relative to the baseline value, set one of:
    relative_to_baseline_offset: float | None = None  # threshold = baseline_value + offset
    relative_to_baseline_multiplier: float | None = None  # threshold = baseline_value * multiplier
    description: str = ""


@dataclass(frozen=True)
class SampleSizeFloor:
    metric_prefix: str  # e.g. "person" -> looks up gt_count under that class
    min_gt_count: int
    description: str = ""


@dataclass
class Verdict:
    result: Literal["PASSED", "FAILED", "INCONCLUSIVE"]
    reasons: list[str] = field(default_factory=list)
    guardrail_results: list[dict] = field(default_factory=list)

    @property
    def explanation(self) -> str:
        return f"{self.result}: " + "; ".join(self.reasons)


def _get(d: dict, dotted: str, default=None):
    cur = d
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


@dataclass
class EvaluationPolicy:
    """Configurable multi-objective evaluation policy.

    primary_metric: dotted path into the metrics dict this experiment is
        trying to improve, e.g. "person.recall".
    primary_metric_direction: "higher_is_better" or "lower_is_better".
    min_meaningful_delta: absolute change in primary_metric below which an
        "improvement" is treated as noise -> INCONCLUSIVE, not PASSED.
    guardrails: list of Guardrail — ANY violated guardrail fails the
        candidate UNLESS the violation margin is within
        `guardrail_noise_margin` of the threshold, in which case it is
        INCONCLUSIVE (small/noisy margin) rather than a hard FAIL.
    sample_size_floors: per-metric GT-count floors; if the primary metric (or
        any class named in guardrails) has fewer GT examples than its floor,
        the verdict is downgraded to INCONCLUSIVE regardless of the numbers
        (protects against e.g. a Stairs-only "win" on 45 GT boxes being
        reported with Person-level confidence).
    """

    primary_metric: str
    primary_metric_direction: Literal["higher_is_better", "lower_is_better"] = "higher_is_better"
    min_meaningful_delta: float = 0.02
    guardrails: list[Guardrail] = field(default_factory=list)
    guardrail_noise_margin: float = 0.01
    sample_size_floors: list[SampleSizeFloor] = field(default_factory=list)
    major_class_regression_delta: float = 0.10
    major_class_regression_metric_suffix: str = "recall"

    def _resolve_threshold(self, g: Guardrail, baseline: dict) -> float:
        if g.relative_to_baseline_offset is not None:
            base_val = _get(baseline, g.metric)
            if base_val is None:
                raise ValueError(f"guardrail metric {g.metric!r} not found in baseline")
            return base_val + g.relative_to_baseline_offset
        if g.relative_to_baseline_multiplier is not None:
            base_val = _get(baseline, g.metric)
            if base_val is None:
                raise ValueError(f"guardrail metric {g.metric!r} not found in baseline")
            return base_val * g.relative_to_baseline_multiplier
        return g.threshold

    def evaluate(self, baseline_metrics: dict, candidate_metrics: dict) -> Verdict:
        reasons: list[str] = []
        guardrail_results: list[dict] = []

        base_primary = _get(baseline_metrics, self.primary_metric)
        cand_primary = _get(candidate_metrics, self.primary_metric)
        if base_primary is None or cand_primary is None:
            return Verdict(
                result="INCONCLUSIVE",
                reasons=[f"primary_metric {self.primary_metric!r} missing from baseline or candidate metrics"],
            )

        delta = cand_primary - base_primary
        if self.primary_metric_direction == "lower_is_better":
            delta = -delta  # normalize so positive delta always means "improved"

        # ---- sample-size floors (checked first: thin evidence caps confidence) ----
        # Only applies to floors relevant to the metric actually being judged
        # (the primary metric's top-level key) — an unrelated thin class
        # appearing elsewhere in the metrics dict must not silently downgrade
        # an otherwise well-supported verdict.
        primary_prefix = self.primary_metric.split(".")[0]
        thin_evidence = False
        for floor in self.sample_size_floors:
            if floor.metric_prefix != primary_prefix:
                continue
            gt_count = _get(candidate_metrics, f"{floor.metric_prefix}.num_gt") or _get(
                baseline_metrics, f"{floor.metric_prefix}.num_gt"
            )
            if gt_count is not None and gt_count < floor.min_gt_count:
                thin_evidence = True
                reasons.append(
                    f"sample size for {floor.metric_prefix!r} ({gt_count}) is below the "
                    f"confidence floor ({floor.min_gt_count}) — {floor.description}".strip()
                )

        # ---- guardrails ----
        hard_fail = False
        noisy_violation = False
        for g in self.guardrails:
            cand_val = _get(candidate_metrics, g.metric)
            if cand_val is None:
                guardrail_results.append({"metric": g.metric, "status": "missing"})
                continue
            threshold = self._resolve_threshold(g, baseline_metrics)
            cmp_fn = _COMPARATORS[g.comparator]
            satisfied = cmp_fn(cand_val, threshold)
            margin = abs(cand_val - threshold)
            guardrail_results.append(
                {
                    "metric": g.metric,
                    "value": cand_val,
                    "threshold": threshold,
                    "comparator": g.comparator,
                    "satisfied": satisfied,
                    "margin": margin,
                }
            )
            if not satisfied:
                if margin <= self.guardrail_noise_margin:
                    noisy_violation = True
                    reasons.append(
                        f"guardrail {g.metric!r} violated by a small/noisy margin "
                        f"({cand_val:.4f} vs threshold {threshold:.4f}, margin {margin:.4f})"
                    )
                else:
                    hard_fail = True
                    reasons.append(
                        f"guardrail {g.metric!r} violated: {cand_val:.4f} does not satisfy "
                        f"{g.comparator} {threshold:.4f} ({g.description})".strip()
                    )

        # ---- major class regression: any other hazard class's recall dropping a lot ----
        for key, cand_val in _flatten(candidate_metrics).items():
            if not key.endswith(f".{self.major_class_regression_metric_suffix}"):
                continue
            base_val = _get(baseline_metrics, key)
            if base_val is None or not isinstance(cand_val, (int, float)):
                continue
            drop = base_val - cand_val
            if drop > self.major_class_regression_delta:
                hard_fail = True
                reasons.append(
                    f"major class regression: {key} dropped {drop:.3f} "
                    f"({base_val:.3f} -> {cand_val:.3f}), exceeds allowed "
                    f"{self.major_class_regression_delta:.3f}"
                )

        # ---- decide ----
        if hard_fail:
            return Verdict(result="FAILED", reasons=reasons, guardrail_results=guardrail_results)

        if abs(delta) < self.min_meaningful_delta:
            reasons.append(
                f"primary metric {self.primary_metric!r} delta ({delta:+.4f}) is below the "
                f"minimum meaningful delta ({self.min_meaningful_delta})"
            )
            return Verdict(result="INCONCLUSIVE", reasons=reasons, guardrail_results=guardrail_results)

        if noisy_violation or thin_evidence:
            reasons.insert(
                0,
                f"primary metric {self.primary_metric!r} improved by {delta:+.4f}, "
                "but confidence is downgraded to INCONCLUSIVE",
            )
            return Verdict(result="INCONCLUSIVE", reasons=reasons, guardrail_results=guardrail_results)

        if delta > 0:
            reasons.insert(
                0,
                f"primary metric {self.primary_metric!r} improved by {delta:+.4f} "
                "with all guardrails satisfied",
            )
            return Verdict(result="PASSED", reasons=reasons, guardrail_results=guardrail_results)

        reasons.insert(0, f"primary metric {self.primary_metric!r} regressed by {delta:+.4f}")
        return Verdict(result="FAILED", reasons=reasons, guardrail_results=guardrail_results)


def _flatten(d: dict, prefix: str = "") -> dict:
    out: dict = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def default_hazard_policy(baseline_hazard_precision: float, baseline_hazard_recall: float) -> EvaluationPolicy:
    """The standard guardrail set described in the Phase C spec: hazard
    precision must not drop below baseline-0.05, hazard recall must not drop
    below baseline-0.02, latency p95 must not exceed baseline*1.5."""
    return EvaluationPolicy(
        primary_metric="person.recall",
        primary_metric_direction="higher_is_better",
        min_meaningful_delta=0.03,
        guardrail_noise_margin=0.01,
        guardrails=[
            Guardrail(
                metric="hazard.precision",
                comparator="gte",
                threshold=0.0,
                relative_to_baseline_offset=-0.05,
                description="hazard precision must not drop more than 0.05 below baseline",
            ),
            Guardrail(
                metric="hazard.recall",
                comparator="gte",
                threshold=0.0,
                relative_to_baseline_offset=-0.02,
                description="hazard recall must not drop more than 0.02 below baseline",
            ),
            Guardrail(
                metric="latency.p95_ms",
                comparator="lte",
                threshold=0.0,
                relative_to_baseline_multiplier=1.5,
                description="p95 latency must not exceed 1.5x baseline",
            ),
        ],
        sample_size_floors=[
            SampleSizeFloor(metric_prefix="stairs", min_gt_count=100,
                             description="Stairs has only 45 GT boxes in the baseline — treat any Stairs-only result as low-confidence"),
            SampleSizeFloor(metric_prefix="truck", min_gt_count=100,
                             description="Truck has only 42 GT boxes in the baseline"),
            SampleSizeFloor(metric_prefix="bus", min_gt_count=100,
                             description="Bus has only 49 GT boxes in the baseline"),
            SampleSizeFloor(metric_prefix="motorcycle", min_gt_count=100,
                             description="Motorcycle has only 49 GT boxes in the baseline"),
        ],
        major_class_regression_delta=0.10,
    )
