"""Seeds the initial 5 experiment queue directly from the user's prescribed
hypotheses (Phase C spec #12) — NOT LLM-generated. Run once via:

    uv run python -m research.seed_experiments

Idempotent: skips any experiment_id that already exists in the DB.
"""

from __future__ import annotations

from research.config import CANONICAL_BASELINE_RUN_ID
from research.db import Experiment, OmniLabDB
from research.experiment_lifecycle import move_to_status
from research.experiment_schema import write_queued_artifacts
from research.prioritization import ScoreInputs, prioritize


def _experiments() -> list[Experiment]:
    return [
        Experiment(
            experiment_id="EXP-0001",
            hypothesis=(
                "The existing threshold sweep (benchmark/results/diagnostics/threshold_sweep.json) "
                "accurately characterizes the precision/recall tradeoff, and threshold alone cannot "
                "resolve Person recall without unacceptable precision loss."
            ),
            motivation=(
                "Phase B.5's diagnostic threshold sweep already showed Person recall roughly "
                "doubling (0.211->0.479) at conf=0.05 while precision collapses (0.667->0.312). "
                "This experiment formalizes that finding through the real omnilab pipeline as a "
                "confirmatory/control run — the safest possible first real experiment, since it "
                "requires no new inference code and no code changes at all."
            ),
            rationale=(
                "Confirms a large-sample (Person, GT=303), already-verified finding rather than "
                "discovering something new — deliberately low-risk per the master spec's "
                "instruction to prove the pipeline works before running anything more speculative."
            ),
            independent_variable="confidence_threshold (evaluated post-hoc from an existing conf=0.01 capture; benchmark/config.py's real conf=0.4 is unchanged)",
            controls={
                "model": "yolov8m-oiv7.pt (same weights as the canonical baseline)",
                "manifest": "data/manifests/eval_manifest.jsonl (unchanged)",
                "iou_threshold": 0.7,
                "imgsz": 640,
            },
            evaluation_method=(
                "Read benchmark/results/diagnostics/threshold_sweep.json's conf=0.4 (baseline) and "
                "conf=0.05 (candidate) buckets; apply research.evaluation_policy's default hazard "
                "policy. A hard evaluation-policy FAILED verdict (precision guardrail badly "
                "violated) CONFIRMS this experiment's hypothesis and maps to a final PASSED status."
            ),
            success_criteria={
                "hypothesis_confirmed_if": (
                    "candidate hazard.precision violates the (baseline-0.05) guardrail by more "
                    "than the noise margin, while person.recall improves by more than the "
                    "minimum-meaningful-delta"
                )
            },
            risks="None — read-only analysis of already-approved diagnostic data, no code change.",
            expected_outcome="Hypothesis confirmed (final status PASSED); no production recommendation changes.",
            experiment_family="threshold_postprocessing",
            baseline_run_id=CANONICAL_BASELINE_RUN_ID,
            execution_status="QUEUED",
            validation_requirement="OFFLINE_SIMULATABLE",
            estimated_cost={"runtime_min": 1, "gpu_mem_gb": 0, "cpu": "low", "disk_mb": 1, "llm_calls": 0},
        ),
        Experiment(
            experiment_id="EXP-0002",
            hypothesis=(
                "Increased inference-time input resolution (640->960 or 640->1280) meaningfully "
                "improves Person recall, at some measurable latency cost."
            ),
            motivation=(
                "64.0% of missed Person boxes have area <2% of the image (small/distant) per "
                "reports/baseline/person_failure_analysis.md. Higher input resolution is a "
                "natural, architecture-preserving lever for small-object recall."
            ),
            rationale=(
                "YOLO models natively support inference at a different imgsz via letterboxing, "
                "with no retraining and no change to the production model weights."
            ),
            independent_variable="imgsz (inference-time only: 640 -> 960)",
            controls={
                "model": "yolov8m-oiv7.pt (same weights)",
                "conf_threshold": 0.4,
                "iou_threshold": 0.7,
                "manifest": "data/manifests/eval_manifest.jsonl (unchanged)",
            },
            evaluation_method=(
                "Run real inference over the eval manifest at imgsz=960 (conf/iou unchanged), "
                "score with benchmark.metrics.evaluate_detections, compare against the canonical "
                "baseline via research.evaluation_policy's default hazard policy."
            ),
            success_criteria={
                "primary_metric": "person.recall",
                "min_meaningful_delta": 0.03,
                "guardrails": ["hazard.precision >= baseline-0.05", "latency.p95_ms <= baseline*1.5"],
            },
            risks="Runtime cost of a second full inference pass (~380 images); no production code touched.",
            expected_outcome="Directional evidence on whether resolution is a viable lever for Person recall.",
            experiment_family="small_object",
            baseline_run_id=CANONICAL_BASELINE_RUN_ID,
            execution_status="QUEUED",
            validation_requirement="OFFLINE_SIMULATABLE",
            estimated_cost={"runtime_min": 10, "gpu_mem_gb": 2, "cpu": "medium", "disk_mb": 5, "llm_calls": 0},
        ),
        Experiment(
            experiment_id="EXP-0003",
            hypothesis=(
                "A meaningful fraction of Person recall loss is attributable to predictions "
                "falling into semantically related classes (Man/Human body/Clothing/Woman) rather "
                "than true missed detections."
            ),
            motivation=(
                "35.1% of missed Person boxes had a DIFFERENT class predicted at the same location "
                "(IoU>=0.3) per reports/baseline/person_failure_analysis.md — this is a labeling "
                "choice, not a confidence problem, and is NOT fixable by lowering the threshold."
            ),
            rationale=(
                "Recomputing recall with a measurement-time class-grouping remap ({Person, Man, "
                "Woman} scored as one super-class) quantifies how much 'true' person-detection "
                "capability is understated by strict single-label scoring, without changing any "
                "production label output."
            ),
            independent_variable="scoring-time class grouping map (measurement only, not a production change)",
            controls={
                "model": "yolov8m-oiv7.pt (same weights, same predictions)",
                "conf_threshold": 0.4,
                "iou_threshold": 0.7,
                "manifest": "data/manifests/eval_manifest.jsonl (unchanged)",
            },
            evaluation_method=(
                "Re-score the EXISTING baseline predictions.jsonl with a {Person,Man,Woman} "
                "super-class remap applied only at scoring time; compare recomputed recall against "
                "the strict-label baseline recall."
            ),
            success_criteria={
                "primary_metric": "person_superclass.recall",
                "min_meaningful_delta": 0.05,
            },
            risks="None — measurement-only, does not change any production label or threshold.",
            expected_outcome="Quantifies the 'understated capability' gap; does not itself justify a production change.",
            experiment_family="class_confusion",
            baseline_run_id=CANONICAL_BASELINE_RUN_ID,
            execution_status="QUEUED",
            validation_requirement="OFFLINE_SIMULATABLE",
            estimated_cost={"runtime_min": 2, "gpu_mem_gb": 0, "cpu": "low", "disk_mb": 1, "llm_calls": 0},
        ),
        Experiment(
            experiment_id="EXP-0004",
            hypothesis=(
                "A single, simple image preprocessing transform (contrast/sharpening/CLAHE) "
                "applied before inference improves difficult Person detection without "
                "unacceptable latency cost."
            ),
            motivation=(
                "Occlusion/small-object/clutter dominate Person misses; a contrast/sharpening "
                "transform is a plausible, cheap lever worth testing in isolation before "
                "considering any model-level change."
            ),
            rationale=(
                "Exactly ONE transform is applied (not a stack), per the master spec's explicit "
                "instruction not to change multiple uncontrolled variables at once."
            ),
            independent_variable="one preprocessing transform (e.g. CLAHE) applied before inference",
            controls={
                "model": "yolov8m-oiv7.pt (same weights)",
                "conf_threshold": 0.4,
                "iou_threshold": 0.7,
                "imgsz": 640,
                "manifest": "data/manifests/eval_manifest.jsonl (unchanged)",
            },
            evaluation_method=(
                "Run real inference over the eval manifest with the transform applied to each "
                "image before the model call; compare against the canonical baseline via "
                "research.evaluation_policy's default hazard policy."
            ),
            success_criteria={
                "primary_metric": "person.recall",
                "min_meaningful_delta": 0.03,
                "guardrails": ["hazard.precision >= baseline-0.05", "latency.p95_ms <= baseline*1.5"],
            },
            risks="Runtime cost of a second full inference pass; no production code touched.",
            expected_outcome="Directional evidence on whether preprocessing is a viable lever.",
            experiment_family="preprocessing",
            baseline_run_id=CANONICAL_BASELINE_RUN_ID,
            execution_status="QUEUED",
            validation_requirement="OFFLINE_SIMULATABLE",
            estimated_cost={"runtime_min": 10, "gpu_mem_gb": 2, "cpu": "medium", "disk_mb": 5, "llm_calls": 0},
        ),
        Experiment(
            experiment_id="EXP-0005",
            hypothesis=(
                "A different model checkpoint/architecture (e.g. YOLO26n, referenced but never "
                "actually shipped per OMNISIGHT_ARCHITECTURE.md section 3) would improve Person "
                "and/or Stairs recall over the current yolov8m-oiv7 baseline."
            ),
            motivation=(
                "Recent commit history references a YOLO26n swap plan that was never executed. "
                "This is the most expensive, highest-risk experiment family (model_variant) and "
                "must only be pursued once cheaper levers are exhausted."
            ),
            rationale=(
                "Per the master spec's explicit ordering: only unblock this if EXP-0002 "
                "(resolution), EXP-0003 (class confusion), and EXP-0004 (preprocessing) indicate "
                "model capacity/architecture — not thresholding/measurement/preprocessing — is the "
                "limiting factor."
            ),
            independent_variable="model checkpoint/architecture",
            controls={"conf_threshold": 0.4, "iou_threshold": 0.7, "imgsz": 640},
            evaluation_method="(not designed yet — BLOCKED pending 0002/0003/0004 results)",
            success_criteria={},
            risks=(
                "Highest risk/cost family: requires acquiring/exporting a new model, and real "
                "CoreML/ANE deployment behavior cannot be validated without a Mac (see "
                "research/experiment_registry.py's production_validation_requirement=REQUIRES_MAC)."
            ),
            expected_outcome="(not applicable while BLOCKED)",
            experiment_family="model_variant",
            baseline_run_id=CANONICAL_BASELINE_RUN_ID,
            execution_status="QUEUED",  # created QUEUED then immediately transitioned to BLOCKED below
            validation_requirement="REQUIRES_MAC",
            estimated_cost={"runtime_min": 60, "gpu_mem_gb": 8, "cpu": "high", "disk_mb": 200, "llm_calls": 0},
        ),
    ]


def _priority_scores() -> dict:
    inputs = [
        ScoreInputs("EXP-0001", expected_impact=2, evidence_strength=5, feasibility=5, experiment_cost=1,
                    rationale="Confirmatory only; near-zero cost, reuses existing evidence"),
        ScoreInputs("EXP-0002", expected_impact=5, evidence_strength=4, feasibility=3, experiment_cost=3,
                    rationale="Could meaningfully move Person recall; requires a new inference run"),
        ScoreInputs("EXP-0003", expected_impact=4, evidence_strength=5, feasibility=5, experiment_cost=1,
                    rationale="Directly grounded in the 35.1% classification-confusion finding; measurement-only, near-zero cost"),
        ScoreInputs("EXP-0004", expected_impact=3, evidence_strength=3, feasibility=3, experiment_cost=3,
                    rationale="Plausible but less directly evidenced than 0002/0003; requires a new inference run"),
    ]
    scored = prioritize(inputs)
    return {s.experiment_id: s.score for s in scored}, scored


def main() -> None:
    scores, scored_list = _priority_scores()
    print("Priority order (score = impact*evidence*feasibility/cost):")
    for s in scored_list:
        print(f"  {s.experiment_id}: {s.score:.1f}  ({s.inputs.rationale})")
    print("  EXP-0005: BLOCKED (not scored — excluded from ordering per spec)")

    with OmniLabDB() as db:
        existing_ids = {e.experiment_id for e in db.list_experiments()}
        for exp in _experiments():
            if exp.experiment_id in existing_ids:
                print(f"skipping {exp.experiment_id} — already seeded")
                continue
            db.create_experiment(exp)
            write_queued_artifacts(exp, __import__("research.config", fromlist=["EXPERIMENTS_DIR"]).EXPERIMENTS_DIR / "queued" / exp.experiment_id)
            move_to_status(exp.experiment_id, "QUEUED")
            print(f"seeded {exp.experiment_id} [{exp.experiment_family}] status=QUEUED")

        if "EXP-0005" in existing_ids:
            pass
        else:
            db.transition_status("EXP-0005", "BLOCKED", note="Per spec: unblock only if 0002/0003/0004 indicate model capacity/architecture is the limiting factor.")
            move_to_status("EXP-0005", "BLOCKED")
            print("EXP-0005 transitioned QUEUED -> BLOCKED")


if __name__ == "__main__":
    main()
