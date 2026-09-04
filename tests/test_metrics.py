"""Independent, hand-computed checks for benchmark/metrics.py.

Every expected number below is computed by hand in the test/comment, not by
running the code and asserting "it didn't crash" — these are true independent
verifications of the IoU / greedy-matching / AP algorithm.
"""

import math

import pytest

from benchmark.metrics import (
    Detection,
    GroundTruth,
    MetricsError,
    average_precision,
    evaluate_detections,
    greedy_match,
    iou_xywh,
    precision_recall_from_match,
)


# ---------------------------------------------------------------------------
# IoU
# ---------------------------------------------------------------------------


def test_iou_identical_boxes_is_one():
    box = [0.1, 0.1, 0.2, 0.2]
    assert iou_xywh(box, box) == pytest.approx(1.0)


def test_iou_disjoint_boxes_is_zero():
    a = [0.0, 0.0, 0.1, 0.1]
    b = [0.5, 0.5, 0.1, 0.1]
    assert iou_xywh(a, b) == pytest.approx(0.0)


def test_iou_hand_computed_partial_overlap():
    # a: x[0,0.4] y[0,0.4] area=0.16
    # b: x[0.2,0.6] y[0.2,0.6] area=0.16
    # intersection: x[0.2,0.4] y[0.2,0.4] -> 0.2*0.2 = 0.04
    # union = 0.16+0.16-0.04 = 0.28
    # iou = 0.04/0.28 = 1/7
    a = [0.0, 0.0, 0.4, 0.4]
    b = [0.2, 0.2, 0.4, 0.4]
    assert iou_xywh(a, b) == pytest.approx(1.0 / 7.0, rel=1e-9)


def test_iou_rejects_malformed_bbox():
    with pytest.raises(MetricsError):
        iou_xywh([0.0, 0.0, 0.1], [0.0, 0.0, 0.1, 0.1])  # missing element
    with pytest.raises(MetricsError):
        iou_xywh([0.0, 0.0, -0.1, 0.1], [0.0, 0.0, 0.1, 0.1])  # negative width


# ---------------------------------------------------------------------------
# Greedy matching
# ---------------------------------------------------------------------------


def test_greedy_match_perfect_detection_is_tp():
    gt = [GroundTruth("img1", "person", (0.1, 0.1, 0.2, 0.2))]
    det = [Detection("img1", "person", (0.1, 0.1, 0.2, 0.2), confidence=0.9)]
    m = greedy_match(det, gt, iou_threshold=0.5)
    assert m.tp == [1]
    assert m.fp == [0]
    assert m.num_gt == 1


def test_greedy_match_missed_detection_is_false_negative():
    # No detection at all -> tp/fp arrays empty, but num_gt=1 so recall=0
    gt = [GroundTruth("img1", "person", (0.1, 0.1, 0.2, 0.2))]
    det: list = []
    m = greedy_match(det, gt, iou_threshold=0.5)
    assert m.tp == []
    assert m.fp == []
    assert m.num_gt == 1
    # fn is derived as num_gt - sum(tp) = 1 - 0 = 1
    assert m.num_gt - sum(m.tp) == 1


def test_greedy_match_low_iou_is_false_positive():
    gt = [GroundTruth("img1", "person", (0.0, 0.0, 0.1, 0.1))]
    # shifted far away -> IoU well below 0.5
    det = [Detection("img1", "person", (0.5, 0.5, 0.1, 0.1), confidence=0.9)]
    m = greedy_match(det, gt, iou_threshold=0.5)
    assert m.tp == [0]
    assert m.fp == [1]


def test_greedy_match_duplicate_detections_only_first_is_tp():
    # Two predictions on the same GT box: higher-confidence one wins as TP,
    # the lower-confidence duplicate is a FP (this is the "duplicate box"
    # signal used for the single-frame duplicate-rate proxy).
    gt = [GroundTruth("img1", "person", (0.1, 0.1, 0.2, 0.2))]
    det = [
        Detection("img1", "person", (0.1, 0.1, 0.2, 0.2), confidence=0.9),
        Detection("img1", "person", (0.1, 0.1, 0.2, 0.2), confidence=0.6),
    ]
    m = greedy_match(det, gt, iou_threshold=0.5)
    # order is confidence-descending: [0.9, 0.6]
    assert m.tp == [1, 0]
    assert m.fp == [0, 1]
    assert len(m.matched_gt_ids) == 1


def test_greedy_match_class_isolation_wrong_class_never_matches():
    gt = [GroundTruth("img1", "dog", (0.1, 0.1, 0.2, 0.2))]
    det = [Detection("img1", "person", (0.1, 0.1, 0.2, 0.2), confidence=0.9)]
    # caller is responsible for filtering by class before calling greedy_match;
    # if mismatched classes are passed together it still "matches" purely on
    # IoU/image, so evaluate_detections (which filters per-class first) is
    # the correct entry point — this test documents that greedy_match itself
    # is class-agnostic and callers must pre-filter.
    m = greedy_match(det, gt, iou_threshold=0.5)
    assert m.tp == [1]  # proves greedy_match does NOT check class_name itself


def test_greedy_match_invalid_iou_threshold_rejected():
    with pytest.raises(MetricsError):
        greedy_match([], [], iou_threshold=0.0)
    with pytest.raises(MetricsError):
        greedy_match([], [], iou_threshold=1.5)


# ---------------------------------------------------------------------------
# Average Precision (hand-computed)
# ---------------------------------------------------------------------------


def test_average_precision_perfect_detector_is_one():
    # 2 GT, 2 detections, both correct, best confidence first
    gt = [
        GroundTruth("img1", "person", (0.0, 0.0, 0.1, 0.1)),
        GroundTruth("img2", "person", (0.0, 0.0, 0.1, 0.1)),
    ]
    det = [
        Detection("img1", "person", (0.0, 0.0, 0.1, 0.1), confidence=0.9),
        Detection("img2", "person", (0.0, 0.0, 0.1, 0.1), confidence=0.8),
    ]
    m = greedy_match(det, gt, iou_threshold=0.5)
    precisions, recalls = precision_recall_from_match(m)
    # precisions=[1.0, 1.0], recalls=[0.5, 1.0]
    assert precisions == pytest.approx([1.0, 1.0])
    assert recalls == pytest.approx([0.5, 1.0])
    ap = average_precision(precisions, recalls)
    assert ap == pytest.approx(1.0)


def test_average_precision_hand_computed_mixed_case():
    # 3 GT total. Detections in confidence order: TP, FP, TP
    # cum_tp: 1,1,2   cum_fp: 0,1,1
    # precision: 1/1=1.0, 1/2=0.5, 2/3=0.6667
    # recall:    1/3=0.3333, 1/3=0.3333, 2/3=0.6667
    #
    # Interpolated precision (monotonic non-increasing from the right) over
    # sentinel-extended arrays:
    #   mrec = [0, 1/3, 1/3, 2/3, 1]
    #   mpre = [0, 1.0, 0.5, 0.6667, 0]
    # after making mpre non-increasing from the right:
    #   from the back: mpre[4]=0
    #   mpre[3]=max(0.6667,0)=0.6667
    #   mpre[2]=max(0.5,0.6667)=0.6667
    #   mpre[1]=max(1.0,0.6667)=1.0
    #   mpre[0]=max(0,1.0)=1.0
    #   -> mpre = [1.0, 1.0, 0.6667, 0.6667, 0]
    # AP = sum over recall deltas where recall changes:
    #   (1/3 - 0) * mpre[1] = (1/3)*1.0 = 0.3333   [i=1, mrec changes 0->1/3]
    #   i=2: mrec[2]==mrec[1] (1/3==1/3) -> skip
    #   (2/3 - 1/3) * mpre[3] = (1/3)*0.6667 = 0.2222  [i=3, mrec changes 1/3->2/3]
    #   (1 - 2/3) * mpre[4] = (1/3)*0 = 0             [i=4, mrec changes 2/3->1]
    # AP = 0.3333 + 0.2222 = 0.5556
    gt = [
        GroundTruth("img1", "person", (0.0, 0.0, 0.1, 0.1)),
        GroundTruth("img2", "person", (0.0, 0.0, 0.1, 0.1)),
        GroundTruth("img3", "person", (0.0, 0.0, 0.1, 0.1)),
    ]
    det = [
        Detection("img1", "person", (0.0, 0.0, 0.1, 0.1), confidence=0.95),  # TP
        Detection("img4", "person", (0.0, 0.0, 0.1, 0.1), confidence=0.9),  # FP (no GT in img4)
        Detection("img2", "person", (0.0, 0.0, 0.1, 0.1), confidence=0.8),  # TP
    ]
    m = greedy_match(det, gt, iou_threshold=0.5)
    precisions, recalls = precision_recall_from_match(m)
    ap = average_precision(precisions, recalls)
    assert ap == pytest.approx(5.0 / 9.0, abs=1e-4)  # 0.3333 + 0.2222 = 0.5556 = 5/9


def test_average_precision_no_detections_is_zero():
    ap = average_precision([], [])
    assert ap == 0.0


def test_average_precision_all_false_positives_is_zero():
    gt = [GroundTruth("img1", "person", (0.0, 0.0, 0.1, 0.1))]
    det = [Detection("img2", "person", (0.0, 0.0, 0.1, 0.1), confidence=0.9)]  # wrong image
    m = greedy_match(det, gt, iou_threshold=0.5)
    precisions, recalls = precision_recall_from_match(m)
    ap = average_precision(precisions, recalls)
    assert ap == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# evaluate_detections — precision/recall/F1 sanity + "bad predictions reduce
# metrics" behavioral checks
# ---------------------------------------------------------------------------


def _perfect_fixture():
    gt = [
        GroundTruth("img1", "person", (0.1, 0.1, 0.2, 0.2)),
        GroundTruth("img2", "dog", (0.3, 0.3, 0.1, 0.1)),
    ]
    det = [
        Detection("img1", "person", (0.1, 0.1, 0.2, 0.2), confidence=0.9),
        Detection("img2", "dog", (0.3, 0.3, 0.1, 0.1), confidence=0.9),
    ]
    return det, gt


def test_evaluate_detections_perfect_predictions_full_score():
    det, gt = _perfect_fixture()
    overall, per_class, _ = evaluate_detections(det, gt, ["person", "dog"], map_ious=(0.5,))
    assert overall.precision == pytest.approx(1.0)
    assert overall.recall == pytest.approx(1.0)
    assert overall.f1 == pytest.approx(1.0)
    assert overall.map50 == pytest.approx(1.0)


def test_evaluate_detections_known_bad_predictions_reduce_metrics():
    det, gt = _perfect_fixture()
    # corrupt one detection: wrong image (guaranteed miss) -> should reduce recall/precision
    bad_det = list(det) + [Detection("img3", "person", (0.0, 0.0, 0.05, 0.05), confidence=0.99)]
    overall_good, _, _ = evaluate_detections(det, gt, ["person", "dog"], map_ious=(0.5,))
    overall_bad, _, _ = evaluate_detections(bad_det, gt, ["person", "dog"], map_ious=(0.5,))
    assert overall_bad.precision < overall_good.precision
    assert overall_bad.fp > overall_good.fp
    # recall unaffected by an extra FP (all real GT still found)
    assert overall_bad.recall == pytest.approx(overall_good.recall)


def test_evaluate_detections_missing_predictions_are_false_negatives():
    det, gt = _perfect_fixture()
    det_missing = det[:1]  # drop the dog detection entirely
    overall, per_class, _ = evaluate_detections(det_missing, gt, ["person", "dog"], map_ious=(0.5,))
    assert overall.fn == 1
    assert per_class["dog"].fn == 1
    assert per_class["dog"].recall == pytest.approx(0.0)
    assert overall.recall == pytest.approx(0.5)  # 1 of 2 GT found


def test_evaluate_detections_map50_95_is_average_over_ious():
    det, gt = _perfect_fixture()
    from benchmark.config import MAP_5095_IOUS

    overall, per_class, _ = evaluate_detections(det, gt, ["person", "dog"], map_ious=MAP_5095_IOUS)
    # perfect boxes -> IoU=1.0 for every threshold -> AP=1.0 at every threshold
    assert overall.map50_95 == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Reproducibility: same input -> identical output across repeated calls
# ---------------------------------------------------------------------------


def test_metrics_are_reproducible_across_repeated_runs():
    det, gt = _perfect_fixture()
    det = det + [Detection("img1", "person", (0.15, 0.15, 0.2, 0.2), confidence=0.55)]  # a near-dup FP
    r1 = evaluate_detections(det, gt, ["person", "dog"], map_ious=(0.5, 0.75))
    r2 = evaluate_detections(det, gt, ["person", "dog"], map_ious=(0.5, 0.75))
    assert r1[0] == r2[0]
    for cname in ["person", "dog"]:
        assert r1[1][cname] == r2[1][cname]
