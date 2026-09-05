"""EXP-0005 (model_variant) diagnostic evaluation script.

Standalone script — does NOT touch benchmark/config.py, benchmark/model.py,
or benchmark/results/baseline/ (the canonical RUN-20260904-002 baseline is
read-only reference data here, same discipline as
benchmark/diagnostics/preprocessing_eval.py). Runs REAL inference over the
eval manifest for each pre-registered model-variant candidate (a different
checkpoint/architecture, NOT a preprocessing transform) at a held-constant
input resolution (imgsz=640) and NMS IoU (0.7) — the ONLY changed variable
per candidate is the model weights/architecture itself.

For every candidate, two real inference passes are run (same convention as
EXP-0004):
  - conf=0.4 (the production operating point) -> official common-class
    hazard/Person precision/recall/F1/AP50, latency, and peak GPU memory.
  - conf=0.01 (mirrors Phase B.5 / EXP-0003 / EXP-0004's diagnostic-capture
    pattern) -> full raw detection pool used for the failure-bucket-
    transition, small-Person, and confidence-threshold-sweep analyses.

Reuses (never re-implements):
  - benchmark.metrics.greedy_match / evaluate_detections for ALL scoring.
  - benchmark.diagnostics.model_variant_class_map for vocabulary detection
    and COCO<->OIV7 class mapping.
  - benchmark.diagnostics.preprocessing_eval.{PassResult, analyze_candidate_
    transitions, _baseline_tp_keys, _latency_stats, _percentile} for the
    per-FN bucket-transition / baseline-TP-regression analysis — that logic
    only depends on a PassResult's predictions_by_sample shape (sample_id ->
    list of {class_name, bbox, confidence} dicts in OIV7-label space), which
    holds regardless of whether the underlying model swap is a preprocessing
    transform (EXP-0004) or a different checkpoint (EXP-0005). Duplicating
    it here would be exactly the kind of drifting second implementation this
    lab's own harness-audit discipline warns against.

Run with: uv run python -m benchmark.diagnostics.model_variant_eval
Writes:
  - benchmark/results/diagnostics/model_variant/<candidate>_conf0.4.jsonl
  - benchmark/results/diagnostics/model_variant/<candidate>_conf0.01.jsonl
  - benchmark/results/diagnostics/model_variant_analysis.json
"""

from __future__ import annotations

import json
import os
import time
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
from benchmark.diagnostics.model_variant_class_map import (
    COMMON_HAZARD_CLASSES_OIV7,
    EXCLUDED_CLASSES_NO_COCO_EQUIVALENT,
    PERSON_OIV7,
    detect_vocabulary,
    map_prediction_class_to_oiv7,
    verify_coco_map_against_model,
    verify_oiv7_map_against_model,
)
from benchmark.diagnostics.preprocessing_eval import (
    PassResult,
    _baseline_tp_keys,
    _latency_stats,
    analyze_candidate_transitions,
)
from benchmark.metrics import Detection, GroundTruth, evaluate_detections

DIAG_DIR = REPO_ROOT / "benchmark" / "results" / "diagnostics"
OUT_DIR = DIAG_DIR / "model_variant"
ANALYSIS_OUT_PATH = DIAG_DIR / "model_variant_analysis.json"
FN_RECORDS_PATH = DIAG_DIR / "person_confusion_analysis.json"
BASELINE_METRICS_PATH = REPO_ROOT / "benchmark" / "results" / "baseline" / "metrics.json"
BASELINE_PER_CLASS_PATH = REPO_ROOT / "benchmark" / "results" / "baseline" / "per_class.json"

LOW_CONF_PROBE = 0.01
SWEEP_THRESHOLDS = [round(0.05 * i, 2) for i in range(1, 20)]  # 0.05..0.95
HAZARD_PRECISION_GUARDRAIL = 0.757  # baseline_precision(0.807) - 0.05, per methodology.md

MODELS_DIR = REPO_ROOT / "benchmark" / "models"

# ---------------------------------------------------------------------------
# Pre-registered candidate set (see research/_exp0005_preregister.py for the
# full rationale/expected-tradeoff text; this dict is the executable half).
# ---------------------------------------------------------------------------
CANDIDATE_SPECS: dict = {
    "A_yolov8m_oiv7_baseline": {
        "path": MODELS_DIR / "yolov8m-oiv7.pt",
        "role": "current production baseline (unchanged)",
        "architecture_family": "YOLOv8 (medium)",
        "pretrained_dataset": "Open Images V7 (601 classes)",
        "source_url": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8m-oiv7.pt",
        "license": "AGPL-3.0 (Ultralytics OSS license) — commercial closed-source use (OmniSight is a paid/commercial App Store app) requires an Ultralytics Enterprise license, same as the currently-shipped model.",
        "reason_for_inclusion": "Reference point (A) — every other candidate is judged relative to this, already in production.",
        "attempt_coreml_export": True,
    },
    "B_yolov8n_oiv7_smaller": {
        "path": MODELS_DIR / "yolov8n-oiv7.pt",
        "role": "smaller/faster same-vocabulary candidate",
        "architecture_family": "YOLOv8 (nano)",
        "pretrained_dataset": "Open Images V7 (601 classes) — same vocabulary as baseline, no class mapping needed",
        "source_url": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n-oiv7.pt",
        "license": "AGPL-3.0 (Ultralytics OSS license) — commercial closed-source use requires Ultralytics Enterprise.",
        "reason_for_inclusion": "(B) smaller/faster variant — an official Ultralytics OIV7 release exists at nano size, so no COCO vocabulary compromise is needed for this probe; tests whether a lighter model (mobile-friendlier) can hold Person recall.",
        "attempt_coreml_export": True,
    },
    "C_yolo11m_coco_newer_arch": {
        "path": MODELS_DIR / "yolo11m.pt",
        "role": "newer-architecture, realistic-for-mobile candidate (COCO-trained)",
        "architecture_family": "YOLO11 (medium)",
        "pretrained_dataset": "COCO (80 classes) — no official Ultralytics OIV7-trained YOLO11 release exists; COCO is the only reliably-downloadable YOLO11 checkpoint via YOLO('yolo11m.pt') auto-download, per the methodology's requirement to verify actual availability before committing to a name.",
        "source_url": "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11m.pt",
        "license": "AGPL-3.0 (Ultralytics OSS license) — commercial closed-source use requires Ultralytics Enterprise.",
        "reason_for_inclusion": "(C) plausible stronger/newer pretrained detector realistic for eventual mobile deployment — a genuinely different architecture generation (YOLO11 vs YOLOv8), not just a bigger/smaller YOLOv8. Exercises the COCO<->OIV7 common-class mapping machinery (Stairs excluded, 7-of-8 hazard subset) since this is the only vocabulary-mismatched candidate in this experiment.",
        "attempt_coreml_export": False,
    },
    "D_yolov8l_oiv7_diagnostic_upper_bound": {
        "path": MODELS_DIR / "yolov8l-oiv7.pt",
        "role": "larger diagnostic upper-bound (explicitly labeled unlikely-to-ship)",
        "architecture_family": "YOLOv8 (large)",
        "pretrained_dataset": "Open Images V7 (601 classes) — same vocabulary as baseline",
        "source_url": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8l-oiv7.pt",
        "license": "AGPL-3.0 (Ultralytics OSS license) — commercial closed-source use requires Ultralytics Enterprise.",
        "reason_for_inclusion": "(D) optional larger diagnostic upper-bound purely to probe whether raw capacity increase (same architecture family/training data as baseline, just bigger) raises Person recall at all. EXPLICITLY LABELED UNLIKELY TO SHIP on a phone (88.6MB, ~44M params) — a capacity-ceiling probe, not a deployment candidate.",
        "attempt_coreml_export": False,
    },
}
CANDIDATE_ORDER = tuple(CANDIDATE_SPECS.keys())


def _model_metadata(path: Path) -> dict:
    import hashlib

    import torch
    from ultralytics import YOLO

    model = YOLO(str(path))
    n_params = sum(p.numel() for p in model.model.parameters())
    size_bytes = os.path.getsize(path)
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    vocabulary = detect_vocabulary(model.names)
    if vocabulary == "oiv7":
        verification = verify_oiv7_map_against_model(model.names)
    else:
        verification = verify_coco_map_against_model(model.names)
    if not verification["ok"]:
        raise RuntimeError(f"{path.name}: class map verification failed, missing={verification['missing']}")
    return {
        "model": model,
        "n_params": n_params,
        "size_bytes": size_bytes,
        "sha256": sha256,
        "vocabulary": vocabulary,
        "num_classes": len(model.names),
        "class_verification": verification,
    }


def _predict_raw(model, image_path: Path, conf: float, device: str) -> tuple:
    """Mirrors benchmark.model.BaselineModel.predict_at's pixel->normalized-
    xywh conversion exactly (same algorithm, generalized to an arbitrary
    ultralytics model object rather than the fixed-checkpoint BaselineModel,
    since this experiment evaluates checkpoints BaselineModel is not wired
    for). imgsz=640 and iou=0.7 are passed explicitly to every candidate's
    predict() call — held constant across all candidates regardless of any
    export-path default the checkpoint might otherwise carry, per the
    methodology's control-variable requirement."""
    results = model.predict(
        source=str(image_path), imgsz=IMGSZ, conf=conf, iou=IOU_THRESHOLD,
        device=device, verbose=False, batch=1,
    )
    result = results[0]
    preds = []
    if result.boxes is not None and len(result.boxes) > 0:
        img_h, img_w = result.orig_shape
        for box in result.boxes:
            cls_idx = int(box.cls.item())
            class_name = model.names[cls_idx]
            bconf = float(box.conf.item())
            x1, y1, x2, y2 = (v.item() for v in box.xyxy[0])
            bbox = (x1 / img_w, y1 / img_h, (x2 - x1) / img_w, (y2 - y1) / img_h)
            preds.append((class_name, bbox, bconf))
    return preds, result


def run_pass(model, vocabulary: str, samples: list, conf: float, device: str) -> tuple:
    """Returns (PassResult, peak_gpu_mem_bytes). Predictions are stored with
    class_name already mapped into OIV7 label space where a mapping exists
    (map_prediction_class_to_oiv7); an unmapped class is namespaced
    'coco::<raw>' so it can never collide with a real OIV7 name and is
    simply ignored by every hazard/Person metric below (harmless to keep for
    traceability). Deterministic: same model + same image + same conf/iou/
    imgsz always yields the same predictions (no randomness in ultralytics
    inference at eval time — no augmentation, no dropout at .eval()/predict())."""
    import torch

    if torch.cuda.is_available():
        torch.cuda.init()  # ensure a CUDA context exists before querying/resetting memory stats
        torch.cuda.synchronize()
        torch.cuda.reset_peak_memory_stats(torch.device(device))

    pr = PassResult()
    for sample in samples:
        image_path = RAW_IMAGE_DIR / sample.filename
        if not image_path.exists():
            pr.skipped.append({"sample_id": sample.sample_id, "reason": "image file missing"})
            continue
        t0 = time.perf_counter()
        raw_preds, _result = _predict_raw(model, image_path, conf, device)
        t1 = time.perf_counter()
        pr.inference_ms.append((t1 - t0) * 1000.0)
        pr.preprocess_ms.append(0.0)  # no preprocessing step in this experiment

        mapped = []
        for class_name, bbox, bconf in raw_preds:
            oiv7_name = map_prediction_class_to_oiv7(class_name, vocabulary)
            final_name = oiv7_name if oiv7_name is not None else f"{vocabulary}::{class_name}"
            mapped.append({"class_name": final_name, "bbox": list(bbox), "confidence": bconf})
        pr.predictions_by_sample[sample.sample_id] = mapped

    peak_mem = torch.cuda.max_memory_allocated(torch.device(device)) if torch.cuda.is_available() else 0
    return pr, peak_mem


def _detections_from_pass(pr: PassResult, class_filter: set | None = None) -> list:
    dets = []
    for sample_id, preds in pr.predictions_by_sample.items():
        for p in preds:
            if class_filter is not None and p["class_name"] not in class_filter:
                continue
            dets.append(Detection(sample_id=sample_id, class_name=p["class_name"], bbox=tuple(p["bbox"]), confidence=p["confidence"]))
    return dets


def _ground_truths(manifest: list, class_filter: set | None = None) -> list:
    gts = []
    for sample in manifest:
        for lbl in sample.labels:
            if class_filter is not None and lbl.class_name not in class_filter:
                continue
            gts.append(GroundTruth(sample_id=sample.sample_id, class_name=lbl.class_name, bbox=lbl.bbox))
    return gts


def _sweep_precision_recall(pass001: PassResult, ground_truths_common: list, ground_truths_person: list) -> dict:
    """Precision/recall at each swept confidence threshold, filtering the
    ONE conf=0.01 capture (no additional inference) — mirrors
    benchmark/diagnostics/threshold_sweep.py's established filter-don't-
    re-infer pattern."""
    all_dets = _detections_from_pass(pass001)
    points = []
    for t in SWEEP_THRESHOLDS:
        filtered = [d for d in all_dets if d.confidence >= t]
        hazard_overall, per_class, _ = evaluate_detections(
            filtered, ground_truths_common, sorted(COMMON_HAZARD_CLASSES_OIV7), map_ious=(0.5,)
        )
        person_dets = [d for d in filtered if d.class_name == PERSON_OIV7]
        person_overall, _pc, _m = evaluate_detections(person_dets, ground_truths_person, [PERSON_OIV7], map_ious=(0.5,))
        points.append({
            "threshold": t,
            "hazard_common": {"precision": hazard_overall.precision, "recall": hazard_overall.recall},
            "person": {"precision": person_overall.precision, "recall": person_overall.recall},
        })
    return {"points": points}


def _find_matched_recall(points: list, target_precision: float, precision_key: tuple, recall_key: tuple) -> dict:
    """Smallest swept threshold whose precision (dotted path precision_key)
    is >= target_precision; returns that threshold + the recall
    (recall_key) there. None if never reached across the whole sweep."""

    def _get(d, path):
        cur = d
        for p in path:
            cur = cur[p]
        return cur

    for pt in sorted(points, key=lambda p: p["threshold"]):
        if _get(pt, precision_key) >= target_precision:
            return {"threshold": pt["threshold"], "recall": _get(pt, recall_key), "precision_at_threshold": _get(pt, precision_key), "reached": True}
    return {"threshold": None, "recall": None, "precision_at_threshold": None, "reached": False}


def run_all() -> dict:
    import torch

    device = "cuda:0" if torch.cuda.is_available() else "cpu"

    if not FN_RECORDS_PATH.exists():
        raise RuntimeError(
            f"missing EXP-0003 FN classification: {FN_RECORDS_PATH} — EXP-0005's failure-bucket "
            "transition analysis depends on it (see person_confusion_analysis.py::main())."
        )
    fn_data = json.loads(FN_RECORDS_PATH.read_text(encoding="utf-8"))
    fn_records = fn_data["records"]

    manifest = load_manifest(EVAL_MANIFEST_PATH)
    assert_eval_only(manifest)
    manifest_by_id = {s.sample_id: s for s in manifest}

    ground_truths_common = _ground_truths(manifest, set(COMMON_HAZARD_CLASSES_OIV7))
    ground_truths_person = _ground_truths(manifest, {PERSON_OIV7})
    ground_truths_hazard8 = _ground_truths(manifest, set(HAZARD_CLASSES_OIV7))

    baseline_tp_keys = _baseline_tp_keys(manifest)

    baseline_metrics_ref = json.loads(BASELINE_METRICS_PATH.read_text(encoding="utf-8"))
    baseline_per_class_ref = json.loads(BASELINE_PER_CLASS_PATH.read_text(encoding="utf-8"))
    baseline_person_precision_04 = baseline_per_class_ref["Person"]["precision"]

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    per_candidate: dict = {}
    log_lines: list = []

    for name in CANDIDATE_ORDER:
        spec = CANDIDATE_SPECS[name]
        path = spec["path"]
        if not path.exists():
            raise RuntimeError(f"candidate {name!r}: model file not found at {path} — download it first.")
        meta = _model_metadata(path)
        model = meta["model"]
        vocabulary = meta["vocabulary"]

        t_start = time.perf_counter()
        pass04, peak_mem04 = run_pass(model, vocabulary, manifest, CONF_THRESHOLD, device)
        pass001, peak_mem001 = run_pass(model, vocabulary, manifest, LOW_CONF_PROBE, device)
        t_end = time.perf_counter()

        with open(OUT_DIR / f"{name}_conf0.4.jsonl", "w", encoding="utf-8") as f:
            for sid, preds in pass04.predictions_by_sample.items():
                f.write(json.dumps({"sample_id": sid, "predictions": preds}) + "\n")
        with open(OUT_DIR / f"{name}_conf0.01.jsonl", "w", encoding="utf-8") as f:
            for sid, preds in pass001.predictions_by_sample.items():
                f.write(json.dumps({"sample_id": sid, "predictions": preds}) + "\n")

        # ---- common-class (PRIMARY) metrics, conf=0.4 ----
        dets04_common = _detections_from_pass(pass04, set(COMMON_HAZARD_CLASSES_OIV7))
        hazard_common_overall, hazard_common_per_class, _ = evaluate_detections(
            dets04_common, ground_truths_common, sorted(COMMON_HAZARD_CLASSES_OIV7), map_ious=(0.5,)
        )
        person_common = hazard_common_per_class.get(PERSON_OIV7)

        # ---- native-vocabulary metrics (full hazard-8 for OIV7 candidates;
        # for a COCO candidate this is identical to the common-class result
        # restricted to its 7 mappable classes -- Stairs is structurally
        # absent, never fabricated). ----
        if vocabulary == "oiv7":
            dets04_native = _detections_from_pass(pass04, set(HAZARD_CLASSES_OIV7))
            hazard_native_overall, hazard_native_per_class, _ = evaluate_detections(
                dets04_native, ground_truths_hazard8, sorted(HAZARD_CLASSES_OIV7), map_ious=(0.5,)
            )
            native_note = "Full native hazard-8 (all 8 OmniSight hazard classes; same vocabulary as production)."
        else:
            hazard_native_overall = hazard_common_overall
            hazard_native_per_class = hazard_common_per_class
            native_note = (
                f"COCO vocabulary has no 'Stairs' class at all — native metrics here are the SAME "
                f"7-class common-class result (excludes: {list(EXCLUDED_CLASSES_NO_COCO_EQUIVALENT)}). "
                "This is a real structural vocabulary gap, not a mapping omission."
            )

        # ---- latency (inference only; no preprocessing step) ----
        inference_lat = _latency_stats(pass04.inference_ms)

        # ---- threshold sweep / precision-matched comparisons ----
        sweep = _sweep_precision_recall(pass001, ground_truths_common, ground_truths_person)
        precision_matched = _find_matched_recall(
            sweep["points"], baseline_person_precision_04, ("person", "precision"), ("person", "recall")
        )
        guardrail_matched = _find_matched_recall(
            sweep["points"], HAZARD_PRECISION_GUARDRAIL, ("hazard_common", "precision"), ("person", "recall")
        )

        # ---- CoreML export attempt (best-effort; execution requires macOS,
        # so this only tests whether the CONVERSION code path itself runs on
        # Windows -- a genuinely different code path than inference). ----
        coreml_result = {"attempted": False, "success": None, "error": None}
        if spec["attempt_coreml_export"]:
            coreml_result["attempted"] = True
            try:
                model.export(format="coreml", imgsz=IMGSZ, nms=False)
                coreml_result["success"] = True
            except Exception as e:  # noqa: BLE001 - deliberately broad; we report success/failure honestly either way
                coreml_result["success"] = False
                coreml_result["error"] = f"{type(e).__name__}: {e}"

        # ---- failure-bucket transition + small-Person analysis (reused) ----
        transitions = analyze_candidate_transitions(name, pass04, pass001, manifest_by_id, fn_records, baseline_tp_keys)

        per_candidate[name] = {
            "spec": {k: v for k, v in spec.items() if k not in ("path", "attempt_coreml_export")},
            "checkpoint": {
                "filename": path.name,
                "sha256": meta["sha256"],
                "size_bytes": meta["size_bytes"],
                "size_mb": round(meta["size_bytes"] / (1024 * 1024), 2),
                "n_params": meta["n_params"],
                "n_params_millions": round(meta["n_params"] / 1e6, 2),
                "vocabulary": vocabulary,
                "num_classes": meta["num_classes"],
                "class_map_verification": meta["class_verification"],
            },
            "hazard_common_class": {
                "precision": hazard_common_overall.precision, "recall": hazard_common_overall.recall,
                "f1": hazard_common_overall.f1, "map50": hazard_common_overall.map50,
                "tp": hazard_common_overall.tp, "fp": hazard_common_overall.fp, "fn": hazard_common_overall.fn,
                "num_gt": hazard_common_overall.num_gt,
                "classes_included": sorted(COMMON_HAZARD_CLASSES_OIV7),
                "classes_excluded": list(EXCLUDED_CLASSES_NO_COCO_EQUIVALENT) if vocabulary == "coco" else [],
            },
            "hazard_native": {
                "precision": hazard_native_overall.precision, "recall": hazard_native_overall.recall,
                "f1": hazard_native_overall.f1, "map50": hazard_native_overall.map50,
                "note": native_note,
            },
            "person": {
                "precision": person_common.precision, "recall": person_common.recall, "f1": person_common.f1,
                "ap50": person_common.ap50, "tp": person_common.tp, "fp": person_common.fp, "fn": person_common.fn,
                "num_gt": person_common.num_gt,
            },
            "latency_ms": {
                **inference_lat,
                "note": "Windows/CUDA relative compute proxy, NOT iPhone. Inference-only (no preprocessing step in this experiment).",
            },
            "peak_gpu_memory_bytes_conf0.4_pass": peak_mem04,
            "peak_gpu_memory_mb_conf0.4_pass": round(peak_mem04 / (1024 * 1024), 2),
            "threshold_sweep": sweep,
            "precision_matched_person_recall": {
                **precision_matched,
                "target_precision": baseline_person_precision_04,
                "definition": "Person recall at the lowest swept confidence threshold whose Person precision >= the baseline's official (conf=0.4) Person precision.",
            },
            "guardrail_matched_person_recall": {
                **guardrail_matched,
                "target_precision": HAZARD_PRECISION_GUARDRAIL,
                "definition": "Person recall at the lowest swept confidence threshold whose common-class hazard precision >= the hazard-precision guardrail floor (baseline-0.05).",
            },
            "coreml_export": coreml_result,
            "skipped_images": pass04.skipped,
            "n_images_evaluated": len(pass04.predictions_by_sample),
            "wall_clock_sec_both_passes": t_end - t_start,
            **transitions,
        }
        log_lines.append(
            f"[{name}] vocab={vocabulary} params={meta['n_params']/1e6:.2f}M size={meta['size_bytes']/1e6:.1f}MB | "
            f"hazard_common P={hazard_common_overall.precision:.4f} R={hazard_common_overall.recall:.4f} | "
            f"person P={person_common.precision:.4f} R={person_common.recall:.4f} F1={person_common.f1:.4f} AP50={person_common.ap50:.4f} | "
            f"inference p50={inference_lat['median_ms']:.2f}ms p95={inference_lat['p95_ms']:.2f}ms peak_gpu={peak_mem04/1e6:.1f}MB | "
            f"coreml_export={coreml_result}"
        )

        del model
        import gc

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    return {
        "candidates": per_candidate,
        "candidate_order": list(CANDIDATE_ORDER),
        "common_class_definition": {
            "classes": sorted(COMMON_HAZARD_CLASSES_OIV7),
            "excluded_no_coco_equivalent": list(EXCLUDED_CLASSES_NO_COCO_EQUIVALENT),
            "note": "Primary cross-model comparison basis whenever any candidate's vocabulary differs from the baseline's (COCO candidate C). For same-vocabulary candidates (B, D) this coincides with a hazard-7 subset of their native hazard-8 metrics (hazard_native carries the full 8-class figure for those).",
        },
        "baseline_reference": {
            "hazard_full8": baseline_metrics_ref["hazard_classes_only"],
            "person": baseline_per_class_ref["Person"],
            "latency_p95_ms": baseline_metrics_ref["latency_ms"]["p95"],
            "run_id": baseline_metrics_ref["run_id"],
        },
        "num_baseline_person_fn": len(fn_records),
        "num_baseline_person_tp": len(baseline_tp_keys),
        "hazard_precision_guardrail": HAZARD_PRECISION_GUARDRAIL,
        "log_lines": log_lines,
    }


def main() -> None:
    result = run_all()
    for line in result["log_lines"]:
        print(line)
    ANALYSIS_OUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Wrote {ANALYSIS_OUT_PATH}")


if __name__ == "__main__":
    main()
