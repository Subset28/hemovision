"""The 7 experiment families (A-G), as an extensible registry.

Each family carries typical independent variables, typical guardrails, and a
default validation_requirement. This is descriptive metadata used to seed new
experiment proposals sensibly — it does not itself gate anything (the
evaluation_policy module and orchestrator's rejection checks do that).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FamilySpec:
    key: str
    label: str
    description: str
    typical_independent_variables: tuple
    typical_guardrails: tuple
    # Windows-side benchmark can evaluate this family without Mac/iPhone.
    windows_evaluatable: bool
    # What it takes to trust the result for actual production deployment —
    # may differ from windows_evaluatable (e.g. model_variant: Windows can
    # score accuracy/latency, but real CoreML/ANE behavior needs a Mac).
    production_validation_requirement: str  # OFFLINE_SIMULATABLE | REQUIRES_MAC | REQUIRES_IPHONE
    allowed_path_prefixes: tuple = field(default_factory=tuple)


REGISTRY: dict[str, FamilySpec] = {
    "threshold_postprocessing": FamilySpec(
        key="threshold_postprocessing",
        label="A. Threshold / Postprocessing",
        description=(
            "Confidence threshold, IoU/NMS threshold, or other postprocessing-only "
            "changes evaluated against the existing model weights."
        ),
        typical_independent_variables=("conf_threshold", "iou_threshold", "class-specific thresholds"),
        typical_guardrails=("hazard.precision", "hazard.recall", "latency.p95_ms"),
        windows_evaluatable=True,
        production_validation_requirement="OFFLINE_SIMULATABLE",
        allowed_path_prefixes=("benchmark/", "research/", "experiments/"),
    ),
    "class_confusion": FamilySpec(
        key="class_confusion",
        label="B. Class Confusion",
        description=(
            "Measurement-time class remapping/grouping to quantify how much recall "
            "loss is attributable to semantically related class confusion, without "
            "changing production label output."
        ),
        typical_independent_variables=("class grouping map", "scoring remap"),
        typical_guardrails=("hazard.precision", "hazard.recall"),
        windows_evaluatable=True,
        production_validation_requirement="OFFLINE_SIMULATABLE",
        allowed_path_prefixes=("benchmark/", "research/", "experiments/"),
    ),
    "small_object": FamilySpec(
        key="small_object",
        label="C. Small Object",
        description=(
            "Input resolution / tiling / crop strategies aimed at improving "
            "small/distant object recall at inference time."
        ),
        typical_independent_variables=("imgsz", "tiling strategy", "multi-scale inference"),
        typical_guardrails=("hazard.precision", "hazard.recall", "latency.p95_ms"),
        windows_evaluatable=True,
        production_validation_requirement="OFFLINE_SIMULATABLE",
        allowed_path_prefixes=("benchmark/", "research/", "experiments/"),
    ),
    "preprocessing": FamilySpec(
        key="preprocessing",
        label="D. Preprocessing",
        description=(
            "Single image preprocessing transform (contrast/CLAHE/sharpening/etc.) "
            "applied before inference. One transform at a time, never a stack."
        ),
        typical_independent_variables=("preprocessing transform",),
        typical_guardrails=("hazard.precision", "hazard.recall", "latency.p95_ms"),
        windows_evaluatable=True,
        production_validation_requirement="OFFLINE_SIMULATABLE",
        allowed_path_prefixes=("benchmark/", "research/", "experiments/"),
    ),
    "model_variant": FamilySpec(
        key="model_variant",
        label="E. Model Variant",
        description=(
            "A different model checkpoint/architecture (e.g. YOLO26n) evaluated "
            "on the Windows benchmark. Windows-side accuracy/latency numbers are "
            "evaluatable here, but real CoreML/ANE deployment behavior on-device "
            "is NOT — see production_validation_requirement."
        ),
        typical_independent_variables=("model checkpoint", "architecture"),
        typical_guardrails=("hazard.precision", "hazard.recall", "latency.p95_ms"),
        windows_evaluatable=True,
        production_validation_requirement="REQUIRES_MAC",
        allowed_path_prefixes=("benchmark/", "research/", "experiments/"),
    ),
    "training_data": FamilySpec(
        key="training_data",
        label="F. Training Data",
        description=(
            "Dataset composition/augmentation changes intended to affect a future "
            "fine-tuning effort. No fine-tuning is performed in Phase C; this family "
            "is evaluatable offline as dataset-analysis/simulation only."
        ),
        typical_independent_variables=("class balance", "augmentation policy", "eval slice"),
        typical_guardrails=("hazard.precision", "hazard.recall"),
        windows_evaluatable=True,
        production_validation_requirement="OFFLINE_SIMULATABLE",
        allowed_path_prefixes=("benchmark/", "data/", "research/", "experiments/"),
    ),
    "temporal_pipeline": FamilySpec(
        key="temporal_pipeline",
        label="G. Temporal Pipeline",
        description=(
            "Tracker (SORT) / temporal smoothing / cross-frame TTS-cooldown changes. "
            "Structurally requires video and the real on-device pipeline — a static-"
            "image Windows benchmark cannot exercise tracking or TTS at all."
        ),
        typical_independent_variables=("tracker IoU threshold", "coasting window", "TTS cooldown"),
        typical_guardrails=("tracking stability (device-measured)", "announcement latency (device-measured)"),
        windows_evaluatable=False,
        production_validation_requirement="REQUIRES_IPHONE",
        allowed_path_prefixes=("ios/", "research/", "experiments/"),
    ),
}


def get_family(key: str) -> FamilySpec:
    if key not in REGISTRY:
        raise KeyError(f"unknown experiment family: {key!r}. Known: {sorted(REGISTRY)}")
    return REGISTRY[key]


def default_validation_requirement(key: str) -> str:
    """Windows-evaluatability vs. production validation requirement,
    reported honestly rather than collapsed into one enum value that loses
    information — a caller wanting 'can I run this on Windows right now'
    should check `windows_evaluatable`, not this field."""
    return get_family(key).production_validation_requirement
