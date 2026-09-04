"""Pure-function detection metrics: IoU, greedy confidence-sorted matching,
precision/recall/F1, and all-point interpolated Average Precision (AP),
averaged over IoU thresholds for mAP@50:95.

No I/O. No third-party detection-metric library (e.g. pycocotools) — implemented
directly per BENCHMARK_PLAN.md instructions, as a ~well-known, independently
verifiable ~100-line algorithm. Every function here is covered by hand-computed
fixtures in tests/test_metrics.py.

IMPORTANT HONESTY NOTE (read before interpreting mAP numbers in the report):
Because benchmark/evaluate.py runs the model at the app's real operating point
(confidence threshold 0.4 — see benchmark/config.py), predictions below that
confidence never reach these functions. That means the precision-recall curve
built here is truncated at conf=0.4, not swept down to ~0 the way conventional
research mAP@0.5 / mAP@0.5:0.95 leaderboard numbers are computed (e.g.
pycocotools sweeps all detections down to conf=0.001). The AP figures this
module produces are therefore a legitimate but *conservative, operating-point-
restricted* estimate — they answer "how good is precision/recall at the exact
settings the shipped app uses", not "what is this model's best possible mAP".
Report writers must state this explicitly wherever mAP is quoted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

BBox = Sequence[float]  # [x, y, w, h], normalized, top-left origin


class MetricsError(ValueError):
    """Raised for malformed inputs to the metrics functions."""


def _validate_bbox(bbox: BBox) -> None:
    if len(bbox) != 4:
        raise MetricsError(f"bbox must have 4 elements [x,y,w,h], got {bbox!r}")
    x, y, w, h = bbox
    if w < 0 or h < 0:
        raise MetricsError(f"bbox width/height must be >= 0, got {bbox!r}")


def iou_xywh(box_a: BBox, box_b: BBox) -> float:
    """Intersection-over-union of two [x, y, w, h] normalized top-left boxes."""
    _validate_bbox(box_a)
    _validate_bbox(box_b)
    ax1, ay1, aw, ah = box_a
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx1, by1, bw, bh = box_b
    bx2, by2 = bx1 + bw, by1 + bh

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h

    area_a = aw * ah
    area_b = bw * bh
    union = area_a + area_b - inter_area
    if union <= 0:
        return 0.0
    return inter_area / union


@dataclass(frozen=True)
class Detection:
    sample_id: str
    class_name: str
    bbox: tuple
    confidence: float


@dataclass(frozen=True)
class GroundTruth:
    sample_id: str
    class_name: str
    bbox: tuple


@dataclass
class MatchResult:
    """Per-detection tp/fp flags (aligned to confidence-descending order) plus
    the total number of ground-truth boxes for the class (for recall denominator)."""

    tp: list  # list[int] 0/1, confidence-descending order
    fp: list  # list[int] 0/1, confidence-descending order
    confidences: list
    num_gt: int
    matched_gt_ids: list  # (sample_id, gt_index) tuples that were matched, for duplicate-box analysis
    unmatched_detection_indices: list  # indices (into the confidence-sorted input) that were FP


def greedy_match(
    detections: Sequence[Detection],
    ground_truths: Sequence[GroundTruth],
    iou_threshold: float,
) -> MatchResult:
    """Greedy confidence-sorted IoU matching for a single class.

    Standard COCO/VOC algorithm: sort detections by confidence descending; for
    each detection, among ground-truth boxes in the SAME image not yet claimed,
    pick the highest-IoU one; if that IoU >= iou_threshold, it's a true positive
    and the GT box is claimed (cannot be reused); otherwise it's a false positive.
    Ground-truth boxes never claimed by any detection are false negatives
    (implicitly: num_gt - matched_count).
    """
    if not (0.0 < iou_threshold <= 1.0):
        raise MetricsError(f"iou_threshold must be in (0, 1], got {iou_threshold}")

    order = sorted(range(len(detections)), key=lambda i: detections[i].confidence, reverse=True)

    # index ground truths by sample_id for fast per-image lookup
    gt_by_sample: dict = {}
    for gi, gt in enumerate(ground_truths):
        gt_by_sample.setdefault(gt.sample_id, []).append(gi)

    claimed = [False] * len(ground_truths)
    tp = []
    fp = []
    confidences = []
    matched_gt_ids = []
    unmatched_detection_indices = []

    for rank, di in enumerate(order):
        det = detections[di]
        candidates = gt_by_sample.get(det.sample_id, [])
        best_iou = 0.0
        best_gi = -1
        for gi in candidates:
            if claimed[gi]:
                continue
            gt = ground_truths[gi]
            iou = iou_xywh(det.bbox, gt.bbox)
            if iou > best_iou:
                best_iou = iou
                best_gi = gi
        confidences.append(det.confidence)
        if best_gi != -1 and best_iou >= iou_threshold:
            tp.append(1)
            fp.append(0)
            claimed[best_gi] = True
            matched_gt_ids.append((det.sample_id, best_gi))
        else:
            tp.append(0)
            fp.append(1)
            unmatched_detection_indices.append(rank)

    return MatchResult(
        tp=tp,
        fp=fp,
        confidences=confidences,
        num_gt=len(ground_truths),
        matched_gt_ids=matched_gt_ids,
        unmatched_detection_indices=unmatched_detection_indices,
    )


def precision_recall_from_match(match: MatchResult) -> tuple:
    """Cumulative precision/recall arrays (confidence-descending order)."""
    cum_tp = 0
    cum_fp = 0
    precisions = []
    recalls = []
    for tp_i, fp_i in zip(match.tp, match.fp):
        cum_tp += tp_i
        cum_fp += fp_i
        precisions.append(cum_tp / (cum_tp + cum_fp) if (cum_tp + cum_fp) > 0 else 0.0)
        recalls.append(cum_tp / match.num_gt if match.num_gt > 0 else 0.0)
    return precisions, recalls


def average_precision(precisions: Sequence[float], recalls: Sequence[float]) -> float:
    """All-point interpolated AP (VOC2012-style), computed from cumulative
    precision/recall arrays already in confidence-descending order.

    Algorithm:
      1. Prepend (recall=0, precision=0) and append (recall=1, precision=0)
         sentinels (precision=0 at recall=1 is a safe outer bound; real curves
         never reach exactly recall=1 with nonzero precision unless the last
         detection is a TP, in which case the sentinel does not affect area
         because recall does not increase past the last real point... actually
         to avoid ambiguity we append precision=0 at recall=1 ONLY as an upper
         recall bound; interpolation below makes precision monotonic first so
         this sentinel never inflates AP).
      2. Make precision monotonically non-increasing from the right
         (interpolated precision at recall r = max precision for recall' >= r).
      3. AP = sum over consecutive distinct recall values of
         (recall_i - recall_{i-1}) * interpolated_precision_i.
    """
    if len(precisions) != len(recalls):
        raise MetricsError("precisions and recalls must be the same length")
    if len(precisions) == 0:
        return 0.0

    mrec = [0.0] + list(recalls) + [1.0]
    mpre = [0.0] + list(precisions) + [0.0]

    for i in range(len(mpre) - 2, -1, -1):
        mpre[i] = max(mpre[i], mpre[i + 1])

    ap = 0.0
    for i in range(1, len(mrec)):
        if mrec[i] != mrec[i - 1]:
            ap += (mrec[i] - mrec[i - 1]) * mpre[i]
    return ap


@dataclass
class ClassMetrics:
    class_name: str
    num_gt: int
    num_predictions: int
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    ap50: float
    ap50_95: float
    ap_per_iou: dict  # {iou_threshold: ap}


@dataclass
class OverallMetrics:
    precision: float
    recall: float
    f1: float
    map50: float
    map50_95: float
    tp: int
    fp: int
    fn: int
    num_gt: int
    num_predictions: int


def _class_metrics_at_fixed_threshold(
    detections: Sequence[Detection],
    ground_truths: Sequence[GroundTruth],
    class_name: str,
    match_iou: float = 0.5,
) -> tuple:
    """Fixed-operating-point precision/recall/F1/TP/FP/FN for one class
    (all predictions passed in are used as-is — this is NOT a PR-curve sweep,
    it reflects the exact confidence threshold predictions were generated at).
    Also returns the MatchResult for duplicate-box / failure analysis.
    """
    match = greedy_match(detections, ground_truths, match_iou)
    tp = sum(match.tp)
    fp = sum(match.fp)
    fn = match.num_gt - tp
    precision = tp / (tp + fp) if (tp + fp) > 0 else (1.0 if match.num_gt == 0 else 0.0)
    recall = tp / match.num_gt if match.num_gt > 0 else (1.0 if len(detections) == 0 else 0.0)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return precision, recall, f1, tp, fp, fn, match


def evaluate_detections(
    detections: Sequence[Detection],
    ground_truths: Sequence[GroundTruth],
    class_names: Iterable[str],
    map_ious: Sequence[float] = (0.5,),
    fixed_threshold_iou: float = 0.5,
) -> tuple:
    """Full evaluation across all classes.

    Returns (overall: OverallMetrics, per_class: dict[str, ClassMetrics],
             matches_at_fixed_iou: dict[str, MatchResult]) — the last is exposed
    so callers (evaluate.py) can derive duplicate-box / failure-case records
    without re-running matching.
    """
    class_names = list(class_names)
    per_class: dict = {}
    matches_at_fixed_iou: dict = {}

    total_tp = total_fp = total_fn = 0
    total_gt = total_pred = 0
    map50_sum = 0.0
    map_5095_sum = 0.0
    n_classes_with_gt = 0

    for cname in class_names:
        cls_dets = [d for d in detections if d.class_name == cname]
        cls_gts = [g for g in ground_truths if g.class_name == cname]

        precision, recall, f1, tp, fp, fn, fixed_match = _class_metrics_at_fixed_threshold(
            cls_dets, cls_gts, cname, match_iou=fixed_threshold_iou
        )
        matches_at_fixed_iou[cname] = fixed_match

        ap_per_iou = {}
        for iou_t in map_ious:
            m = greedy_match(cls_dets, cls_gts, iou_t)
            precisions, recalls = precision_recall_from_match(m)
            ap_per_iou[iou_t] = average_precision(precisions, recalls)

        ap50 = ap_per_iou.get(0.5, 0.0)
        ap50_95 = sum(ap_per_iou.values()) / len(ap_per_iou) if ap_per_iou else 0.0

        per_class[cname] = ClassMetrics(
            class_name=cname,
            num_gt=len(cls_gts),
            num_predictions=len(cls_dets),
            tp=tp,
            fp=fp,
            fn=fn,
            precision=precision,
            recall=recall,
            f1=f1,
            ap50=ap50,
            ap50_95=ap50_95,
            ap_per_iou=ap_per_iou,
        )

        total_tp += tp
        total_fp += fp
        total_fn += fn
        total_gt += len(cls_gts)
        total_pred += len(cls_dets)

        if len(cls_gts) > 0:
            n_classes_with_gt += 1
            map50_sum += ap50
            map_5095_sum += ap50_95

    overall_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    overall_recall = total_tp / total_gt if total_gt > 0 else 0.0
    overall_f1 = (
        (2 * overall_precision * overall_recall / (overall_precision + overall_recall))
        if (overall_precision + overall_recall) > 0
        else 0.0
    )
    map50 = map50_sum / n_classes_with_gt if n_classes_with_gt > 0 else 0.0
    map50_95 = map_5095_sum / n_classes_with_gt if n_classes_with_gt > 0 else 0.0

    overall = OverallMetrics(
        precision=overall_precision,
        recall=overall_recall,
        f1=overall_f1,
        map50=map50,
        map50_95=map50_95,
        tp=total_tp,
        fp=total_fp,
        fn=total_fn,
        num_gt=total_gt,
        num_predictions=total_pred,
    )

    return overall, per_class, matches_at_fixed_iou
