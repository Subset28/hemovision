"""Evaluation entrypoint: python -m benchmark.evaluate

Loads the baseline model at the app's exact operating point, runs inference
over the eval manifest (batch=1, matching real app usage), scores predictions
against ground truth, and writes:

  benchmark/results/baseline/metrics.json        - overall metrics + latency
  benchmark/results/baseline/predictions.jsonl   - raw per-image predictions
  benchmark/results/baseline/per_class.json      - per-class precision/recall/AP
  benchmark/results/baseline/failures.jsonl      - individual failure cases
  benchmark/results/baseline/run_metadata.json   - full reproducibility record

See benchmark/metrics.py module docstring for the important honesty caveat
about mAP being restricted to the conf=0.4 operating point, not a full sweep.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from benchmark.config import (
    BASELINE_RESULTS_DIR,
    BENCHMARK_VERSION,
    EVAL_MANIFEST_PATH,
    HAZARD_CLASS_MAP,
    MAP_5095_IOUS,
    RAW_IMAGE_DIR,
)
from benchmark.dataset import assert_eval_only, load_manifest
from benchmark.metrics import Detection, GroundTruth, evaluate_detections
from benchmark.model import BaselineModel
from benchmark.run_metadata import build_run_metadata, manifest_sha256

HAZARD_CLASSES_OIV7 = set(HAZARD_CLASS_MAP.values())


def _bbox_close(a: tuple, b: tuple, eps: float = 1e-6) -> bool:
    return len(a) == 4 and len(b) == 4 and all(abs(a[i] - b[i]) <= eps for i in range(4))


def _classify_failure(
    class_name: str,
    gt_labels_for_sample: list,
    n_boxes_in_image: int,
    is_hazard: bool,
    kind: str,  # "missed" | "false_positive" | "duplicate"
    gt_bbox: tuple | None = None,
) -> str:
    """Assign a taxonomy category (docs/FAILURE_TAXONOMY.md) from real signals
    available in a static-image benchmark only. Never invents temporal
    categories (unstable detection, tracking failure, etc.) — those are
    documented as structurally unmeasurable here.

    BUG FIX (found during Phase B validation pass, see reports/baseline/
    Baseline_Report.md addendum): for "missed" failures this used to match
    the ground-truth label ONLY by class_name, taking the FIRST same-class
    label found in the image's label list. For images with multiple
    ground-truth boxes of the same class (e.g. several Bicycles in one
    photo, common in Open Images), that could silently classify a missed
    box's failure reason (occlusion/small_object/clutter) using a
    DIFFERENT same-class box's is_occluded/size signals — e.g. box #3 (not
    occluded, not small) gets labeled "occlusion" because box #1 in the same
    image happens to be occluded. Passing gt_bbox lets this function find the
    EXACT missed box by (class_name, bbox) instead of just class_name.
    """
    if kind == "duplicate":
        return "duplicate_detection"
    if kind == "false_positive":
        return "false_positive"
    # kind == "missed": find the SPECIFIC missed box by class_name + bbox (not
    # just class_name — see bug-fix note above) and use ITS occlusion/size
    # signals, already computed at manifest-build time.
    target = None
    if gt_bbox is not None:
        for lbl in gt_labels_for_sample:
            if lbl.class_name == class_name and _bbox_close(lbl.bbox, gt_bbox):
                target = lbl
                break
    if target is None:
        # Fallback for callers that don't have the exact bbox available —
        # keeps this function usable in that degraded mode rather than
        # crashing, but this path re-introduces the ambiguity above when a
        # sample has multiple same-class boxes, so callers should always
        # pass gt_bbox when it's known (evaluate.py's real call sites do).
        for lbl in gt_labels_for_sample:
            if lbl.class_name == class_name:
                target = lbl
                break
    if target is None:
        return "missed_detection"
    area = target.bbox[2] * target.bbox[3]
    if target.is_occluded:
        return "occlusion"
    if area < 0.02:
        return "small_object"
    if n_boxes_in_image > 8:
        return "clutter"
    return "missed_detection"


def main() -> None:
    if not EVAL_MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"No manifest at {EVAL_MANIFEST_PATH}. Run `uv run python -m benchmark.build_dataset` first."
        )

    samples = load_manifest(EVAL_MANIFEST_PATH)
    assert_eval_only(samples)
    print(f"Loaded {len(samples)} eval samples from {EVAL_MANIFEST_PATH}")

    model = BaselineModel()
    print(f"Model loaded on device={model.device}")

    BASELINE_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    all_detections: list = []
    all_ground_truths: list = []
    latencies_ms: list = []
    predictions_records: list = []
    gt_by_sample: dict = {}
    class_names_seen: set = set()

    for i, sample in enumerate(samples):
        image_path = RAW_IMAGE_DIR / sample.filename
        if not image_path.exists():
            print(f"  WARNING: missing image file for {sample.sample_id}: {image_path}, skipping")
            continue

        t0 = time.perf_counter()
        raw_preds = model.predict(image_path)
        t1 = time.perf_counter()
        latency_ms = (t1 - t0) * 1000.0
        latencies_ms.append(latency_ms)

        gt_by_sample[sample.sample_id] = list(sample.labels)

        for lbl in sample.labels:
            all_ground_truths.append(
                GroundTruth(sample_id=sample.sample_id, class_name=lbl.class_name, bbox=lbl.bbox)
            )
            class_names_seen.add(lbl.class_name)

        pred_records_for_image = []
        for p in raw_preds:
            all_detections.append(
                Detection(
                    sample_id=sample.sample_id,
                    class_name=p.class_name,
                    bbox=p.bbox,
                    confidence=p.confidence,
                )
            )
            class_names_seen.add(p.class_name)
            pred_records_for_image.append(
                {"class_name": p.class_name, "bbox": list(p.bbox), "confidence": p.confidence}
            )

        predictions_records.append(
            {
                "sample_id": sample.sample_id,
                "filename": sample.filename,
                "latency_ms": latency_ms,
                "predictions": pred_records_for_image,
                "num_ground_truth": len(sample.labels),
            }
        )

        if (i + 1) % 50 == 0:
            print(f"  ...{i + 1}/{len(samples)} images")

    print(f"Ran inference on {len(predictions_records)} images.")

    overall, per_class, matches_at_fixed_iou = evaluate_detections(
        all_detections, all_ground_truths, sorted(class_names_seen), map_ious=MAP_5095_IOUS
    )

    hazard_overall, hazard_per_class, hazard_matches = evaluate_detections(
        all_detections, all_ground_truths, sorted(class_names_seen & HAZARD_CLASSES_OIV7),
        map_ious=MAP_5095_IOUS,
    )

    # ---- failures.jsonl ----------------------------------------------------
    failures: list = []
    model_version_hash = None  # filled from run_metadata below

    n_boxes_by_sample = {sid: len(lbls) for sid, lbls in gt_by_sample.items()}

    for cname, match in matches_at_fixed_iou.items():
        matched_gt_set = set(match.matched_gt_ids)
        # false negatives: gt boxes of this class never matched
        cls_gts = [g for g in all_ground_truths if g.class_name == cname]
        for gi, gt in enumerate(cls_gts):
            if (gt.sample_id, gi) not in matched_gt_set:
                is_hazard = cname in HAZARD_CLASSES_OIV7
                ftype = _classify_failure(
                    cname, gt_by_sample.get(gt.sample_id, []), n_boxes_by_sample.get(gt.sample_id, 0),
                    is_hazard, "missed", gt_bbox=gt.bbox,
                )
                failures.append(
                    {
                        "sample_id": gt.sample_id,
                        "ground_truth": {"class_name": cname, "bbox": list(gt.bbox)},
                        "prediction": None,
                        "confidence": None,
                        "failure_type": ftype,
                        "is_hazard_class": is_hazard,
                        "model_version": "yolov8m-oiv7",
                        "benchmark_version": BENCHMARK_VERSION,
                    }
                )

        # false positives (includes duplicate-box case: a lower-confidence
        # detection of the same class on an already-claimed GT box)
        cls_dets_sorted = sorted(
            [d for d in all_detections if d.class_name == cname], key=lambda d: d.confidence, reverse=True
        )
        for rank in match.unmatched_detection_indices:
            det = cls_dets_sorted[rank]
            is_hazard = cname in HAZARD_CLASSES_OIV7
            # duplicate detection heuristic: this class already has a TP match
            # somewhere in the same image (single-frame duplicate-box proxy) —
            # i.e. this FP is an extra box on an object already correctly found.
            is_duplicate = any(sid == det.sample_id for sid, _ in match.matched_gt_ids)
            ftype = _classify_failure(
                cname, gt_by_sample.get(det.sample_id, []), n_boxes_by_sample.get(det.sample_id, 0),
                is_hazard, "duplicate" if is_duplicate else "false_positive",
            )
            failures.append(
                {
                    "sample_id": det.sample_id,
                    "ground_truth": None,
                    "prediction": {"class_name": cname, "bbox": list(det.bbox)},
                    "confidence": det.confidence,
                    "failure_type": ftype,
                    "is_hazard_class": is_hazard,
                    "model_version": "yolov8m-oiv7",
                    "benchmark_version": BENCHMARK_VERSION,
                }
            )

    # ---- write outputs -------------------------------------------------------
    manifest_hash = manifest_sha256(EVAL_MANIFEST_PATH)
    run_meta = build_run_metadata(
        EVAL_MANIFEST_PATH,
        manifest_hash,
        extra={"num_eval_images": len(predictions_records), "num_images_in_manifest": len(samples)},
    )

    (BASELINE_RESULTS_DIR / "run_metadata.json").write_text(
        json.dumps(run_meta, indent=2), encoding="utf-8"
    )

    with open(BASELINE_RESULTS_DIR / "predictions.jsonl", "w", encoding="utf-8") as f:
        for rec in predictions_records:
            f.write(json.dumps(rec) + "\n")

    with open(BASELINE_RESULTS_DIR / "failures.jsonl", "w", encoding="utf-8") as f:
        for rec in failures:
            f.write(json.dumps(rec) + "\n")

    per_class_out = {
        cname: {
            "num_gt": m.num_gt,
            "num_predictions": m.num_predictions,
            "tp": m.tp,
            "fp": m.fp,
            "fn": m.fn,
            "precision": m.precision,
            "recall": m.recall,
            "f1": m.f1,
            "ap50": m.ap50,
            "ap50_95": m.ap50_95,
            "is_hazard_class": cname in HAZARD_CLASSES_OIV7,
        }
        for cname, m in per_class.items()
    }
    (BASELINE_RESULTS_DIR / "per_class.json").write_text(
        json.dumps(per_class_out, indent=2), encoding="utf-8"
    )

    latencies_sorted = sorted(latencies_ms)
    n = len(latencies_sorted)

    def _pct(p: float) -> float:
        if n == 0:
            return 0.0
        idx = min(n - 1, int(round(p * (n - 1))))
        return latencies_sorted[idx]

    metrics_out = {
        "run_id": run_meta["run_id"],
        "num_images_evaluated": len(predictions_records),
        "overall": {
            "precision": overall.precision,
            "recall": overall.recall,
            "f1": overall.f1,
            "map50": overall.map50,
            "map50_95": overall.map50_95,
            "tp": overall.tp,
            "fp": overall.fp,
            "fn": overall.fn,
            "num_gt": overall.num_gt,
            "num_predictions": overall.num_predictions,
        },
        "hazard_classes_only": {
            "precision": hazard_overall.precision,
            "recall": hazard_overall.recall,
            "f1": hazard_overall.f1,
            "map50": hazard_overall.map50,
            "map50_95": hazard_overall.map50_95,
            "tp": hazard_overall.tp,
            "fp": hazard_overall.fp,
            "fn": hazard_overall.fn,
            "num_gt": hazard_overall.num_gt,
            "num_predictions": hazard_overall.num_predictions,
            "miss_rate_proxy": 1.0 - hazard_overall.recall,
            "note": (
                "miss_rate_proxy = 1 - recall on hazard classes only, computed at the "
                "app's conf=0.4 operating point. This is a static-image proxy for the "
                "production 'miss rate' — it cannot capture cross-frame tracker "
                "recovery (coasting) which the real app has."
            ),
        },
        "false_detection_rate_proxy": {
            "fp_per_image": overall.fp / len(predictions_records) if predictions_records else 0.0,
            "note": (
                "Raw detector false positives per image at conf=0.4, BEFORE any "
                "SpeechEngine cooldown/priority/crowd-suppression logic. This is an "
                "explicit upper-bound proxy for 'false announcement rate', not the "
                "real number a user would hear — see docs/FAILURE_TAXONOMY.md."
            ),
        },
        "duplicate_box_rate_proxy": {
            "duplicate_detections": sum(1 for f in failures if f["failure_type"] == "duplicate_detection"),
            "note": (
                "Count of predicted boxes matching an already-claimed ground-truth "
                "box within the SAME single image (single-frame proxy). This is a "
                "different, weaker signal than the production 'duplicate announcement "
                "rate', which is a cross-frame tracker/TTS-cooldown phenomenon this "
                "static dataset structurally cannot measure."
            ),
        },
        "latency_ms": {
            "mean": sum(latencies_ms) / n if n else 0.0,
            "p50": _pct(0.5),
            "p95": _pct(0.95),
            "p99": _pct(0.99),
            "min": min(latencies_ms) if latencies_ms else 0.0,
            "max": max(latencies_ms) if latencies_ms else 0.0,
            "note": (
                "Measured on Windows/CUDA (RTX 3070 Ti), batch=1, single-process "
                "Python/PyTorch/ultralytics inference. This is a PROXY ONLY for "
                "real on-device Apple Neural Engine latency (computeUnits=.all on "
                "iPhone) — not equivalent. Real on-device numbers require the "
                "Mac/iPhone device benchmark described in BENCHMARK_PLAN.md Phase 2."
            ),
        },
        "not_measurable_with_this_benchmark": [
            "detection_stability (requires video/frame-sequence temporal continuity)",
            "tts_announcement_latency (requires the real SpeechEngine + device)",
            "lidar_spatial_usefulness (requires LiDAR-equipped device + real depth data)",
            "cross_frame_duplicate_announcement_rate (requires the SORT tracker + TTS cooldowns)",
        ],
    }
    (BASELINE_RESULTS_DIR / "metrics.json").write_text(
        json.dumps(metrics_out, indent=2), encoding="utf-8"
    )

    print(f"\nWrote results to {BASELINE_RESULTS_DIR}")
    print(f"Overall: P={overall.precision:.3f} R={overall.recall:.3f} F1={overall.f1:.3f} "
          f"mAP50={overall.map50:.3f} mAP50-95={overall.map50_95:.3f}")
    print(f"Hazard classes only: P={hazard_overall.precision:.3f} R={hazard_overall.recall:.3f} "
          f"miss_rate_proxy={1.0 - hazard_overall.recall:.3f}")
    print(f"Latency p50={metrics_out['latency_ms']['p50']:.1f}ms p95={metrics_out['latency_ms']['p95']:.1f}ms")
    print(f"Failures logged: {len(failures)}")


if __name__ == "__main__":
    main()
