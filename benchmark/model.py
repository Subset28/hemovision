"""Thin wrapper around the shipped baseline model (yolov8m-oiv7.pt) via ultralytics,
run at the app's exact operating point (benchmark/config.py). Returns normalized
[x, y, w, h] predictions matching the manifest's ground-truth bbox convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from benchmark.config import CONF_THRESHOLD, IMGSZ, IOU_THRESHOLD, MODEL_PATH


@dataclass(frozen=True)
class RawPrediction:
    class_name: str
    bbox: tuple  # (x, y, w, h) normalized, top-left origin
    confidence: float


class BaselineModel:
    """Loads benchmark/models/yolov8m-oiv7.pt once; runs single-image inference
    at imgsz=640, conf=0.4, iou=0.7 (see benchmark/config.py for provenance).
    Batch size is always 1 — matches the app's real single-frame usage pattern
    per BENCHMARK_PLAN.md #13 (Windows-first, correctness over throughput)."""

    def __init__(self, model_path: Path = MODEL_PATH, device: str | None = None):
        from ultralytics import YOLO  # deferred import: heavy, torch-dependent

        if not model_path.exists():
            raise FileNotFoundError(
                f"Model not found at {model_path}. Expected the pre-downloaded "
                "yolov8m-oiv7.pt checkpoint (see BENCHMARK_PLAN.md / repo context)."
            )
        self.model_path = model_path
        self._model = YOLO(str(model_path))
        if device is None:
            import torch

            device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.device = device
        self.class_names: dict = self._model.names  # {index: name}

    def predict(self, image_path: Path) -> list:
        """Run inference on a single image at the app's real operating point
        (conf=0.4, iou=0.7 from benchmark/config.py), return normalized predictions.
        This is the ONLY method used to produce benchmark/results/baseline/ — the
        official baseline. Delegates to predict_at() with the config defaults."""
        return self.predict_at(image_path, conf=CONF_THRESHOLD, iou=IOU_THRESHOLD)

    def predict_at(self, image_path: Path, conf: float, iou: float | None = None) -> list:
        """Diagnostic-only: run inference at an arbitrary confidence/IoU, e.g. for
        the threshold-sweep / PR-curve / Person-failure low-confidence capture
        (benchmark/diagnostics/). NEVER used to produce benchmark/results/baseline/
        — that path always goes through predict(), which is pinned to
        benchmark/config.py's CONF_THRESHOLD/IOU_THRESHOLD. This method exists so
        diagnostic scripts don't duplicate the pixel->normalized-xywh conversion
        logic below (a second, drifting copy of that logic would itself be a bug
        risk of exactly the kind this benchmark's harness audits for)."""
        if iou is None:
            iou = IOU_THRESHOLD
        results = self._model.predict(
            source=str(image_path),
            imgsz=IMGSZ,
            conf=conf,
            iou=iou,
            device=self.device,
            verbose=False,
            batch=1,
        )
        result = results[0]
        preds: list = []
        if result.boxes is None or len(result.boxes) == 0:
            return preds

        img_h, img_w = result.orig_shape  # (H, W)
        for box in result.boxes:
            cls_idx = int(box.cls.item())
            class_name = self.class_names[cls_idx]
            conf = float(box.conf.item())
            x1, y1, x2, y2 = (v.item() for v in box.xyxy[0])
            x = x1 / img_w
            y = y1 / img_h
            w = (x2 - x1) / img_w
            h = (y2 - y1) / img_h
            preds.append(RawPrediction(class_name=class_name, bbox=(x, y, w, h), confidence=conf))
        return preds
