"""EXP-0005 (model_variant): verified vocabulary mapping between the
baseline's Open Images V7 (601-class) label space and a COCO-trained (80-
class) candidate's label space, for the hazard classes OmniSight actually
cares about (benchmark/config.py::HAZARD_CLASS_MAP).

HOW THIS WAS VERIFIED (not assumed from memory), same discipline as
benchmark/diagnostics/human_class_map.py: every class name below was checked
against a REAL model's `.names` dict before being added, via

    uv run python -c "from ultralytics import YOLO; \\
        m = YOLO('benchmark/models/yolo11m.pt'); print(sorted(m.names.values()))"
    uv run python -c "from ultralytics import YOLO; \\
        m = YOLO('benchmark/models/yolov8m-oiv7.pt'); \\
        print([v for v in m.names.values() if v in ('Person','Car','Truck','Bus','Bicycle','Motorcycle','Stairs','Dog')])"

Result (2026-09-04, recorded here so it is reproducible without re-running):
yolo11m.pt (and every other stock Ultralytics COCO checkpoint sharing the
standard 80-class COCO head, e.g. yolov8n/s/m/l/x.pt) has exactly 80 classes:
'person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck',
'boat', ... 'dog' (class 16), ... -- all lowercase, singular. There is NO
'stairs' class anywhere in COCO's 80-class vocabulary (COCO has no stairs
annotations at all -- this is a real, structural absence, not an omission in
this file). yolov8{n,m,l}-oiv7.pt (Open Images V7, 601 classes, Titlecase)
were independently confirmed to contain 'Person','Car','Truck','Bus',
'Bicycle','Motorcycle','Stairs','Dog' exactly as in benchmark/config.py's
HAZARD_CLASS_MAP.

CONSTRUCTION RULE: a COCO<->OIV7 pair is added to COMMON_CLASS_MAP only when
it is a clean, unambiguous 1:1 semantic equivalence (same real-world object
category, not a superset/subset relationship) -- mirrors the discipline in
human_class_map.py of not lumping in anything not directly verified. Person
is the class every candidate in this experiment MUST support (see
verify_person_comparable below); the other 6 mapped hazard classes are
included for the common-class hazard-8-minus-Stairs comparison.

Stairs is explicitly EXCLUDED from any COCO-involving common-class
comparison (fabricating a "closest COCO class" equivalence, e.g. mapping to
Stairs-adjacent classes that don't exist, would misrepresent a structural
vocabulary gap as a measured result) -- see EXCLUDED_CLASSES below and
research on this in experiments/*/EXP-0005/methodology.md.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# OIV7 (Titlecase) -> COCO (lowercase) 1:1 hazard-class equivalences.
# Verified present in a real yolo11m.pt / stock-COCO model.names (see
# docstring). Every key here is one of benchmark.config.HAZARD_CLASS_MAP's
# 8 OIV7 values.
# ---------------------------------------------------------------------------
OIV7_TO_COCO: dict[str, str] = {
    "Person": "person",
    "Car": "car",
    "Truck": "truck",
    "Bus": "bus",
    "Bicycle": "bicycle",
    "Motorcycle": "motorcycle",
    "Dog": "dog",
    # "Stairs": deliberately absent -- see EXCLUDED_CLASSES.
}

COCO_TO_OIV7: dict[str, str] = {v: k for k, v in OIV7_TO_COCO.items()}

# Classes in benchmark.config.HAZARD_CLASS_MAP that have NO COCO equivalent
# at all (structural vocabulary gap, not a mapping oversight). Any
# COCO-involving common-class comparison must exclude these, never fabricate
# a "closest" equivalent for them.
EXCLUDED_CLASSES_NO_COCO_EQUIVALENT: tuple[str, ...] = ("Stairs",)

# The common-class hazard set used as PRIMARY comparison whenever a candidate
# is COCO-trained: hazard-8 minus Stairs = 7 classes (OIV7 naming).
COMMON_HAZARD_CLASSES_OIV7: tuple[str, ...] = tuple(OIV7_TO_COCO.keys())

PERSON_OIV7 = "Person"
PERSON_COCO = "person"


def verify_coco_map_against_model(model_names: dict) -> dict:
    """Re-verify every COCO class name this module declares is actually
    present in a live COCO-trained model's .names dict (dict[int, str]).
    Returns {"missing": [...], "ok": bool, "num_declared": int}. Call this at
    analysis time, not just trust the module comments -- mirrors
    human_class_map.verify_against_model's discipline."""
    real_names = set(model_names.values())
    declared = set(OIV7_TO_COCO.values())
    missing = sorted(c for c in declared if c not in real_names)
    return {"missing": missing, "ok": len(missing) == 0, "num_declared": len(declared)}


def verify_oiv7_map_against_model(model_names: dict) -> dict:
    """Same check for an OIV7-vocabulary candidate: every hazard class in
    benchmark.config.HAZARD_CLASS_MAP (including Stairs) must be present."""
    real_names = set(model_names.values())
    from benchmark.config import HAZARD_CLASSES_OIV7

    declared = set(HAZARD_CLASSES_OIV7)
    missing = sorted(c for c in declared if c not in real_names)
    return {"missing": missing, "ok": len(missing) == 0, "num_declared": len(declared)}


def is_coco_vocabulary(model_names: dict) -> bool:
    """Heuristic-but-verifiable vocabulary detector: exactly 80 classes and
    'person' (lowercase) present, 'Person' (OIV7 Titlecase) absent. Used by
    the runner to decide which mapping/verification path a given candidate
    needs -- never assumed from the checkpoint filename alone."""
    names = set(model_names.values())
    return len(model_names) == 80 and "person" in names and "Person" not in names


def is_oiv7_vocabulary(model_names: dict) -> bool:
    return "Person" in set(model_names.values()) and len(model_names) >= 500


def detect_vocabulary(model_names: dict) -> str:
    """Returns 'oiv7', 'coco', or raises ValueError for an unrecognized
    vocabulary this module has no mapping for (fail loud rather than
    silently comparing incompatible label spaces)."""
    if is_oiv7_vocabulary(model_names):
        return "oiv7"
    if is_coco_vocabulary(model_names):
        return "coco"
    raise ValueError(
        f"unrecognized model vocabulary: {len(model_names)} classes, "
        f"'Person' present={('Person' in model_names.values())}, "
        f"'person' present={('person' in model_names.values())} -- "
        "model_variant_class_map.py has no verified mapping for this "
        "checkpoint's label space; add one (and verify it) before using it "
        "as an EXP-0005 candidate."
    )


def map_prediction_class_to_oiv7(class_name: str, vocabulary: str) -> str | None:
    """Map one raw predicted class name to its OIV7-space equivalent for
    hazard-relevant scoring. Returns None if the class has no mapped
    equivalent (e.g. any non-hazard COCO class, a COCO class this module
    doesn't map, or a non-hazard OIV7 class) -- callers should drop unmapped
    predictions from the evaluation rather than guessing.

    IMPORTANT: for an OIV7-vocabulary candidate this passes through the
    FULL hazard-8 set (benchmark.config.HAZARD_CLASSES_OIV7), including
    'Stairs' -- Stairs exists natively in OIV7 and must be preserved for
    each OIV7 candidate's own native hazard-8 metrics. COMMON_HAZARD_CLASSES_OIV7
    (7 classes, Stairs excluded) is a NARROWER set used only when actually
    building the cross-vocabulary common-class comparison (see
    model_variant_eval.py's separate common-class filtering step) -- it is
    deliberately NOT used here, or every OIV7 candidate's native hazard-8
    figure would silently lose Stairs."""
    from benchmark.config import HAZARD_CLASSES_OIV7

    if vocabulary == "oiv7":
        return class_name if class_name in HAZARD_CLASSES_OIV7 else None
    if vocabulary == "coco":
        return COCO_TO_OIV7.get(class_name)
    raise ValueError(f"unknown vocabulary: {vocabulary!r}")


def map_gt_class_to_common(class_name: str) -> str | None:
    """Ground truth is always native OIV7 (data/manifests/eval_manifest.jsonl).
    For the common-class comparison, only the 7 mapped hazard classes are
    kept (Stairs GT boxes are excluded from any COCO-involving comparison,
    consistent with map_prediction_class_to_oiv7)."""
    return class_name if class_name in COMMON_HAZARD_CLASSES_OIV7 else None
