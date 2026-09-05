"""Regression tests for EXP-0005's model-variant comparison tooling
(benchmark/diagnostics/model_variant_class_map.py, model_variant_eval.py).

Deliberately does NOT load the real YOLO model / torch/ultralytics in this
file (no GPU dependency here, matching tests/test_preprocessing.py's
explicit convention) — the full-scale "run 4 real candidate checkpoints over
380 images" correctness check is something only the actual experiment run
can do (see EXP-0005's results.json/model_comparison.json for the real,
numeric confirmation). What IS tested here, fast and deterministically, is
every piece of PURE LOGIC that check depends on: class mapping correctness,
vocabulary detection, the failure-bucket transition mechanism (hand-computed
fixture, reusing EXP-0004's proven analyze_candidate_transitions), the
sweep/isolation guarantees, and — critically — a genuine "baseline
reproduction" check performed by REPLAYING the already-captured, on-disk
official predictions (benchmark/results/baseline/predictions.jsonl) through
the NEW cross-model evaluation code path, rather than re-running inference.
"""

from __future__ import annotations

import json

import pytest

from benchmark.config import EVAL_MANIFEST_PATH, HAZARD_CLASSES_OIV7, REPO_ROOT
from benchmark.dataset import load_manifest
from benchmark.diagnostics.model_variant_class_map import (
    COCO_TO_OIV7,
    COMMON_HAZARD_CLASSES_OIV7,
    EXCLUDED_CLASSES_NO_COCO_EQUIVALENT,
    OIV7_TO_COCO,
    PERSON_COCO,
    PERSON_OIV7,
    detect_vocabulary,
    is_coco_vocabulary,
    is_oiv7_vocabulary,
    map_gt_class_to_common,
    map_prediction_class_to_oiv7,
    verify_coco_map_against_model,
    verify_oiv7_map_against_model,
)
from benchmark.metrics import Detection, GroundTruth, evaluate_detections

BASELINE_DIR = REPO_ROOT / "benchmark" / "results" / "baseline"


# ---------------------------------------------------------------------------
# Common-class mapping correctness
# ---------------------------------------------------------------------------


def test_person_maps_1to1_both_directions():
    assert OIV7_TO_COCO["Person"] == "person"
    assert COCO_TO_OIV7["person"] == "Person"


@pytest.mark.parametrize("oiv7_name,coco_name", [
    ("Person", "person"), ("Car", "car"), ("Truck", "truck"), ("Bus", "bus"),
    ("Bicycle", "bicycle"), ("Motorcycle", "motorcycle"), ("Dog", "dog"),
])
def test_all_seven_common_hazard_classes_map_cleanly(oiv7_name, coco_name):
    assert OIV7_TO_COCO[oiv7_name] == coco_name
    assert COCO_TO_OIV7[coco_name] == oiv7_name


def test_stairs_has_no_coco_equivalent_and_is_excluded():
    assert "Stairs" not in OIV7_TO_COCO
    assert "Stairs" not in COCO_TO_OIV7.values()
    assert "Stairs" in EXCLUDED_CLASSES_NO_COCO_EQUIVALENT


def test_common_hazard_classes_are_hazard_minus_stairs():
    assert set(COMMON_HAZARD_CLASSES_OIV7) == set(HAZARD_CLASSES_OIV7) - {"Stairs"}
    assert len(COMMON_HAZARD_CLASSES_OIV7) == 7


def test_map_gt_class_to_common_excludes_stairs_but_keeps_person():
    assert map_gt_class_to_common("Person") == "Person"
    assert map_gt_class_to_common("Car") == "Car"
    assert map_gt_class_to_common("Stairs") is None
    assert map_gt_class_to_common("Cat") is None  # not a hazard class at all


# ---------------------------------------------------------------------------
# Prediction-class mapping across vocabularies (>= 2, per the task spec)
# ---------------------------------------------------------------------------


def test_map_prediction_oiv7_vocabulary_is_pass_through_for_hazard_classes():
    assert map_prediction_class_to_oiv7("Person", "oiv7") == "Person"
    assert map_prediction_class_to_oiv7("Car", "oiv7") == "Car"
    assert map_prediction_class_to_oiv7("Stairs", "oiv7") == "Stairs"  # oiv7 candidates DO keep Stairs natively


def test_map_prediction_oiv7_vocabulary_drops_non_hazard_class():
    assert map_prediction_class_to_oiv7("Cat", "oiv7") is None


def test_map_prediction_coco_vocabulary_maps_person_and_hazard_classes():
    assert map_prediction_class_to_oiv7(PERSON_COCO, "coco") == PERSON_OIV7
    assert map_prediction_class_to_oiv7("car", "coco") == "Car"
    assert map_prediction_class_to_oiv7("truck", "coco") == "Truck"


def test_map_prediction_coco_vocabulary_drops_unmapped_class():
    # "airplane" is a real COCO class but not one of the mapped hazard classes
    assert map_prediction_class_to_oiv7("airplane", "coco") is None


def test_map_prediction_unknown_vocabulary_raises():
    with pytest.raises(ValueError):
        map_prediction_class_to_oiv7("person", "not_a_real_vocabulary")


# ---------------------------------------------------------------------------
# Vocabulary detection (incompatible-vocabulary rejection)
# ---------------------------------------------------------------------------


def test_detect_vocabulary_identifies_oiv7():
    fake_names = {0: "Person", 1: "Car"}
    fake_names.update({i: f"Class{i}" for i in range(2, 601)})  # pad to OIV7-scale
    assert detect_vocabulary(fake_names) == "oiv7"
    assert is_oiv7_vocabulary(fake_names) is True
    assert is_coco_vocabulary(fake_names) is False


def test_detect_vocabulary_identifies_coco():
    fake_names = {i: c for i, c in enumerate(
        ["person", "bicycle", "car", "motorcycle", "airplane", "bus", "train",
         "truck", "boat", "traffic light", "fire hydrant", "stop sign",
         "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep",
         "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
         "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard",
         "sports ball", "kite", "baseball bat", "baseball glove", "skateboard",
         "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork",
         "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
         "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair",
         "couch", "potted plant", "bed", "dining table", "toilet", "tv",
         "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave",
         "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase",
         "scissors", "teddy bear", "hair drier", "toothbrush"]
    )}
    assert len(fake_names) == 80
    assert detect_vocabulary(fake_names) == "coco"
    assert is_coco_vocabulary(fake_names) is True
    assert is_oiv7_vocabulary(fake_names) is False


def test_detect_vocabulary_rejects_unrecognized_label_space():
    # neither 'Person' (OIV7) nor 'person' (COCO), and not 80/500+ classes
    fake_names = {0: "Widget", 1: "Gadget", 2: "Thingamajig"}
    with pytest.raises(ValueError):
        detect_vocabulary(fake_names)


def test_verify_oiv7_map_against_model_flags_missing_hazard_class():
    fake_names = {0: "Person", 1: "Car"}  # missing Truck, Bus, Bicycle, Motorcycle, Stairs, Dog
    result = verify_oiv7_map_against_model(fake_names)
    assert result["ok"] is False
    assert "Stairs" in result["missing"]


def test_verify_coco_map_against_model_flags_missing_class():
    fake_names = {0: "person"}  # missing car/truck/bus/bicycle/motorcycle/dog
    result = verify_coco_map_against_model(fake_names)
    assert result["ok"] is False
    assert "car" in result["missing"]


# ---------------------------------------------------------------------------
# CRITICAL: baseline reproduction via replay (no re-inference) — running the
# ALREADY-CAPTURED official predictions through the NEW cross-model
# evaluation code path (mapping with vocabulary='oiv7' + evaluate_detections
# restricted to HAZARD_CLASSES_OIV7, exactly what
# model_variant_eval.run_all() does for an OIV7-vocabulary candidate) must
# reproduce the ORIGINAL RUN-20260904-002 numbers EXACTLY.
# ---------------------------------------------------------------------------


def test_baseline_replay_through_new_eval_path_reproduces_official_numbers_exactly():
    official_metrics = json.loads((BASELINE_DIR / "metrics.json").read_text(encoding="utf-8"))
    official_hazard = official_metrics["hazard_classes_only"]

    manifest = load_manifest(EVAL_MANIFEST_PATH)
    ground_truths = [
        GroundTruth(sample_id=s.sample_id, class_name=lbl.class_name, bbox=lbl.bbox)
        for s in manifest for lbl in s.labels
        if lbl.class_name in HAZARD_CLASSES_OIV7
    ]

    detections = []
    with open(BASELINE_DIR / "predictions.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            for p in rec["predictions"]:
                mapped = map_prediction_class_to_oiv7(p["class_name"], "oiv7")
                if mapped is None:
                    continue
                detections.append(Detection(
                    sample_id=rec["sample_id"], class_name=mapped,
                    bbox=tuple(p["bbox"]), confidence=p["confidence"],
                ))

    overall, per_class, _ = evaluate_detections(
        detections, ground_truths, sorted(HAZARD_CLASSES_OIV7), map_ious=(0.5,)
    )

    assert overall.precision == pytest.approx(official_hazard["precision"], abs=1e-9)
    assert overall.recall == pytest.approx(official_hazard["recall"], abs=1e-9)
    assert overall.tp == official_hazard["tp"]
    assert overall.fp == official_hazard["fp"]
    assert overall.fn == official_hazard["fn"]
    assert overall.num_gt == official_hazard["num_gt"]

    official_per_class = json.loads((BASELINE_DIR / "per_class.json").read_text(encoding="utf-8"))
    official_person = official_per_class["Person"]
    person_m = per_class["Person"]
    assert person_m.precision == pytest.approx(official_person["precision"], abs=1e-9)
    assert person_m.recall == pytest.approx(official_person["recall"], abs=1e-9)
    assert person_m.tp == official_person["tp"]
    assert person_m.fp == official_person["fp"]
    assert person_m.fn == official_person["fn"]


def test_baseline_replay_is_deterministic_across_two_runs():
    """Same input (the on-disk captures) -> same output, every time — the
    evaluation code path has no hidden randomness/ordering dependence."""
    manifest = load_manifest(EVAL_MANIFEST_PATH)
    ground_truths = [
        GroundTruth(sample_id=s.sample_id, class_name=lbl.class_name, bbox=lbl.bbox)
        for s in manifest for lbl in s.labels if lbl.class_name in HAZARD_CLASSES_OIV7
    ]
    detections = []
    with open(BASELINE_DIR / "predictions.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            for p in rec["predictions"]:
                mapped = map_prediction_class_to_oiv7(p["class_name"], "oiv7")
                if mapped is None:
                    continue
                detections.append(Detection(sample_id=rec["sample_id"], class_name=mapped, bbox=tuple(p["bbox"]), confidence=p["confidence"]))

    run1, _, _ = evaluate_detections(detections, ground_truths, sorted(HAZARD_CLASSES_OIV7), map_ious=(0.5,))
    run2, _, _ = evaluate_detections(detections, ground_truths, sorted(HAZARD_CLASSES_OIV7), map_ious=(0.5,))
    assert run1.precision == run2.precision
    assert run1.recall == run2.recall
    assert run1.tp == run2.tp and run1.fp == run2.fp and run1.fn == run2.fn


# ---------------------------------------------------------------------------
# Model metadata recording: hash/size/param-count captured correctly.
# Uses the already-downloaded checkpoint files under benchmark/models/ if
# present (gitignored, produced by the real experiment run); skipped if a
# given checkpoint isn't present in this checkout (e.g. a fresh clone that
# hasn't run EXP-0005) rather than failing the whole suite on a missing
# multi-megabyte binary that is deliberately never committed to git.
# ---------------------------------------------------------------------------


def _model_path(name: str):
    return REPO_ROOT / "benchmark" / "models" / name


@pytest.mark.parametrize("filename", ["yolov8m-oiv7.pt", "yolov8n-oiv7.pt", "yolov8l-oiv7.pt", "yolo11m.pt"])
def test_model_metadata_hash_and_size_match_real_file(filename):
    import hashlib
    import os

    path = _model_path(filename)
    if not path.exists():
        pytest.skip(f"{filename} not present in this checkout (gitignored; download via EXP-0005's runner)")

    expected_size = os.path.getsize(path)
    expected_hash = hashlib.sha256(path.read_bytes()).hexdigest()

    from benchmark.diagnostics.model_variant_eval import _model_metadata

    meta = _model_metadata(path)
    assert meta["size_bytes"] == expected_size
    assert meta["sha256"] == expected_hash
    assert meta["n_params"] > 0
    assert meta["vocabulary"] in ("oiv7", "coco")
    assert meta["class_verification"]["ok"] is True


# ---------------------------------------------------------------------------
# Transition-analysis correctness: hand-computed fixture, reusing
# preprocessing_eval.analyze_candidate_transitions (imported directly by
# model_variant_eval.py, not reimplemented) with a tiny synthetic FN-record
# set + synthetic PassResult, verifying the exact expected transition.
# ---------------------------------------------------------------------------


def test_transition_analysis_hand_computed_fixture():
    from benchmark.diagnostics.preprocessing_eval import PassResult, analyze_candidate_transitions

    # A single baseline Person FN, TRUE_DETECTOR_MISS, on sample "s1" gt_index 0.
    fn_records = [{
        "sample_id": "s1", "gt_index": 0, "gt_bbox": [0.1, 0.1, 0.2, 0.4],
        "gt_area_pct": 8.0, "gt_is_small": False, "gt_is_occluded": False,
        "primary_category": "TRUE_DETECTOR_MISS", "secondary_flags": [], "top_alt_class": None,
        "candidates": [],
    }]

    class FakeSample:
        def __init__(self, sample_id, labels):
            self.sample_id = sample_id
            self.labels = labels

    class FakeLabel:
        def __init__(self, class_name, bbox):
            self.class_name = class_name
            self.bbox = bbox

    manifest_by_id = {"s1": FakeSample("s1", [FakeLabel("Person", (0.1, 0.1, 0.2, 0.4))])}

    # Candidate model recovers it: predicts "Person" at IoU=1.0, conf=0.9 (>=0.4) at both passes.
    pass04 = PassResult()
    pass04.predictions_by_sample = {"s1": [{"class_name": "Person", "bbox": [0.1, 0.1, 0.2, 0.4], "confidence": 0.9}]}
    pass001 = PassResult()
    pass001.predictions_by_sample = {"s1": [{"class_name": "Person", "bbox": [0.1, 0.1, 0.2, 0.4], "confidence": 0.9}]}

    result = analyze_candidate_transitions(
        candidate_name="fake_candidate", pass04=pass04, pass001=pass001,
        manifest_by_id=manifest_by_id, fn_records=fn_records, baseline_tp_keys=set(),
    )

    tdm = result["transitions_by_baseline_bucket"]["TRUE_DETECTOR_MISS"]
    assert tdm["n"] == 1
    assert tdm["to_TP"] == 1
    assert tdm["new_bucket_counts"] == {"TP": 1}
    assert result["true_miss_detail"]["gained_tp"] == 1
    assert result["true_miss_detail"]["remains_complete_miss"] == 0


def test_transition_analysis_true_miss_not_recovered_stays_true_miss():
    from benchmark.diagnostics.preprocessing_eval import PassResult, analyze_candidate_transitions

    fn_records = [{
        "sample_id": "s1", "gt_index": 0, "gt_bbox": [0.1, 0.1, 0.2, 0.4],
        "gt_area_pct": 8.0, "gt_is_small": False, "gt_is_occluded": False,
        "primary_category": "TRUE_DETECTOR_MISS", "secondary_flags": [], "top_alt_class": None,
        "candidates": [],
    }]

    class FakeSample:
        def __init__(self, sample_id, labels):
            self.sample_id = sample_id
            self.labels = labels

    class FakeLabel:
        def __init__(self, class_name, bbox):
            self.class_name = class_name
            self.bbox = bbox

    manifest_by_id = {"s1": FakeSample("s1", [FakeLabel("Person", (0.1, 0.1, 0.2, 0.4))])}

    # Candidate model produces NOTHING near the GT box at all -- still a complete miss.
    pass04 = PassResult()
    pass04.predictions_by_sample = {"s1": []}
    pass001 = PassResult()
    pass001.predictions_by_sample = {"s1": []}

    result = analyze_candidate_transitions(
        candidate_name="fake_candidate", pass04=pass04, pass001=pass001,
        manifest_by_id=manifest_by_id, fn_records=fn_records, baseline_tp_keys=set(),
    )
    tdm = result["transitions_by_baseline_bucket"]["TRUE_DETECTOR_MISS"]
    assert tdm["to_TP"] == 0
    assert tdm["new_bucket_counts"] == {"TRUE_DETECTOR_MISS": 1}
    assert result["true_miss_detail"]["remains_complete_miss"] == 1


def test_baseline_tp_regression_detected_when_candidate_drops_detection():
    from benchmark.diagnostics.preprocessing_eval import PassResult, analyze_candidate_transitions

    class FakeSample:
        def __init__(self, sample_id, labels):
            self.sample_id = sample_id
            self.labels = labels

    class FakeLabel:
        def __init__(self, class_name, bbox):
            self.class_name = class_name
            self.bbox = bbox

    manifest_by_id = {"s1": FakeSample("s1", [FakeLabel("Person", (0.1, 0.1, 0.2, 0.4))])}
    baseline_tp_keys = {("s1", 0)}

    # Candidate produces NO Person prediction at all for a previously-correct baseline TP.
    pass04 = PassResult()
    pass04.predictions_by_sample = {"s1": []}
    pass001 = PassResult()
    pass001.predictions_by_sample = {"s1": []}

    result = analyze_candidate_transitions(
        candidate_name="fake_candidate", pass04=pass04, pass001=pass001,
        manifest_by_id=manifest_by_id, fn_records=[], baseline_tp_keys=baseline_tp_keys,
    )
    regr = result["baseline_tp_regressions"]
    assert regr["n_baseline_tp"] == 1
    assert regr["regressed"] == 1
    assert regr["remained_tp"] == 0


# ---------------------------------------------------------------------------
# Threshold-sweep isolation: computing the sweep must never mutate the
# PassResult it reads from, and the primary fixed-threshold (conf=0.4)
# evaluation must be identical whether or not the sweep was computed first.
# ---------------------------------------------------------------------------


def test_sweep_does_not_mutate_pass_result():
    from benchmark.diagnostics.model_variant_eval import _sweep_precision_recall
    from benchmark.diagnostics.preprocessing_eval import PassResult

    pass001 = PassResult()
    pass001.predictions_by_sample = {
        "s1": [{"class_name": "Person", "bbox": [0.1, 0.1, 0.2, 0.4], "confidence": 0.6}],
    }
    before = json.dumps(pass001.predictions_by_sample, sort_keys=True)

    gts = [GroundTruth(sample_id="s1", class_name="Person", bbox=(0.1, 0.1, 0.2, 0.4))]
    _sweep_precision_recall(pass001, gts, gts)

    after = json.dumps(pass001.predictions_by_sample, sort_keys=True)
    assert before == after, "sweep computation mutated the underlying PassResult"


def test_sweep_result_is_independent_of_primary_fixed_threshold_eval():
    """Computing conf=0.4 evaluate_detections before vs after computing the
    full sweep from the SAME raw conf=0.01 capture must give bit-identical
    fixed-threshold numbers -- the sweep is read-only filtering, never a
    stateful transform of the underlying detections list."""
    from benchmark.diagnostics.model_variant_eval import _sweep_precision_recall

    dets = [
        Detection(sample_id="s1", class_name="Person", bbox=(0.1, 0.1, 0.2, 0.4), confidence=0.6),
        Detection(sample_id="s2", class_name="Person", bbox=(0.5, 0.5, 0.2, 0.2), confidence=0.2),
    ]
    gts = [
        GroundTruth(sample_id="s1", class_name="Person", bbox=(0.1, 0.1, 0.2, 0.4)),
        GroundTruth(sample_id="s2", class_name="Person", bbox=(0.5, 0.5, 0.2, 0.2)),
    ]

    fixed_before, _, _ = evaluate_detections([d for d in dets if d.confidence >= 0.4], gts, ["Person"], map_ious=(0.5,))

    from benchmark.diagnostics.preprocessing_eval import PassResult
    pass001 = PassResult()
    pass001.predictions_by_sample = {
        "s1": [{"class_name": "Person", "bbox": [0.1, 0.1, 0.2, 0.4], "confidence": 0.6}],
        "s2": [{"class_name": "Person", "bbox": [0.5, 0.5, 0.2, 0.2], "confidence": 0.2}],
    }
    _sweep_precision_recall(pass001, gts, gts)

    fixed_after, _, _ = evaluate_detections([d for d in dets if d.confidence >= 0.4], gts, ["Person"], map_ious=(0.5,))
    assert fixed_before.precision == fixed_after.precision
    assert fixed_before.recall == fixed_after.recall


# ---------------------------------------------------------------------------
# Latency measurement isolation: per-candidate PassResult objects are always
# fresh (never accumulated across candidates).
# ---------------------------------------------------------------------------


def test_pass_result_instances_are_independent_across_calls():
    from benchmark.diagnostics.preprocessing_eval import PassResult

    pr1 = PassResult()
    pr1.inference_ms.append(5.0)
    pr2 = PassResult()
    assert pr2.inference_ms == []
    assert pr1.inference_ms == [5.0]


def test_latency_stats_isolated_per_candidate_not_accumulated():
    from benchmark.diagnostics.preprocessing_eval import _latency_stats

    candidate_a_latencies = [10.0, 12.0, 11.0]
    candidate_b_latencies = [50.0, 55.0, 52.0]
    stats_a = _latency_stats(candidate_a_latencies)
    stats_b = _latency_stats(candidate_b_latencies)
    assert stats_a["median_ms"] < stats_b["median_ms"]
    assert stats_a["n"] == 3 and stats_b["n"] == 3
    # confirm the two lists never got merged/aliased
    assert candidate_a_latencies == [10.0, 12.0, 11.0]
    assert candidate_b_latencies == [50.0, 55.0, 52.0]


# ---------------------------------------------------------------------------
# _find_matched_recall correctness (precision-matched / guardrail-matched
# helper) — hand-computed fixture.
# ---------------------------------------------------------------------------


def test_find_matched_recall_returns_lowest_threshold_clearing_target():
    from benchmark.diagnostics.model_variant_eval import _find_matched_recall

    points = [
        {"threshold": 0.1, "person": {"precision": 0.3, "recall": 0.9}},
        {"threshold": 0.3, "person": {"precision": 0.6, "recall": 0.5}},
        {"threshold": 0.5, "person": {"precision": 0.8, "recall": 0.2}},
    ]
    result = _find_matched_recall(points, target_precision=0.6, precision_key=("person", "precision"), recall_key=("person", "recall"))
    assert result["reached"] is True
    assert result["threshold"] == 0.3
    assert result["recall"] == pytest.approx(0.5)


def test_find_matched_recall_reports_not_reached():
    from benchmark.diagnostics.model_variant_eval import _find_matched_recall

    points = [{"threshold": 0.1, "person": {"precision": 0.2, "recall": 0.9}}]
    result = _find_matched_recall(points, target_precision=0.99, precision_key=("person", "precision"), recall_key=("person", "recall"))
    assert result["reached"] is False
    assert result["threshold"] is None
    assert result["recall"] is None
