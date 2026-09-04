"""Diagnostic (read-only w.r.t. the baseline): loads real predictions
(benchmark/results/baseline/predictions.jsonl) and ground truth
(data/manifests/eval_manifest.jsonl) for a spread of sample images across
multiple classes, and for each ground-truth box prints the best-matching
prediction (any class, at the app's real conf=0.4 operating point already
baked into predictions.jsonl) with its IoU, so a human can eyeball whether
class strings and coordinate conventions actually line up.

Run with: uv run python -m benchmark.diagnostics.label_alignment_check

Writes benchmark/diagnostics/label_alignment_examples.txt.

This is validation tooling only — it does not change benchmark/config.py,
does not re-run the model, and does not alter the baseline results it reads.
"""

from __future__ import annotations

import json

from benchmark.config import BASELINE_RESULTS_DIR, EVAL_MANIFEST_PATH, REPO_ROOT
from benchmark.metrics import iou_xywh

OUTPUT_PATH = REPO_ROOT / "benchmark" / "diagnostics" / "label_alignment_examples.txt"

# Spread across at least 5 classes, explicitly including Person and Stairs.
# "count" is how many GT boxes of that class to sample (in manifest order).
TARGET_CLASSES = {
    "Person": 5,
    "Stairs": 5,
    "Dog": 3,
    "Car": 3,
    "Bicycle": 2,
    "Motorcycle": 2,
}


def load_manifest_by_id() -> dict:
    manifest = {}
    with open(EVAL_MANIFEST_PATH, "r", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            manifest[d["sample_id"]] = d
    return manifest


def load_predictions_by_id() -> dict:
    preds = {}
    with open(BASELINE_RESULTS_DIR / "predictions.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            preds[d["sample_id"]] = d["predictions"]
    return preds


def main() -> None:
    manifest = load_manifest_by_id()
    predictions = load_predictions_by_id()

    lines: list[str] = []
    lines.append("# Label alignment spot-check")
    lines.append(
        "# Format: sample_id | GT: <class> bbox=[x,y,w,h] | Pred: <class> conf=.. IoU=.. [MATCH|NO MATCH]"
    )
    lines.append(
        "# MATCH = same class name AND IoU >= 0.5 against the single best-overlapping "
        "prediction of ANY class in that image (not necessarily the same class as GT — "
        "shown deliberately so class-mismatch bugs would be visible)."
    )
    lines.append("")

    total_checked = 0
    total_match = 0

    for cname, want_n in TARGET_CLASSES.items():
        found = 0
        for sample_id, sample in manifest.items():
            if found >= want_n:
                break
            gt_boxes = [l for l in sample["labels"] if l["class_name"] == cname]
            if not gt_boxes:
                continue
            preds_for_image = predictions.get(sample_id, [])
            for gt in gt_boxes:
                if found >= want_n:
                    break
                best_pred = None
                best_iou = 0.0
                for p in preds_for_image:
                    iou = iou_xywh(gt["bbox"], p["bbox"])
                    if iou > best_iou:
                        best_iou = iou
                        best_pred = p
                total_checked += 1
                if best_pred is None:
                    lines.append(
                        f"{sample_id} | GT: {cname} bbox={[round(v, 4) for v in gt['bbox']]} "
                        f"| Pred: NONE in image | [NO MATCH — no predictions at all]"
                    )
                else:
                    is_match = best_pred["class_name"] == cname and best_iou >= 0.5
                    if is_match:
                        total_match += 1
                    tag = "MATCH" if is_match else "NO MATCH"
                    nearest = (
                        f"nearest pred: {best_pred['class_name']} "
                        f"conf={best_pred['confidence']:.2f} IoU={best_iou:.2f}"
                    )
                    lines.append(
                        f"{sample_id} | GT: {cname} bbox={[round(v, 4) for v in gt['bbox']]} "
                        f"| Pred: {best_pred['class_name']} conf={best_pred['confidence']:.2f} "
                        f"IoU={best_iou:.2f} [{tag}"
                        + ("]" if is_match else f" — {nearest}]")
                    )
                found += 1

    lines.append("")
    lines.append(f"# Summary: {total_match}/{total_checked} sampled GT boxes had a same-class, IoU>=0.5 match.")
    lines.append(
        "# Purpose of this script: confirm class-name strings and bbox coordinate "
        "convention agree between benchmark/model.py predictions and data/manifests/ "
        "eval_manifest.jsonl ground truth. It is NOT a recall estimate (it samples a "
        "small, non-random subset of GT boxes) — see reports/baseline/Baseline_Report.md "
        "and benchmark/results/baseline/per_class.json for the real per-class recall."
    )

    OUTPUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {len(lines)} lines to {OUTPUT_PATH}")
    print(f"Summary: {total_match}/{total_checked} sampled GT boxes matched.")


if __name__ == "__main__":
    main()
