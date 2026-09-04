"""Tests for research/evaluation_policy.py, with concrete before/after metric
fixtures proving the policy is not a naive "recall went up -> pass" rule."""

from __future__ import annotations

from research.evaluation_policy import (
    EvaluationPolicy,
    Guardrail,
    SampleSizeFloor,
    default_hazard_policy,
)

BASELINE = {
    "hazard": {"precision": 0.807, "recall": 0.480},
    "person": {"recall": 0.211, "precision": 0.667, "num_gt": 303},
    "stairs": {"recall": 0.333, "precision": 0.682, "num_gt": 45},
    "latency": {"p95_ms": 57.1},
}


class TestBigRecallGainWithCollapsedPrecisionDoesNotPass:
    def test_threshold_lowering_style_result_fails(self):
        """Mirrors the real conf=0.05 threshold-sweep finding: Person recall
        nearly doubles but precision collapses well past the guardrail."""
        policy = default_hazard_policy(0.807, 0.480)
        candidate = {
            "hazard": {"precision": 0.55, "recall": 0.60},  # precision dropped 0.257 (>> 0.05 allowance)
            "person": {"recall": 0.479, "precision": 0.312, "num_gt": 303},
            "stairs": {"recall": 0.333, "precision": 0.682, "num_gt": 45},
            "latency": {"p95_ms": 57.1},
        }
        verdict = policy.evaluate(BASELINE, candidate)
        assert verdict.result == "FAILED"
        assert any("hazard.precision" in r for r in verdict.reasons)


class TestGenuineWinPasses:
    def test_real_improvement_within_guardrails_passes(self):
        policy = default_hazard_policy(0.807, 0.480)
        candidate = {
            "hazard": {"precision": 0.79, "recall": 0.50},  # precision -0.017, within -0.05 allowance
            "person": {"recall": 0.28, "precision": 0.64, "num_gt": 303},  # +0.069, above min_meaningful_delta
            "stairs": {"recall": 0.333, "precision": 0.682, "num_gt": 45},
            "latency": {"p95_ms": 60.0},  # within 1.5x baseline (85.65)
        }
        verdict = policy.evaluate(BASELINE, candidate)
        assert verdict.result == "PASSED"


class TestNoisySmallChangeIsInconclusiveNotPassed:
    def test_tiny_delta_is_inconclusive(self):
        policy = default_hazard_policy(0.807, 0.480)
        candidate = {
            "hazard": {"precision": 0.80, "recall": 0.485},
            "person": {"recall": 0.221, "precision": 0.66, "num_gt": 303},  # +0.01, below min_meaningful_delta
            "stairs": {"recall": 0.333, "precision": 0.682, "num_gt": 45},
            "latency": {"p95_ms": 57.1},
        }
        verdict = policy.evaluate(BASELINE, candidate)
        assert verdict.result == "INCONCLUSIVE"

    def test_guardrail_violated_by_noisy_margin_is_inconclusive_not_failed(self):
        policy = default_hazard_policy(0.807, 0.480)
        candidate = {
            # precision drop of 0.055 -> exceeds -0.05 threshold by 0.005, within noise margin 0.01
            "hazard": {"precision": 0.752, "recall": 0.50},
            "person": {"recall": 0.28, "precision": 0.60, "num_gt": 303},
            "stairs": {"recall": 0.333, "precision": 0.682, "num_gt": 45},
            "latency": {"p95_ms": 57.1},
        }
        verdict = policy.evaluate(BASELINE, candidate)
        assert verdict.result == "INCONCLUSIVE"


class TestStairsOnlyWinTreatedWithSkepticism:
    def test_stairs_only_improvement_is_inconclusive_below_sample_floor(self):
        """Stairs has 45 GT boxes — a policy targeting Stairs recall must not
        report PASSED with Person-level confidence. We implement this via an
        explicit sample_size_floor that downgrades to INCONCLUSIVE."""
        policy = EvaluationPolicy(
            primary_metric="stairs.recall",
            min_meaningful_delta=0.03,
            guardrails=[
                Guardrail(metric="hazard.precision", comparator="gte", threshold=0.0,
                          relative_to_baseline_offset=-0.05),
            ],
            sample_size_floors=[
                SampleSizeFloor(metric_prefix="stairs", min_gt_count=100,
                                 description="Stairs sample size (45) is too thin for a confident PASSED verdict"),
            ],
        )
        candidate = {
            "hazard": {"precision": 0.80, "recall": 0.49},
            "stairs": {"recall": 0.50, "precision": 0.70, "num_gt": 45},  # +0.167, would otherwise clearly PASS
        }
        verdict = policy.evaluate(BASELINE, candidate)
        assert verdict.result == "INCONCLUSIVE"
        assert any("sample size" in r for r in verdict.reasons)


class TestMajorClassRegression:
    def test_unrelated_hazard_class_regression_fails_even_if_primary_improves(self):
        policy = default_hazard_policy(0.807, 0.480)
        candidate = {
            "hazard": {"precision": 0.80, "recall": 0.50},
            "person": {"recall": 0.30, "precision": 0.65, "num_gt": 303},
            "car": {"recall": 0.20, "precision": 0.60, "num_gt": 148},  # baseline car.recall not in BASELINE though
            "stairs": {"recall": 0.333, "precision": 0.682, "num_gt": 45},
            "latency": {"p95_ms": 57.1},
        }
        baseline_with_car = dict(BASELINE, car={"recall": 0.601, "precision": 0.718, "num_gt": 148})
        verdict = policy.evaluate(baseline_with_car, candidate)
        assert verdict.result == "FAILED"
        assert any("major class regression" in r for r in verdict.reasons)


class TestMissingMetricsAreInconclusive:
    def test_missing_primary_metric_is_inconclusive(self):
        policy = default_hazard_policy(0.807, 0.480)
        verdict = policy.evaluate(BASELINE, {"hazard": {"precision": 0.8, "recall": 0.5}})
        assert verdict.result == "INCONCLUSIVE"
