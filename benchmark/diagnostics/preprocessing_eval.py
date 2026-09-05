"""EXP-0004 (preprocessing) diagnostic evaluation script.

Standalone script — NOT part of benchmark/evaluate.py's production path, does
NOT touch benchmark/config.py, benchmark/model.py, or benchmark/results/
baseline/ (the canonical RUN-20260904-002 baseline is read-only reference
data here). Runs REAL inference over the eval manifest for each pre-
registered preprocessing candidate in benchmark/diagnostics/preprocessing.py
(identity control + CLAHE + unsharp-mask + gamma + auto-contrast-stretch),
at the app's exact operating point (imgsz=640, conf=0.4, iou=0.7, same
weights, same manifest) — preprocessing is the ONLY changed variable.

For every candidate, two real inference passes are run:
  - conf=0.4 (the production operating point) -> official hazard/Person
    precision/recall/F1/AP50, and the "final" candidate metrics fed to
    research/evaluation_policy.py.
  - conf=0.01 (mirrors Phase B.5's low_conf_predictions.jsonl / EXP-0003's
    diagnostic capture pattern) -> full raw detection pool used for the
    failure-bucket-transition, confidence-distribution, localization, and
    true-miss analyses below (§4-9 of the EXP-0004 task spec).

Reuses benchmark.metrics.greedy_match (avoids the historical multi-instance
matching bug already fixed there) and, for the per-FN bucket-transition
analysis, reuses benchmark.diagnostics.person_confusion_analysis's matching/
classification primitives directly (_match_person_boxes_in_sample,
_classify_one, Candidate, and its floors) rather than re-deriving a second,
possibly-drifting copy of that decision tree.

Run with: uv run python -m benchmark.diagnostics.preprocessing_eval
Writes:
  - benchmark/results/diagnostics/preprocessing/<candidate>_conf0.4.jsonl
  - benchmark/results/diagnostics/preprocessing/<candidate>_conf0.01.jsonl
  - benchmark/results/diagnostics/preprocessing_analysis.json
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from benchmark.config import (
    CONF_THRESHOLD,
    EVAL_MANIFEST_PATH,
    HAZARD_CLASSES_OIV7,
    IMGSZ,
    IOU_THRESHOLD,
    RAW_IMAGE_DIR,
    REPO_ROOT,
)
from benchmark.dataset import assert_eval_only, load_manifest
from benchmark.diagnostics import preprocessing as prep
from benchmark.diagnostics.human_class_map import HUMAN_LIKE_CLASSES, PERSON_SUBPARTS, WHOLE_PERSON_ALIASES
from benchmark.diagnostics.person_confusion_analysis import (
    BASELINE_CONF,
    CONF_NOISE_FLOOR,
    DIAG_CONF_FLOOR_C,
    MATCH_IOU,
    SMALL_OBJECT_AREA_PCT,
    SPATIAL_ASSOC_IOU,
    Candidate,
    _classify_one,
    _match_person_boxes_in_sample,
)
from benchmark.metrics import Detection, GroundTruth, evaluate_detections, greedy_match, iou_xywh
from benchmark.model import BaselineModel

DIAG_DIR = REPO_ROOT / "benchmark" / "results" / "diagnostics"
OUT_DIR = DIAG_DIR / "preprocessing"
ANALYSIS_OUT_PATH = DIAG_DIR / "preprocessing_analysis.json"
FN_RECORDS_PATH = DIAG_DIR / "person_confusion_analysis.json"
BASELINE_PRED_PATH = REPO_ROOT / "benchmark" / "results" / "baseline" / "predictions.jsonl"
BASELINE_METRICS_PATH = REPO_ROOT / "benchmark" / "results" / "baseline" / "metrics.json"
BASELINE_PER_CLASS_PATH = REPO_ROOT / "benchmark" / "results" / "baseline" / "per_class.json"

LOW_CONF_PROBE = 0.01
LOW_CONF_NOISE_FLOOR = CONF_NOISE_FLOOR  # reuse EXP-0003's floor (0.05) for candidate-pool purposes

CANDIDATE_ORDER = ("identity", "clahe", "unsharp", "gamma", "autocontrast")


# ---------------------------------------------------------------------------
# Inference passes
# ---------------------------------------------------------------------------


@dataclass
class PassResult:
    predictions_by_sample: dict = field(default_factory=dict)  # sample_id -> list[dict]
    preprocess_ms: list = field(default_factory=list)
    inference_ms: list = field(default_factory=list)
    skipped: list = field(default_factory=list)  # sample_ids that failed to load/decode


def run_pass(model: BaselineModel, samples: list, candidate_name: str, conf: float) -> PassResult:
    pr = PassResult()
    for sample in samples:
        image_path = RAW_IMAGE_DIR / sample.filename
        try:
            img = prep.load_image_bgr(image_path)
        except prep.PreprocessingError as e:
            pr.skipped.append({"sample_id": sample.sample_id, "reason": str(e)})
            continue

        t0 = time.perf_counter()
        transformed = prep.apply_candidate(candidate_name, img)
        t1 = time.perf_counter()
        pr.preprocess_ms.append((t1 - t0) * 1000.0)

        results = model._model.predict(
            source=transformed, imgsz=IMGSZ, conf=conf, iou=IOU_THRESHOLD,
            device=model.device, verbose=False, batch=1,
        )
        t2 = time.perf_counter()
        pr.inference_ms.append((t2 - t1) * 1000.0)

        result = results[0]
        preds = []
        if result.boxes is not None and len(result.boxes) > 0:
            img_h, img_w = result.orig_shape
            for box in result.boxes:
                cls_idx = int(box.cls.item())
                class_name = model.class_names[cls_idx]
                bconf = float(box.conf.item())
                x1, y1, x2, y2 = (v.item() for v in box.xyxy[0])
                bbox = (x1 / img_w, y1 / img_h, (x2 - x1) / img_w, (y2 - y1) / img_h)
                preds.append({"class_name": class_name, "bbox": list(bbox), "confidence": bconf})
        pr.predictions_by_sample[sample.sample_id] = preds
    return pr


def _detections_from_pass(pr: PassResult) -> list:
    dets = []
    for sample_id, preds in pr.predictions_by_sample.items():
        for p in preds:
            dets.append(Detection(sample_id=sample_id, class_name=p["class_name"], bbox=tuple(p["bbox"]), confidence=p["confidence"]))
    return dets


def _percentile(values: list, q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    idx = min(n - 1, int(round(q * (n - 1))))
    return s[idx]


def _latency_stats(values: list) -> dict:
    return {
        "median_ms": _percentile(values, 0.5),
        "p95_ms": _percentile(values, 0.95),
        "mean_ms": (sum(values) / len(values)) if values else 0.0,
        "n": len(values),
    }


# ---------------------------------------------------------------------------
# FN-record / TP-regression per-candidate re-classification (reuses
# person_confusion_analysis.py's matching + decision-tree primitives).
# ---------------------------------------------------------------------------


def _build_candidate_pool(gt_bbox, low_conf_all: list, exclude_bboxes: set) -> list:
    """Mirror person_confusion_analysis._candidate_pool_for, but against an
    arbitrary (candidate) low-confidence prediction list instead of the
    fixed on-disk low_conf_predictions.jsonl."""
    pool = []
    for p in low_conf_all:
        key = tuple(round(v, 6) for v in p["bbox"])
        if p["class_name"] == "Person" and key in exclude_bboxes:
            continue
        i = iou_xywh(gt_bbox, tuple(p["bbox"]))
        if i <= 0.0:
            continue
        pool.append(Candidate(
            class_name=p["class_name"], confidence=p["confidence"], bbox=tuple(p["bbox"]),
            iou=i, is_baseline_prediction=p["confidence"] >= BASELINE_CONF,
        ))
    return pool


def _person_gts_for_sample(sample) -> list:
    return [lbl.bbox for lbl in sample.labels if lbl.class_name == "Person"]


def _candidate_match_for_sample(person_preds_04: list, person_gt_bboxes: list) -> tuple:
    """Returns (claimed_gt_idx, claimed_pred_bboxes) for one sample under one
    candidate's own conf=0.4 predictions — the exact same greedy-match
    procedure the baseline uses to decide TP/FN, just fed the candidate's
    own detections instead of the baseline's."""
    if not person_gt_bboxes:
        return set(), set()
    claimed_gt_idx, claimed_pred_idx = _match_person_boxes_in_sample(person_preds_04, person_gt_bboxes)
    claimed_pred_bboxes = {tuple(round(v, 6) for v in person_preds_04[i]["bbox"]) for i in claimed_pred_idx}
    return claimed_gt_idx, claimed_pred_bboxes


def analyze_candidate_transitions(
    candidate_name: str,
    pass04: PassResult,
    pass001: PassResult,
    manifest_by_id: dict,
    fn_records: list,
    baseline_tp_keys: set,
) -> dict:
    """For one candidate: FN bucket transitions (§4), size split (§5),
    confidence-distribution shift for LOW_CONFIDENCE_PERSON (§6),
    localization/IoU shift for LOCALIZATION_FAILURE (§7), true-miss recovery
    for TRUE_DETECTOR_MISS (§8), and regressions among baseline TPs (§4)."""
    # Pre-index per-sample Person predictions at conf=0.4 and full low-conf pool.
    person_preds_04_by_sample = {
        sid: [p for p in preds if p["class_name"] == "Person"]
        for sid, preds in pass04.predictions_by_sample.items()
    }
    match_cache: dict = {}

    def _match_for(sample_id: str):
        if sample_id in match_cache:
            return match_cache[sample_id]
        sample = manifest_by_id[sample_id]
        gt_bboxes = _person_gts_for_sample(sample)
        person_preds_04 = person_preds_04_by_sample.get(sample_id, [])
        claimed_gt_idx, claimed_pred_bboxes = _candidate_match_for_sample(person_preds_04, gt_bboxes)
        low_conf_all = pass001.predictions_by_sample.get(sample_id, [])
        match_cache[sample_id] = (claimed_gt_idx, claimed_pred_bboxes, low_conf_all)
        return match_cache[sample_id]

    # ---- §4/§8: per-FN transitions ----
    transitions_by_baseline_bucket: dict = {}
    small_split: dict = {"small": {"n": 0}, "non_small": {"n": 0}}
    for bucket in ("TRUE_DETECTOR_MISS", "LOW_CONFIDENCE_PERSON", "SEMANTIC_CLASS_CONFUSION", "LOCALIZATION_FAILURE"):
        transitions_by_baseline_bucket[bucket] = {"n": 0, "to_TP": 0, "new_bucket_counts": {}}

    true_miss_detail = {"gained_any_person_candidate": 0, "gained_tp": 0, "gained_other_human_class": 0, "remains_complete_miss": 0}
    low_conf_conf_shifts = []  # per-record dicts for §6
    localization_iou_shifts = []  # per-record dicts for §7
    size_transitions = {
        "small": {b: {"n": 0, "to_TP": 0} for b in transitions_by_baseline_bucket},
        "non_small": {b: {"n": 0, "to_TP": 0} for b in transitions_by_baseline_bucket},
    }

    for rec in fn_records:
        sample_id = rec["sample_id"]
        gi = rec["gt_index"]
        bucket = rec["primary_category"]
        gt_bbox = tuple(rec["gt_bbox"])
        size_key = "small" if rec["gt_is_small"] else "non_small"

        claimed_gt_idx, claimed_pred_bboxes, low_conf_all = _match_for(sample_id)
        transitions_by_baseline_bucket[bucket]["n"] += 1
        size_transitions[size_key][bucket]["n"] += 1

        became_tp = gi in claimed_gt_idx
        if became_tp:
            transitions_by_baseline_bucket[bucket]["to_TP"] += 1
            size_transitions[size_key][bucket]["to_TP"] += 1
            new_bucket = "TP"
        else:
            pool = _build_candidate_pool(gt_bbox, low_conf_all, claimed_pred_bboxes)
            new_primary, _secondary, _alt = _classify_one(gt_bbox, pool)
            new_bucket = new_primary
        transitions_by_baseline_bucket[bucket]["new_bucket_counts"][new_bucket] = (
            transitions_by_baseline_bucket[bucket]["new_bucket_counts"].get(new_bucket, 0) + 1
        )

        # §6: confidence-distribution shift for LOW_CONFIDENCE_PERSON
        if bucket == "LOW_CONFIDENCE_PERSON":
            base_person_candidates = [c for c in rec["candidates"] if c["class_name"] == "Person"]
            base_top = max(base_person_candidates, key=lambda c: c["confidence"]) if base_person_candidates else None
            base_conf = base_top["confidence"] if base_top else None
            base_iou = base_top["iou"] if base_top else None
            if became_tp:
                cand_person_here = [
                    p for p in person_preds_04_by_sample.get(sample_id, [])
                    if iou_xywh(gt_bbox, tuple(p["bbox"])) >= SPATIAL_ASSOC_IOU
                ]
                cand_top = max(cand_person_here, key=lambda p: p["confidence"]) if cand_person_here else None
                cand_conf = cand_top["confidence"] if cand_top else None
                cand_iou = iou_xywh(gt_bbox, tuple(cand_top["bbox"])) if cand_top else None
            else:
                pool = _build_candidate_pool(gt_bbox, low_conf_all, claimed_pred_bboxes)
                person_pool = [c for c in pool if c.class_name == "Person"]
                cand_top_c = max(person_pool, key=lambda c: c.confidence) if person_pool else None
                cand_conf = cand_top_c.confidence if cand_top_c else None
                cand_iou = cand_top_c.iou if cand_top_c else None

            if cand_conf is None:
                direction = "disappeared"
                delta = None
            elif base_conf is None:
                direction = "new_person_candidate_appeared"
                delta = None
            else:
                delta = cand_conf - base_conf
                direction = "raised" if delta > 0.005 else ("lowered" if delta < -0.005 else "unchanged")
            low_conf_conf_shifts.append({
                "sample_id": sample_id, "gt_index": gi,
                "baseline_conf": base_conf, "candidate_conf": cand_conf, "delta": delta, "direction": direction,
                "baseline_iou": base_iou, "candidate_iou": cand_iou,
                "crossed_threshold": bool(cand_conf is not None and cand_conf >= CONF_THRESHOLD and (cand_iou or 0) >= MATCH_IOU),
            })

        # §7: localization shift for LOCALIZATION_FAILURE
        if bucket == "LOCALIZATION_FAILURE":
            human_candidates = [c for c in rec["candidates"] if c["class_name"] in HUMAN_LIKE_CLASSES]
            base_top = max(human_candidates, key=lambda c: c["iou"]) if human_candidates else None
            base_iou = base_top["iou"] if base_top else 0.0
            base_bbox = base_top["bbox"] if base_top else None
            if became_tp:
                cand_human = [p for p in person_preds_04_by_sample.get(sample_id, []) if iou_xywh(gt_bbox, tuple(p["bbox"])) > 0]
                cand_top = max(cand_human, key=lambda p: iou_xywh(gt_bbox, tuple(p["bbox"]))) if cand_human else None
                cand_iou = iou_xywh(gt_bbox, tuple(cand_top["bbox"])) if cand_top else 0.0
                cand_bbox = cand_top["bbox"] if cand_top else None
            else:
                pool = _build_candidate_pool(gt_bbox, low_conf_all, claimed_pred_bboxes)
                human_pool = [c for c in pool if c.class_name in HUMAN_LIKE_CLASSES]
                cand_top_c = max(human_pool, key=lambda c: c.iou) if human_pool else None
                cand_iou = cand_top_c.iou if cand_top_c else 0.0
                cand_bbox = list(cand_top_c.bbox) if cand_top_c else None
            localization_iou_shifts.append({
                "sample_id": sample_id, "gt_index": gi,
                "baseline_iou": base_iou, "candidate_iou": cand_iou, "delta_iou": cand_iou - base_iou,
                "crossed_match_threshold": cand_iou >= MATCH_IOU,
                "baseline_bbox": base_bbox, "candidate_bbox": cand_bbox, "gt_bbox": list(gt_bbox),
            })

        # §8: true-miss recovery detail for TRUE_DETECTOR_MISS
        if bucket == "TRUE_DETECTOR_MISS":
            if became_tp:
                true_miss_detail["gained_tp"] += 1
                true_miss_detail["gained_any_person_candidate"] += 1
            else:
                pool = _build_candidate_pool(gt_bbox, low_conf_all, claimed_pred_bboxes)
                person_pool = [c for c in pool if c.class_name == "Person"]
                human_pool = [c for c in pool if c.class_name in HUMAN_LIKE_CLASSES and c.class_name != "Person"]
                if person_pool:
                    true_miss_detail["gained_any_person_candidate"] += 1
                elif human_pool:
                    true_miss_detail["gained_other_human_class"] += 1
                else:
                    true_miss_detail["remains_complete_miss"] += 1

    # ---- baseline-TP regression check ----
    regressions = {"n_baseline_tp": len(baseline_tp_keys), "remained_tp": 0, "regressed": 0, "regression_detail": []}
    for (sample_id, gi) in baseline_tp_keys:
        claimed_gt_idx, claimed_pred_bboxes, low_conf_all = _match_for(sample_id)
        if gi in claimed_gt_idx:
            regressions["remained_tp"] += 1
        else:
            regressions["regressed"] += 1
            sample = manifest_by_id[sample_id]
            gt_bboxes = _person_gts_for_sample(sample)
            gt_bbox = gt_bboxes[gi]
            pool = _build_candidate_pool(gt_bbox, low_conf_all, claimed_pred_bboxes)
            new_primary, _sec, _alt = _classify_one(gt_bbox, pool)
            regressions["regression_detail"].append({"sample_id": sample_id, "gt_index": gi, "new_state": new_primary})

    return {
        "transitions_by_baseline_bucket": transitions_by_baseline_bucket,
        "size_transitions": size_transitions,
        "true_miss_detail": true_miss_detail,
        "low_confidence_person_shifts": low_conf_conf_shifts,
        "localization_failure_shifts": localization_iou_shifts,
        "baseline_tp_regressions": regressions,
    }


def _baseline_tp_keys(manifest: list) -> set:
    baseline_preds = {}
    with open(BASELINE_PRED_PATH, "r", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            baseline_preds[d["sample_id"]] = d["predictions"]
    keys = set()
    for sample in manifest:
        person_gts = _person_gts_for_sample(sample)
        if not person_gts:
            continue
        person_preds = [p for p in baseline_preds.get(sample.sample_id, []) if p["class_name"] == "Person"]
        claimed_gt_idx, _ = _match_person_boxes_in_sample(person_preds, person_gts)
        for gi in claimed_gt_idx:
            keys.add((sample.sample_id, gi))
    return keys


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def run_all() -> dict:
    if not FN_RECORDS_PATH.exists():
        raise RuntimeError(
            f"missing EXP-0003 FN classification: {FN_RECORDS_PATH} — EXP-0004's failure-bucket "
            "transition analysis depends on it (see person_confusion_analysis.py::main())."
        )
    fn_data = json.loads(FN_RECORDS_PATH.read_text(encoding="utf-8"))
    fn_records = fn_data["records"]

    manifest = load_manifest(EVAL_MANIFEST_PATH)
    assert_eval_only(manifest)
    manifest_by_id = {s.sample_id: s for s in manifest}

    ground_truths = []
    for sample in manifest:
        for lbl in sample.labels:
            ground_truths.append(GroundTruth(sample_id=sample.sample_id, class_name=lbl.class_name, bbox=lbl.bbox))

    baseline_tp_keys = _baseline_tp_keys(manifest)

    model = BaselineModel()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    baseline_metrics_ref = json.loads(BASELINE_METRICS_PATH.read_text(encoding="utf-8"))
    baseline_per_class_ref = json.loads(BASELINE_PER_CLASS_PATH.read_text(encoding="utf-8"))

    per_candidate: dict = {}
    log_lines: list = []

    for name in CANDIDATE_ORDER:
        spec = prep.CANDIDATE_REGISTRY[name]
        t_start = time.perf_counter()
        pass04 = run_pass(model, manifest, name, CONF_THRESHOLD)
        pass001 = run_pass(model, manifest, name, LOW_CONF_PROBE)
        t_end = time.perf_counter()

        # persist raw captures
        with open(OUT_DIR / f"{name}_conf0.4.jsonl", "w", encoding="utf-8") as f:
            for sid, preds in pass04.predictions_by_sample.items():
                f.write(json.dumps({"sample_id": sid, "predictions": preds}) + "\n")
        with open(OUT_DIR / f"{name}_conf0.01.jsonl", "w", encoding="utf-8") as f:
            for sid, preds in pass001.predictions_by_sample.items():
                f.write(json.dumps({"sample_id": sid, "predictions": preds}) + "\n")

        dets04 = _detections_from_pass(pass04)
        hazard_overall, per_class, _matches = evaluate_detections(
            dets04, ground_truths, sorted(HAZARD_CLASSES_OIV7), map_ious=(0.5,)
        )
        person_m = per_class.get("Person")

        preprocess_lat = _latency_stats(pass04.preprocess_ms)
        inference_lat = _latency_stats(pass04.inference_ms)
        total_ms = [a + b for a, b in zip(pass04.preprocess_ms, pass04.inference_ms)]
        total_lat = _latency_stats(total_ms)

        transitions = analyze_candidate_transitions(name, pass04, pass001, manifest_by_id, fn_records, baseline_tp_keys)

        per_candidate[name] = {
            "params": spec["params"],
            "hypothesis": spec["hypothesis"],
            "hazard": {
                "precision": hazard_overall.precision, "recall": hazard_overall.recall,
                "f1": hazard_overall.f1, "map50": hazard_overall.map50,
                "tp": hazard_overall.tp, "fp": hazard_overall.fp, "fn": hazard_overall.fn,
                "num_gt": hazard_overall.num_gt,
            },
            "person": {
                "precision": person_m.precision, "recall": person_m.recall, "f1": person_m.f1,
                "ap50": person_m.ap50, "tp": person_m.tp, "fp": person_m.fp, "fn": person_m.fn,
                "num_gt": person_m.num_gt,
            },
            "latency": {
                "preprocess_ms": preprocess_lat,
                "inference_ms": inference_lat,
                "total_ms": total_lat,
                "note": "Windows/CUDA inference-compute proxy only — not iPhone, not end-to-end. "
                        "preprocess_ms times ONLY the candidate's pixel-transform function; "
                        "inference_ms times ONLY the ultralytics model.predict() call. Never conflated.",
            },
            "skipped_images": pass04.skipped,
            "n_images_evaluated": len(pass04.predictions_by_sample),
            "wall_clock_sec_both_passes": t_end - t_start,
            **transitions,
        }
        log_lines.append(
            f"[{name}] hazard P={hazard_overall.precision:.4f} R={hazard_overall.recall:.4f} | "
            f"person P={person_m.precision:.4f} R={person_m.recall:.4f} F1={person_m.f1:.4f} AP50={person_m.ap50:.4f} | "
            f"preprocess p95={preprocess_lat['p95_ms']:.3f}ms inference p95={inference_lat['p95_ms']:.3f}ms | "
            f"skipped={len(pass04.skipped)}"
        )

    identity_reproduces_baseline = _check_identity_reproduces_baseline(per_candidate["identity"], baseline_metrics_ref, baseline_per_class_ref)
    log_lines.append(f"identity control reproduces official baseline exactly: {identity_reproduces_baseline['exact_match']}")

    return {
        "candidates": per_candidate,
        "candidate_order": list(CANDIDATE_ORDER),
        "baseline_reference": {
            "hazard": baseline_metrics_ref["hazard_classes_only"],
            "person": baseline_per_class_ref["Person"],
            "latency_p95_ms": baseline_metrics_ref["latency_ms"]["p95"],
            "run_id": baseline_metrics_ref["run_id"],
        },
        "identity_control_check": identity_reproduces_baseline,
        "num_baseline_person_fn": len(fn_records),
        "num_baseline_person_tp": len(baseline_tp_keys),
        "log_lines": log_lines,
    }


def _check_identity_reproduces_baseline(identity_result: dict, baseline_metrics_ref: dict, baseline_per_class_ref: dict) -> dict:
    ref_hazard = baseline_metrics_ref["hazard_classes_only"]
    ref_person = baseline_per_class_ref["Person"]
    checks = {
        "hazard.precision": (identity_result["hazard"]["precision"], ref_hazard["precision"]),
        "hazard.recall": (identity_result["hazard"]["recall"], ref_hazard["recall"]),
        "hazard.tp": (identity_result["hazard"]["tp"], ref_hazard["tp"]),
        "hazard.fp": (identity_result["hazard"]["fp"], ref_hazard["fp"]),
        "hazard.fn": (identity_result["hazard"]["fn"], ref_hazard["fn"]),
        "person.precision": (identity_result["person"]["precision"], ref_person["precision"]),
        "person.recall": (identity_result["person"]["recall"], ref_person["recall"]),
        "person.tp": (identity_result["person"]["tp"], ref_person["tp"]),
        "person.fp": (identity_result["person"]["fp"], ref_person["fp"]),
        "person.fn": (identity_result["person"]["fn"], ref_person["fn"]),
    }
    mismatches = {}
    for k, (got, want) in checks.items():
        if isinstance(got, float) or isinstance(want, float):
            if abs(got - want) > 1e-9:
                mismatches[k] = {"got": got, "want": want}
        else:
            if got != want:
                mismatches[k] = {"got": got, "want": want}
    return {"exact_match": len(mismatches) == 0, "mismatches": mismatches, "checks": checks}


def main() -> None:
    result = run_all()
    for line in result["log_lines"]:
        print(line)
    ANALYSIS_OUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {ANALYSIS_OUT_PATH}")


if __name__ == "__main__":
    main()
