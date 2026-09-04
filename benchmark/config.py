"""Single source of truth for the benchmark's operating point and paths.

The values below MUST mirror the shipped production configuration exactly, since the
whole point of this benchmark is to evaluate what is actually running on-device — not
some hypothetical improved configuration. They are sourced from:

  - imgsz=640            -> CoreML pipeline input is 640x640 RGB (confirmed via
                             protobuf spec parsing of ScanningData.mlpackage).
  - conf=0.4              -> ios/OmniSightKit/Sources/OmniSightKit/OpticalCore.swift:137
                             `public var confidenceThreshold: Float = 0.4` on
                             `ScannerConfiguration` (the app's override of the model's
                             own embedded default of 0.25).
  - iou=0.7               -> the model's own embedded NMS default (app does not
                             override this at ios/OmniSightKit/.../OpticalCore.swift
                             or CoreMLDetector.swift; iouThreshold there is unrelated
                             — that's the SORT tracker's box-matching IoU, not NMS IoU).
  - hazard classes        -> ios/OmniSightKit/Sources/OmniSightKit/OpticalCore.swift:108-110
                             `public let hazardClasses: Set<String> = ["person", "car",
                             "truck", "bus", "bicycle", "motorcycle", "stairs", "dog"]`
                             (lowercase, as used in-app; OIV7 class names are
                             Titlecase — see HAZARD_CLASS_MAP below).

Do not hardcode these values anywhere else in the benchmark package — import from here.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Repo layout
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_DIR = REPO_ROOT / "benchmark"
MODEL_PATH = BENCHMARK_DIR / "models" / "yolov8m-oiv7.pt"

DATA_DIR = REPO_ROOT / "data"
RAW_IMAGE_DIR = DATA_DIR / "raw" / "eval"
MANIFEST_DIR = DATA_DIR / "manifests"
EVAL_MANIFEST_PATH = MANIFEST_DIR / "eval_manifest.jsonl"

RESULTS_DIR = BENCHMARK_DIR / "results"
BASELINE_RESULTS_DIR = RESULTS_DIR / "baseline"

# ---------------------------------------------------------------------------
# Model operating point (must match production exactly — see module docstring)
# ---------------------------------------------------------------------------

IMGSZ = 640
CONF_THRESHOLD = 0.4
IOU_THRESHOLD = 0.7

# ---------------------------------------------------------------------------
# mAP evaluation IoU thresholds (standard COCO-style sweep, independent of the
# above NMS iou — this is the IoU used to decide whether a *prediction* matches
# a *ground-truth box* for scoring purposes, not the model's own NMS).
# ---------------------------------------------------------------------------

MAP50_IOU = 0.5
MAP_5095_IOUS = tuple(round(0.5 + 0.05 * i, 2) for i in range(10))  # 0.50..0.95 step .05

# ---------------------------------------------------------------------------
# OmniSight hazard classes (lowercase, in-app naming) mapped to their exact
# Open Images V7 class names (Titlecase, as embedded in the .mlpackage / .pt
# metadata). All 8 map cleanly onto real OIV7 classes, including "Stairs"
# (confirmed present with 45 ground-truth boxes across 36 images in the
# actual eval build — see docs/DATASETS.md for exact achieved counts).
# ---------------------------------------------------------------------------

HAZARD_CLASS_MAP: dict[str, str] = {
    "person": "Person",
    "car": "Car",
    "truck": "Truck",
    "bus": "Bus",
    "bicycle": "Bicycle",
    "motorcycle": "Motorcycle",
    "stairs": "Stairs",
    "dog": "Dog",
}

HAZARD_CLASSES_OIV7 = tuple(HAZARD_CLASS_MAP.values())

# ---------------------------------------------------------------------------
# General (non-hazard) classes added for a broader precision/recall spread.
# Chosen as common indoor/outdoor objects likely to appear in OmniSight's
# real usage (rooms, hallways, kitchens, sidewalks, desks, stores).
# ---------------------------------------------------------------------------

GENERAL_CLASSES_OIV7 = (
    "Chair",
    "Table",
    "Couch",
    "Door",
    "Backpack",
    "Bottle",
    "Laptop",
    "Cabinetry",
    "Stairs",  # duplicate of hazard set, harmless if repeated
    "Traffic sign",
    "Bench",
    "Umbrella",
    "Handbag",
    "Trash can",
    "Houseplant",
    "Book",
    "Cat",
    "Bicycle wheel",
    "Window",
    "Wheelchair",
)

# Full class list requested from Open Images V7 for the eval subset build.
# ORDER MATTERS: build_dataset.py processes classes in this order and stops
# once TARGET_TOTAL_IMAGES is reached, so hazard classes are listed FIRST to
# guarantee they get explicitly queried (not just incidentally present in
# other images) before the budget is spent on general classes.
_seen = set()
ALL_TARGET_CLASSES_OIV7 = tuple(
    c for c in (*HAZARD_CLASSES_OIV7, *GENERAL_CLASSES_OIV7)
    if not (c in _seen or _seen.add(c))
)
del _seen

# ---------------------------------------------------------------------------
# Dataset build target (see docs/DATASETS.md for the exact rationale/how to
# expand later).
# ---------------------------------------------------------------------------

TARGET_TOTAL_IMAGES = 380
MAX_SAMPLES_PER_CLASS = 40
RANDOM_SEED = 42

# ---------------------------------------------------------------------------
# Benchmark/report versioning
# ---------------------------------------------------------------------------

BENCHMARK_VERSION = "0.1.0"
