"""Diagnostic-only confidence-threshold sweep + precision-recall curves.

Reuses the single low-confidence capture (benchmark/results/diagnostics/
low_conf_predictions.jsonl, conf=0.01, produced by capture_low_conf.py) and
computes precision/recall/F1 in pure Python at each of a fixed list of
thresholds by filtering that captured set — no additional model inference.

Also builds a full precision-recall curve per hazard class from the same
captured detections (confidence-descending cumulative match), independent of
the discrete threshold list.

NEVER writes to benchmark/results/baseline/ and NEVER changes
benchmark/config.py — this is diagnostic-only, per BENCHMARK_PLAN.md /
this task's step 3 instructions. The real baseline operating point
(conf=0.4, iou=0.7, imgsz=640) is unaffected.

Run with: uv run python -m benchmark.diagnostics.threshold_sweep
Writes:
  benchmark/results/diagnostics/threshold_sweep.json
  benchmark/results/diagnostics/pr_curves.json
"""

from __future__ import annotations

import json

from benchmark.config import EVAL_MANIFEST_PATH, HAZARD_CLASS_MAP, REPO_ROOT
from benchmark.dataset import load_manifest
from benchmark.metrics import (
    Detection,
    GroundTruth,
    evaluate_detections,
    greedy_match,
    precision_recall_from_match,
)

HAZARD_CLASSES = tuple(HAZARD_CLASS_MAP.values())

DIAG_DIR = REPO_ROOT / "benchmark" / "results" / "diagnostics"
LOW_CONF_PATH = DIAG_DIR / "low_conf_predictions.jsonl"
SWEEP_OUT_PATH = DIAG_DIR / "threshold_sweep.json"
PR_CURVE_OUT_PATH = DIAG_DIR / "pr_curves.json"

THRESHOLDS = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.60, 0.70, 0.80, 0.90]
MATCH_IOU = 0.5

HAZARD_GT_COUNTS = {
    "Person": 303,
    "Car": 148,
    "Bicycle": 78,
    "Dog": 52,
    "Motorcycle": 49,
    "Bus": 49,
    "Stairs": 45,
    "Truck": 42,
}


def load_low_conf_detections() -> list:
    dets = []
    with open(LOW_CONF_PATH, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            for p in rec["predictions"]:
                dets.append(
                    Detection(
                        sample_id=rec["sample_id"],
                        class_name=p["class_name"],
                        bbox=tuple(p["bbox"]),
                        confidence=p["confidence"],
                    )
                )
    return dets


def load_ground_truths() -> list:
    gts = []
    for sample in load_manifest(EVAL_MANIFEST_PATH):
        for lbl in sample.labels:
            gts.append(GroundTruth(sample_id=sample.sample_id, class_name=lbl.class_name, bbox=lbl.bbox))
    return gts


def sweep() -> dict:
    all_dets = load_low_conf_detections()
    all_gts = load_ground_truths()

    class_universe = sorted(set(HAZARD_CLASSES) | {d.class_name for d in all_dets if d.class_name in HAZARD_CLASSES})

    results = {"thresholds": {}, "note": (
        "Computed by filtering ONE low-threshold (conf=0.01) inference capture "
        "(benchmark/results/diagnostics/low_conf_predictions.jsonl) at each listed "
        "confidence cutoff, then running the same greedy IoU>=0.5 matching as the "
        "official baseline (benchmark/metrics.py). Diagnostic only — does not change "
        "benchmark/config.py's real operating point (conf=0.4). "
        "GT sample counts per hazard class (for statistical-confidence context): "
        + ", ".join(f"{k}={v}" for k, v in HAZARD_GT_COUNTS.items())
    )}

    for t in THRESHOLDS:
        filtered = [d for d in all_dets if d.confidence >= t]
        overall, per_class, _ = evaluate_detections(filtered, all_gts, class_universe, map_ious=(0.5,))
        results["thresholds"][str(t)] = {
            "hazard_overall": {
                "precision": overall.precision,
                "recall": overall.recall,
                "f1": overall.f1,
                "tp": overall.tp,
                "fp": overall.fp,
                "fn": overall.fn,
                "num_gt": overall.num_gt,
                "num_predictions": overall.num_predictions,
            },
            "per_class": {
                cname: {
                    "precision": m.precision,
                    "recall": m.recall,
                    "f1": m.f1,
                    "tp": m.tp,
                    "fp": m.fp,
                    "fn": m.fn,
                    "num_gt": m.num_gt,
                }
                for cname, m in per_class.items()
            },
        }

    # explicit summary of whether lowering the threshold fixes Person recall
    person_at_baseline = results["thresholds"][str(0.40)]["per_class"]["Person"]
    person_at_low = results["thresholds"][str(0.05)]["per_class"]["Person"]
    results["person_threshold_summary"] = {
        "recall_at_conf_0.40_baseline": person_at_baseline["recall"],
        "precision_at_conf_0.40_baseline": person_at_baseline["precision"],
        "recall_at_conf_0.05": person_at_low["recall"],
        "precision_at_conf_0.05": person_at_low["precision"],
        "verdict": (
            "See recall_at_conf_0.05 vs recall_at_conf_0.40_baseline and the matching "
            "precision figures — read together with reports/baseline/"
            "person_failure_analysis.md before concluding threshold alone explains the gap."
        ),
    }

    return results


def pr_curves() -> dict:
    """Full (not just 14-point) precision-recall curve per hazard class, built
    from the same low-conf capture via cumulative confidence-descending
    matching (benchmark/metrics.py precision_recall_from_match) — no extra
    inference."""
    all_dets = load_low_conf_detections()
    all_gts = load_ground_truths()

    curves = {}
    for cname in HAZARD_CLASSES:
        cls_dets = [d for d in all_dets if d.class_name == cname]
        cls_gts = [g for g in all_gts if g.class_name == cname]
        match = greedy_match(cls_dets, cls_gts, MATCH_IOU)
        precisions, recalls = precision_recall_from_match(match)
        curves[cname] = {
            "num_gt": HAZARD_GT_COUNTS.get(cname, len(cls_gts)),
            "points": [
                {"confidence": c, "precision": p, "recall": r}
                for c, p, r in zip(match.confidences, precisions, recalls)
            ],
        }
    return {
        "note": (
            "Full precision-recall curves per hazard class, built from ONE low-confidence "
            "(conf=0.01) capture via cumulative confidence-descending IoU>=0.5 matching "
            "(benchmark/metrics.py). Sample-size context: " +
            ", ".join(f"{k}={v} GT boxes" for k, v in HAZARD_GT_COUNTS.items()) +
            ". Classes with under ~50 GT boxes (Stairs, Motorcycle, Bus, Dog) should be "
            "read as low-confidence curves — a handful of boxes changes them a lot."
        ),
        "curves": curves,
    }


def main() -> None:
    if not LOW_CONF_PATH.exists():
        raise FileNotFoundError(
            f"{LOW_CONF_PATH} not found. Run `uv run python -m benchmark.diagnostics.capture_low_conf` first."
        )

    sweep_results = sweep()
    SWEEP_OUT_PATH.write_text(json.dumps(sweep_results, indent=2), encoding="utf-8")
    print(f"Wrote {SWEEP_OUT_PATH}")

    curve_results = pr_curves()
    PR_CURVE_OUT_PATH.write_text(json.dumps(curve_results, indent=2), encoding="utf-8")
    print(f"Wrote {PR_CURVE_OUT_PATH}")

    print("\nPerson recall/precision across thresholds:")
    for t in THRESHOLDS:
        pc = sweep_results["thresholds"][str(t)]["per_class"]["Person"]
        print(f"  conf>={t:.2f}: P={pc['precision']:.3f} R={pc['recall']:.3f} (tp={pc['tp']} fp={pc['fp']} fn={pc['fn']})")


if __name__ == "__main__":
    main()
