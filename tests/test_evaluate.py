"""Regression tests for benchmark/evaluate.py's failure classification.

Covers the bug found during the Phase B validation pass: _classify_failure
used to match a missed ground-truth box's occlusion/size signals by
class_name only, so images with multiple same-class ground-truth boxes could
misattribute occlusion/size signals from the WRONG box. Fixed by matching on
(class_name, bbox).
"""

from __future__ import annotations

from benchmark.dataset import BoxLabel
from benchmark.evaluate import _bbox_close, _classify_failure


def _lbl(class_name, bbox, is_occluded=False, is_truncated=False, is_group_of=False):
    return BoxLabel(
        class_name=class_name,
        bbox=bbox,
        is_occluded=is_occluded,
        is_truncated=is_truncated,
        is_group_of=is_group_of,
    )


# ---------------------------------------------------------------------------
# _bbox_close
# ---------------------------------------------------------------------------


def test_bbox_close_identical():
    assert _bbox_close((0.1, 0.2, 0.3, 0.4), (0.1, 0.2, 0.3, 0.4))


def test_bbox_close_within_eps():
    assert _bbox_close((0.1, 0.2, 0.3, 0.4), (0.1 + 1e-9, 0.2, 0.3, 0.4))


def test_bbox_close_different():
    assert not _bbox_close((0.1, 0.2, 0.3, 0.4), (0.5, 0.2, 0.3, 0.4))


# ---------------------------------------------------------------------------
# _classify_failure: the actual bug being regression-tested
# ---------------------------------------------------------------------------


def test_classify_failure_multi_same_class_boxes_uses_correct_box_not_occluded():
    """The bug: two Bicycle boxes in one image, first one occluded, second one
    NOT occluded but small. Without gt_bbox (old buggy behavior), the second
    box's failure would incorrectly be classified using the FIRST box's
    is_occluded=True. With gt_bbox, it must correctly resolve to whichever
    category fits the SPECIFIC missed box."""
    occluded_box = _lbl("Bicycle", (0.0, 0.0, 0.5, 0.5), is_occluded=True)  # large, occluded
    small_not_occluded_box = _lbl("Bicycle", (0.5, 0.5, 0.05, 0.05), is_occluded=False)  # small, not occluded
    labels = [occluded_box, small_not_occluded_box]

    # Old buggy behavior (no gt_bbox) would find the FIRST Bicycle label (occluded_box)
    # regardless of which one was actually missed.
    result_no_bbox = _classify_failure("Bicycle", labels, n_boxes_in_image=2, is_hazard=True, kind="missed")
    assert result_no_bbox == "occlusion"  # ambiguous fallback picks the first same-class label

    # Fixed behavior: passing the SPECIFIC missed box's bbox resolves correctly.
    result_correct = _classify_failure(
        "Bicycle", labels, n_boxes_in_image=2, is_hazard=True, kind="missed",
        gt_bbox=small_not_occluded_box.bbox,
    )
    assert result_correct == "small_object"  # NOT "occlusion" — this is the fix

    result_correct_other = _classify_failure(
        "Bicycle", labels, n_boxes_in_image=2, is_hazard=True, kind="missed",
        gt_bbox=occluded_box.bbox,
    )
    assert result_correct_other == "occlusion"


def test_classify_failure_single_box_occluded():
    labels = [_lbl("Person", (0.1, 0.1, 0.2, 0.2), is_occluded=True)]
    result = _classify_failure(
        "Person", labels, n_boxes_in_image=1, is_hazard=True, kind="missed", gt_bbox=(0.1, 0.1, 0.2, 0.2)
    )
    assert result == "occlusion"


def test_classify_failure_small_object():
    labels = [_lbl("Person", (0.0, 0.0, 0.05, 0.05))]  # area = 0.0025 < 0.02
    result = _classify_failure(
        "Person", labels, n_boxes_in_image=1, is_hazard=True, kind="missed", gt_bbox=(0.0, 0.0, 0.05, 0.05)
    )
    assert result == "small_object"


def test_classify_failure_clutter():
    labels = [_lbl("Person", (0.0, 0.0, 0.5, 0.5))]  # not small, not occluded
    result = _classify_failure(
        "Person", labels, n_boxes_in_image=9, is_hazard=True, kind="missed", gt_bbox=(0.0, 0.0, 0.5, 0.5)
    )
    assert result == "clutter"


def test_classify_failure_plain_missed_detection():
    labels = [_lbl("Person", (0.0, 0.0, 0.5, 0.5))]
    result = _classify_failure(
        "Person", labels, n_boxes_in_image=3, is_hazard=True, kind="missed", gt_bbox=(0.0, 0.0, 0.5, 0.5)
    )
    assert result == "missed_detection"


def test_classify_failure_duplicate_and_false_positive_ignore_bbox():
    assert _classify_failure("Person", [], 0, True, "duplicate") == "duplicate_detection"
    assert _classify_failure("Person", [], 0, True, "false_positive") == "false_positive"


def test_classify_failure_no_matching_label_falls_back_to_missed_detection():
    labels = [_lbl("Car", (0.0, 0.0, 0.5, 0.5))]
    result = _classify_failure(
        "Person", labels, n_boxes_in_image=1, is_hazard=True, kind="missed", gt_bbox=(0.0, 0.0, 0.5, 0.5)
    )
    assert result == "missed_detection"
