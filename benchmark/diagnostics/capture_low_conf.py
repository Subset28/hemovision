"""Diagnostic-only: ONE low-threshold inference pass (conf=0.01, same imgsz=640
and iou=0.7 NMS as the baseline) over the full eval manifest, capturing every
candidate detection regardless of whether it would clear the app's real
conf=0.4 operating point.

This is the single expensive re-run other diagnostics (threshold_sweep.py,
pr_curves.py, person_failure_analysis.py) reuse by post-hoc filtering — per
the task spec, inference is NOT re-run once per threshold.

Uses BaselineModel.predict_at() (benchmark/model.py) — NOT predict() — so this
never touches or reproduces benchmark/results/baseline/ and never changes
benchmark/config.py's actual operating point.

Run with: uv run python -m benchmark.diagnostics.capture_low_conf
Writes benchmark/results/diagnostics/low_conf_predictions.jsonl
"""

from __future__ import annotations

import json
import time

from benchmark.config import EVAL_MANIFEST_PATH, IOU_THRESHOLD, RAW_IMAGE_DIR, REPO_ROOT
from benchmark.dataset import assert_eval_only, load_manifest
from benchmark.model import BaselineModel

LOW_CONF = 0.01
OUT_DIR = REPO_ROOT / "benchmark" / "results" / "diagnostics"
OUT_PATH = OUT_DIR / "low_conf_predictions.jsonl"


def main() -> None:
    samples = load_manifest(EVAL_MANIFEST_PATH)
    assert_eval_only(samples)
    print(f"Loaded {len(samples)} eval samples.")

    model = BaselineModel()
    print(f"Model loaded on device={model.device}. Capturing at conf={LOW_CONF}, iou={IOU_THRESHOLD} "
          "(diagnostic only — benchmark/config.py unchanged).")

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    t_start = time.perf_counter()
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        for i, sample in enumerate(samples):
            image_path = RAW_IMAGE_DIR / sample.filename
            if not image_path.exists():
                print(f"  WARNING: missing image for {sample.sample_id}, skipping")
                continue
            raw_preds = model.predict_at(image_path, conf=LOW_CONF, iou=IOU_THRESHOLD)
            rec = {
                "sample_id": sample.sample_id,
                "filename": sample.filename,
                "predictions": [
                    {"class_name": p.class_name, "bbox": list(p.bbox), "confidence": p.confidence}
                    for p in raw_preds
                ],
            }
            f.write(json.dumps(rec) + "\n")
            if (i + 1) % 50 == 0:
                print(f"  ...{i + 1}/{len(samples)} images")

    elapsed = time.perf_counter() - t_start
    print(f"Wrote {OUT_PATH} ({len(samples)} images, {elapsed:.1f}s total).")


if __name__ == "__main__":
    main()
