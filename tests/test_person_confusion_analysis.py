"""Regression tests for EXP-0003's class-confusion diagnostics
(benchmark/diagnostics/human_class_map.py, person_confusion_analysis.py,
person_counterfactuals.py).

Uses small, hand-computed synthetic fixtures (never "run on real data and
assert no-crash") so every expected classification is verifiable by hand.
All bboxes are normalized [x, y, w, h], top-left origin, matching
benchmark/metrics.py's convention.
"""

from __future__ import annotations

from benchmark.diagnostics.human_class_map import (
    ALL_HUMAN_RELATED_CLASSES,
    HUMAN_LIKE_CLASSES,
    PERSON_SUBPARTS,
    WHOLE_PERSON_ALIASES,
    verify_against_model,
)
from benchmark.diagnostics.person_confusion_analysis import (
    CONF_NOISE_FLOOR,
    DIAG_CONF_FLOOR_C,
    MATCH_IOU,
    SPATIAL_ASSOC_IOU,
    Candidate,
    _classify_one,
    _match_person_boxes_in_sample,
)
from benchmark.metrics import iou_xywh


# ---------------------------------------------------------------------------
# human_class_map.py
# ---------------------------------------------------------------------------


def test_verify_against_model_passes_for_a_superset():
    fake_names = {i: c for i, c in enumerate(sorted(ALL_HUMAN_RELATED_CLASSES | {"Car"}))}
    result = verify_against_model(fake_names)
    assert result["ok"] is True
    assert result["missing"] == []


def test_verify_against_model_flags_missing_class():
    fake_names = {0: "Car", 1: "Dog"}  # missing every human class
    result = verify_against_model(fake_names)
    assert result["ok"] is False
    assert "Person" in result["missing"]
    assert "Man" in result["missing"]


def test_whole_person_and_subparts_are_disjoint():
    assert WHOLE_PERSON_ALIASES.isdisjoint(PERSON_SUBPARTS)


# ---------------------------------------------------------------------------
# _classify_one: the 5-category decision tree
# ---------------------------------------------------------------------------

GT_BOX = (0.40, 0.40, 0.20, 0.40)  # a representative Person GT box


def _cand(class_name, confidence, bbox, iou=None):
    if iou is None:
        iou = iou_xywh(GT_BOX, bbox)
    return Candidate(class_name=class_name, confidence=confidence, bbox=bbox, iou=iou,
                      is_baseline_prediction=confidence >= 0.4)


def test_category_a_true_detector_miss_no_candidates():
    primary, secondary, alt = _classify_one(GT_BOX, [])
    assert primary == "TRUE_DETECTOR_MISS"
    assert secondary == []
    assert alt is None


def test_category_a_only_unrelated_class_nearby():
    # A "Chair" prediction overlapping the GT box is not human-like at all.
    cand = _cand("Chair", 0.9, GT_BOX)  # same box -> iou 1.0, but wrong branch of logic entirely
    primary, secondary, alt = _classify_one(GT_BOX, [cand])
    assert primary == "TRUE_DETECTOR_MISS"


def test_category_b_low_confidence_person():
    # Person-class candidate, good IoU, but below the 0.4 production threshold.
    cand = _cand("Person", 0.15, GT_BOX)
    primary, secondary, alt = _classify_one(GT_BOX, [cand])
    assert primary == "LOW_CONFIDENCE_PERSON"
    assert alt is None


def test_category_c_semantic_class_confusion_man():
    # "Man" at the right location, at/above the diagnostic confidence floor.
    cand = _cand("Man", 0.55, GT_BOX)
    primary, secondary, alt = _classify_one(GT_BOX, [cand])
    assert primary == "SEMANTIC_CLASS_CONFUSION"
    assert alt == "Man"


def test_category_c_picks_highest_confidence_alt_class_when_several():
    cands = [_cand("Woman", 0.42, GT_BOX), _cand("Man", 0.71, GT_BOX)]
    primary, secondary, alt = _classify_one(GT_BOX, cands)
    assert primary == "SEMANTIC_CLASS_CONFUSION"
    assert alt == "Man"


def test_category_c_requires_confidence_at_or_above_diagnostic_floor():
    # "Man" at match-quality IoU but BELOW the diagnostic confidence floor
    # (0.4) does not count as genuine semantic confusion -> falls through to
    # localization-failure bucket (localized correctly, evidence too weak).
    cand = _cand("Man", DIAG_CONF_FLOOR_C - 0.01, GT_BOX)
    primary, secondary, alt = _classify_one(GT_BOX, [cand])
    assert primary == "LOCALIZATION_FAILURE"
    assert alt == "Man"


NEAR_BOX = (0.46, 0.52, 0.20, 0.40)  # shifted from GT_BOX, iou in [0.3, 0.5) by construction


def test_near_box_fixture_is_in_the_intended_iou_band():
    iou = iou_xywh(GT_BOX, NEAR_BOX)
    assert SPATIAL_ASSOC_IOU <= iou < MATCH_IOU, f"fixture iou {iou} not in the intended band"


def test_category_d_localization_failure_low_iou_person():
    # A Person-class prediction exists nearby but overlaps only partially --
    # spatially associated (>=0.3) but below the match floor (0.5).
    iou = iou_xywh(GT_BOX, NEAR_BOX)
    cand = _cand("Person", 0.9, NEAR_BOX, iou=iou)
    primary, secondary, alt = _classify_one(GT_BOX, [cand])
    assert primary == "LOCALIZATION_FAILURE"


def test_category_d_localization_failure_low_iou_alias():
    iou = iou_xywh(GT_BOX, NEAR_BOX)
    cand = _cand("Woman", 0.8, NEAR_BOX, iou=iou)
    primary, secondary, alt = _classify_one(GT_BOX, [cand])
    assert primary == "LOCALIZATION_FAILURE"
    assert alt == "Woman"


def test_subpart_candidate_at_match_quality_counts_as_semantic_confusion():
    cand = _cand("Human body", 0.6, GT_BOX)
    primary, secondary, alt = _classify_one(GT_BOX, [cand])
    assert primary == "SEMANTIC_CLASS_CONFUSION"
    assert alt == "Human body"


def test_duplicate_multi_label_secondary_flag():
    # Two DIFFERENT human-related classes stacked over the same GT box ->
    # primary is whichever wins the decision tree (Man, semantic confusion),
    # but the DUPLICATE_MULTI_LABEL secondary flag must also be set.
    cands = [_cand("Man", 0.6, GT_BOX), _cand("Human body", 0.5, GT_BOX)]
    primary, secondary, alt = _classify_one(GT_BOX, cands)
    assert primary == "SEMANTIC_CLASS_CONFUSION"
    assert "DUPLICATE_MULTI_LABEL" in secondary


def test_no_duplicate_flag_for_single_human_related_class():
    cand = _cand("Man", 0.6, GT_BOX)
    _primary, secondary, _alt = _classify_one(GT_BOX, [cand])
    assert "DUPLICATE_MULTI_LABEL" not in secondary


def test_below_noise_floor_confidence_candidate_ignored():
    # A near-zero-confidence "Person" box should not rescue this from
    # TRUE_DETECTOR_MISS -- it's below CONF_NOISE_FLOOR.
    cand = _cand("Person", CONF_NOISE_FLOOR - 0.01, GT_BOX)
    primary, secondary, alt = _classify_one(GT_BOX, [cand])
    assert primary == "TRUE_DETECTOR_MISS"


# ---------------------------------------------------------------------------
# _match_person_boxes_in_sample: multi-instance scoping correctness
# ---------------------------------------------------------------------------


def test_two_people_in_one_image_handled_independently():
    """Two non-overlapping Person GT boxes; one has a confident matching
    prediction, the other has none. Each must be judged independently -- no
    cross-contamination (the historical evaluate.py bug this experiment must
    not reintroduce)."""
    gt_a = (0.05, 0.05, 0.15, 0.30)
    gt_b = (0.60, 0.60, 0.15, 0.30)
    preds = [{"bbox": list(gt_a), "confidence": 0.9}]  # matches gt_a only
    claimed_gt, claimed_pred = _match_person_boxes_in_sample(preds, [gt_a, gt_b])
    assert claimed_gt == {0}
    assert claimed_pred == {0}


def test_overlapping_people_each_gt_scoped_to_its_own_box():
    """Two OVERLAPPING Person GT boxes; one prediction. Greedy matching
    claims exactly one GT (the higher-IoU one), the other remains a genuine
    FN -- it must not be silently treated as matched, and the claimed
    detection must not double as evidence for the other GT."""
    gt_a = (0.10, 0.10, 0.30, 0.50)
    gt_b = (0.20, 0.15, 0.30, 0.50)  # overlaps gt_a substantially
    pred_box = gt_a  # exact match to gt_a
    preds = [{"bbox": list(pred_box), "confidence": 0.9}]
    claimed_gt, claimed_pred = _match_person_boxes_in_sample(preds, [gt_a, gt_b])
    assert claimed_gt == {0}  # only gt_a (exact IoU=1.0) is claimed
    assert 1 not in claimed_gt  # gt_b remains an FN despite the overlap
    assert claimed_pred == {0}


def test_one_prediction_cannot_double_count_across_two_gts():
    """A single prediction overlapping two different GT boxes above match
    threshold must claim at most ONE of them (greedy matching's per-image
    claim invariant) -- never both."""
    gt_a = (0.10, 0.10, 0.30, 0.30)
    gt_b = (0.15, 0.12, 0.30, 0.30)  # heavy overlap with gt_a
    pred_box = (0.12, 0.11, 0.30, 0.30)
    preds = [{"bbox": list(pred_box), "confidence": 0.8}]
    claimed_gt, claimed_pred = _match_person_boxes_in_sample(preds, [gt_a, gt_b])
    assert len(claimed_gt) == 1  # never both
    assert claimed_pred == {0}


def test_multiple_predictions_over_one_gt_only_one_claims_it():
    """Multiple candidate Person predictions stacked over a single GT box:
    only the (greedy, confidence-first) best one claims it; this exercises
    the duplicate/multi-label-over-one-box scenario at the matching layer
    (semantic duplicate-class stacking is covered by
    test_duplicate_multi_label_secondary_flag above at the classification
    layer)."""
    gt_a = (0.30, 0.30, 0.20, 0.40)
    preds = [
        {"bbox": list(gt_a), "confidence": 0.55},
        {"bbox": list(gt_a), "confidence": 0.91},
    ]
    claimed_gt, claimed_pred = _match_person_boxes_in_sample(preds, [gt_a])
    assert claimed_gt == {0}
    # the higher-confidence prediction (index 1) is the one that claims it
    assert claimed_pred == {1}
