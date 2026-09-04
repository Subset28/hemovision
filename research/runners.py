"""Per-experiment execution logic. Each runner takes an Experiment record and
the experiment's working directory (on the checked-out experiment branch) and
returns an ExperimentRunResult with baseline/candidate metrics, the
evaluation policy to judge them with, and a verdict_interpretation mapping
(most experiments want PASSED->PASSED; a CONFIRMATORY experiment like
EXP-0001, whose hypothesis is "X does NOT work", wants a hard evaluation-
policy FAILED to map to a confirmed-hypothesis PASSED — see module docstring
on EXP-0001 below for why).

Only EXP-0001 and EXP-0002 are implemented in Phase C, per the master spec's
explicit instruction to run 0001 and, optionally, 0002 — 0003/0004/0005 stay
QUEUED/BLOCKED for a future, separately-approved session.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from research.config import REPO_ROOT
from research.db import Experiment
from research.evaluation_policy import EvaluationPolicy, Verdict, default_hazard_policy


class RunnerError(RuntimeError):
    """Raised when an experiment's execution logic itself fails (benchmark
    subprocess error, missing input file, etc.) — this maps to REJECTED,
    since the pipeline never produced a fair, complete result to judge."""


@dataclass
class ExperimentRunResult:
    baseline_metrics: dict
    candidate_metrics: dict
    policy: EvaluationPolicy
    verdict_interpretation: dict  # evaluation_policy.Verdict.result -> final DB status
    notes: str
    result_run_id: str
    log_lines: list = field(default_factory=list)


def _threshold_sweep_path() -> Path:
    return REPO_ROOT / "benchmark" / "results" / "diagnostics" / "threshold_sweep.json"


def run_exp_0001(exp: Experiment, exp_dir: Path) -> ExperimentRunResult:
    """EXP-0001 (threshold_postprocessing, confirmatory/control).

    Hypothesis: "the existing threshold sweep accurately characterizes the
    precision/recall tradeoff and threshold alone cannot resolve Person
    recall without unacceptable precision loss."

    This experiment does NOT run new inference — it reuses
    benchmark/results/diagnostics/threshold_sweep.json (already-approved
    Phase B.5 diagnostic evidence) as its evidence base, per the experiment's
    own declared evaluation_method. "Candidate" here means "the same model,
    evaluated at conf=0.05 instead of conf=0.4" — a real, already-captured
    configuration, not a new one.

    Because the hypothesis is a NEGATIVE claim ("this does not work without
    an unacceptable cost"), a hard evaluation_policy FAILED verdict (the
    precision guardrail badly violated) is what CONFIRMS the hypothesis, and
    maps to a final PASSED status for this experiment. A clean PASSED
    evaluation-policy verdict (precision held, recall genuinely improved)
    would REFUTE the hypothesis and maps to FAILED.
    """
    sweep_path = _threshold_sweep_path()
    if not sweep_path.exists():
        raise RunnerError(f"missing evidence file: {sweep_path}")
    sweep = json.loads(sweep_path.read_text(encoding="utf-8"))

    try:
        baseline_bucket = sweep["thresholds"]["0.4"]
        candidate_bucket = sweep["thresholds"]["0.05"]
    except KeyError as e:
        raise RunnerError(f"threshold_sweep.json missing expected bucket: {e}") from e

    baseline_hazard = baseline_bucket["hazard_overall"]
    candidate_hazard = candidate_bucket["hazard_overall"]
    baseline_person = baseline_bucket["per_class"]["Person"]
    candidate_person = candidate_bucket["per_class"]["Person"]

    # Latency is not re-measured by this analysis-only experiment (no new
    # inference is run — filtering an existing capture at a lower confidence
    # does not change model wall-clock cost); reuse the canonical baseline's
    # measured p95 for both sides so the latency guardrail is a no-op here,
    # not a fabricated number.
    baseline_run_meta = json.loads(
        (REPO_ROOT / "benchmark" / "results" / "baseline" / "metrics.json").read_text(encoding="utf-8")
    )
    p95 = baseline_run_meta["latency_ms"]["p95"]

    baseline_metrics = {
        "hazard": {"precision": baseline_hazard["precision"], "recall": baseline_hazard["recall"]},
        "person": {
            "recall": baseline_person["recall"],
            "precision": baseline_person["precision"],
            "num_gt": baseline_person["num_gt"],
        },
        "latency": {"p95_ms": p95},
    }
    candidate_metrics = {
        "hazard": {"precision": candidate_hazard["precision"], "recall": candidate_hazard["recall"]},
        "person": {
            "recall": candidate_person["recall"],
            "precision": candidate_person["precision"],
            "num_gt": candidate_person["num_gt"],
        },
        "latency": {"p95_ms": p95},
    }

    policy = default_hazard_policy(baseline_hazard["precision"], baseline_hazard["recall"])

    notes = (
        "Confirmatory/control experiment. Evidence source: "
        f"{sweep_path.relative_to(REPO_ROOT)}. Compares the canonical baseline "
        "(conf=0.4) against the same model/weights/manifest evaluated at "
        "conf=0.05 (a real captured configuration, not a hypothetical). "
        "No new inference was run; no benchmark/config.py values were changed."
    )

    return ExperimentRunResult(
        baseline_metrics=baseline_metrics,
        candidate_metrics=candidate_metrics,
        policy=policy,
        verdict_interpretation={"PASSED": "FAILED", "FAILED": "PASSED", "INCONCLUSIVE": "INCONCLUSIVE"},
        notes=notes,
        result_run_id="RUN-20260904-002+threshold_sweep@conf=0.05",
        log_lines=[
            f"Loaded {sweep_path}",
            f"baseline (conf=0.4) hazard: {baseline_hazard}",
            f"candidate (conf=0.05) hazard: {candidate_hazard}",
            f"baseline (conf=0.4) person: {baseline_person}",
            f"candidate (conf=0.05) person: {candidate_person}",
        ],
    )


def run_exp_0002(exp: Experiment, exp_dir: Path) -> ExperimentRunResult:
    """EXP-0002 (small_object, resolution sweep).

    Hypothesis: does increased inference-time input resolution (640->960)
    improve Person recall, and at what latency cost? Runs REAL new inference
    over the eval manifest at imgsz=960 via benchmark.model.BaselineModel's
    existing predict_at() (imgsz is NOT parameterized there today — this
    runner calls ultralytics directly at imgsz=960, conf=0.4, iou=0.7,
    mirroring benchmark/model.py's exact conversion logic, since
    predict_at() only varies conf/iou, not imgsz, and Phase C must not modify
    benchmark/config.py's real operating point).
    """
    from benchmark.config import (
        CONF_THRESHOLD,
        EVAL_MANIFEST_PATH,
        HAZARD_CLASS_MAP,
        IOU_THRESHOLD,
        MODEL_PATH,
        RAW_IMAGE_DIR,
    )
    from benchmark.dataset import assert_eval_only, load_manifest
    from benchmark.metrics import Detection, GroundTruth, evaluate_detections
    from benchmark.model import BaselineModel

    CANDIDATE_IMGSZ = 960
    HAZARD_CLASSES_OIV7 = set(HAZARD_CLASS_MAP.values())

    if not EVAL_MANIFEST_PATH.exists():
        raise RunnerError(f"missing eval manifest: {EVAL_MANIFEST_PATH}")

    samples = load_manifest(EVAL_MANIFEST_PATH)
    assert_eval_only(samples)

    model = BaselineModel()

    all_detections: list = []
    all_ground_truths: list = []
    latencies_ms: list = []
    class_names_seen: set = set()
    log_lines = [f"Running EXP-0002 candidate inference at imgsz={CANDIDATE_IMGSZ}, "
                 f"conf={CONF_THRESHOLD}, iou={IOU_THRESHOLD} over {len(samples)} images"]

    for sample in samples:
        image_path = RAW_IMAGE_DIR / sample.filename
        if not image_path.exists():
            continue
        t0 = time.perf_counter()
        results = model._model.predict(
            source=str(image_path), imgsz=CANDIDATE_IMGSZ, conf=CONF_THRESHOLD,
            iou=IOU_THRESHOLD, device=model.device, verbose=False, batch=1,
        )
        t1 = time.perf_counter()
        latencies_ms.append((t1 - t0) * 1000.0)
        result = results[0]
        for lbl in sample.labels:
            all_ground_truths.append(GroundTruth(sample_id=sample.sample_id, class_name=lbl.class_name, bbox=lbl.bbox))
            class_names_seen.add(lbl.class_name)
        if result.boxes is not None and len(result.boxes) > 0:
            img_h, img_w = result.orig_shape
            for box in result.boxes:
                cls_idx = int(box.cls.item())
                class_name = model.class_names[cls_idx]
                conf = float(box.conf.item())
                x1, y1, x2, y2 = (v.item() for v in box.xyxy[0])
                bbox = (x1 / img_w, y1 / img_h, (x2 - x1) / img_w, (y2 - y1) / img_h)
                all_detections.append(Detection(sample_id=sample.sample_id, class_name=class_name, bbox=bbox, confidence=conf))
                class_names_seen.add(class_name)

    hazard_overall, hazard_per_class, _ = evaluate_detections(
        all_detections, all_ground_truths, sorted(class_names_seen & HAZARD_CLASSES_OIV7), map_ious=(0.5,)
    )
    person_m = hazard_per_class.get("Person")
    if person_m is None:
        raise RunnerError("no Person class in candidate evaluation output")

    latencies_sorted = sorted(latencies_ms)
    n = len(latencies_sorted)
    p95_candidate = latencies_sorted[min(n - 1, int(round(0.95 * (n - 1))))] if n else 0.0

    baseline_run_meta = json.loads(
        (REPO_ROOT / "benchmark" / "results" / "baseline" / "metrics.json").read_text(encoding="utf-8")
    )
    baseline_per_class = json.loads(
        (REPO_ROOT / "benchmark" / "results" / "baseline" / "per_class.json").read_text(encoding="utf-8")
    )
    baseline_person = baseline_per_class["Person"]

    baseline_metrics = {
        "hazard": {
            "precision": baseline_run_meta["hazard_classes_only"]["precision"],
            "recall": baseline_run_meta["hazard_classes_only"]["recall"],
        },
        "person": {"recall": baseline_person["recall"], "precision": baseline_person["precision"], "num_gt": baseline_person["num_gt"]},
        "latency": {"p95_ms": baseline_run_meta["latency_ms"]["p95"]},
    }
    candidate_metrics = {
        "hazard": {"precision": hazard_overall.precision, "recall": hazard_overall.recall},
        "person": {"recall": person_m.recall, "precision": person_m.precision, "num_gt": person_m.num_gt},
        "latency": {"p95_ms": p95_candidate},
    }

    log_lines.append(f"candidate (imgsz=960) hazard: P={hazard_overall.precision:.3f} R={hazard_overall.recall:.3f}")
    log_lines.append(f"candidate (imgsz=960) person: P={person_m.precision:.3f} R={person_m.recall:.3f}")
    log_lines.append(f"candidate p95 latency: {p95_candidate:.1f}ms")

    policy = default_hazard_policy(baseline_metrics["hazard"]["precision"], baseline_metrics["hazard"]["recall"])

    return ExperimentRunResult(
        baseline_metrics=baseline_metrics,
        candidate_metrics=candidate_metrics,
        policy=policy,
        verdict_interpretation={"PASSED": "PASSED", "FAILED": "FAILED", "INCONCLUSIVE": "INCONCLUSIVE"},
        notes=(
            f"Real inference re-run at imgsz={CANDIDATE_IMGSZ} (candidate) vs the canonical "
            "imgsz=640 baseline, same model weights/conf/iou/manifest. This is an inference-time-only "
            "resolution change — benchmark/config.py's real IMGSZ=640 is unchanged."
        ),
        result_run_id=f"EXP-0002-imgsz{CANDIDATE_IMGSZ}-inline",
        log_lines=log_lines,
    )


RUNNERS = {
    "EXP-0001": run_exp_0001,
    "EXP-0002": run_exp_0002,
}
