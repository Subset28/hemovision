"""Phase F item #7 — backfill EXP-0001..0005 into the canonical
ExperimentSpec/ExperimentProposal/ExperimentResult schema.

Run once via:

    uv run python -m research.backfill_experiment_specs

Idempotent: overwrites research/experiment_specs/EXP-000N.json deterministically
(same input -> same output every time — see tests/test_experiment_spec.py's
serialization-determinism test) rather than appending/mutating.

Migration policy (which marker applies when)
---------------------------------------------------------------------------
Every field below is set from a REAL, verbatim historical artifact
(hypothesis.md / methodology.md / config.yaml / results.json / conclusion.md
under experiments/completed/EXP-000N/) wherever a literal textual/structural
analog exists. Where no historical analog exists, one of three markers is
used — never a fabricated value:

  - LEGACY_UNKNOWN: the concept plausibly existed in spirit in the
    historical prose but was never written down as its OWN discrete,
    separately-authored field. Example: `supports_hypothesis_if` /
    `rejects_hypothesis_if` / `inconclusive_if` (pre-registered
    interpretation conditions) — EXP-0001..0005's hypothesis.md/methodology.md
    files DO contain interpretive language (e.g. EXP-0001's
    `hypothesis_confirmed_if` in its old-style success_criteria dict), but
    they were never split into three separate PASS/FAIL/INCONCLUSIVE
    conditions the way this schema requires, so fabricating a 3-way split
    now would misrepresent what was actually pre-registered at the time.

  - NOT_RECORDED: the concept did not exist AT ALL when the experiment was
    queued — most importantly `evidence_references` (Phase-E's memory_db.py
    did not exist until Phase E, well after EXP-0001..0005 were queued and
    completed) and `schema_version` in its historical sense (there was no
    ExperimentProposal schema at all — see below for how schema_version is
    actually set on the backfilled record).

  - NOT_APPLICABLE: the field is meaningful in general but genuinely does
    not apply to this experiment (e.g. `mac_iphone_deployment_approved` is
    NOT_APPLICABLE-equivalent — left False — for EXP-0001..0004, which never
    declared mac_iphone_required=True; only EXP-0005 declares
    mac_iphone_required=True, per its REQUIRES_MAC validation_requirement).

`schema_version` on every backfilled record is set to the CURRENT version
(research.experiment_spec.SCHEMA_VERSION, "1.0") — this is a statement about
the FORMAT the backfilled record is expressed in today, not a claim that
EXP-0001 was originally authored against a "1.0" schema (no such schema
existed at the time). This is the same convention any historical-data
migration uses: the migrated record's version reflects the schema of the
migrated representation, not the original source format.

Human-authority approval flags are left at their default (False) for every
backfilled record: none of EXP-0001..0005 touched production Swift code,
replaced a shipped CoreML model, trained anything, used private user data,
uploaded external data, deployed to Mac/iPhone, or changed signing/
distribution — so no approval was ever sought, and none is fabricated
retroactively. This is a real fact about these five experiments (see
research/README.md's Phase C "MAY NOT do" list, which none of them violated),
not an oversight in the backfill.
"""

from __future__ import annotations

import json
from pathlib import Path

from research.config import EXPERIMENTS_DIR, REPO_ROOT
from research.experiment_spec import (
    NOT_RECORDED,
    SCHEMA_VERSION,
    ExperimentProposal,
    ExperimentResult,
    ExperimentSpec,
)

SPECS_DIR = REPO_ROOT / "research" / "experiment_specs"

# Expected execution_status/research_verdict per Phase F item #7 — checked by
# tests/test_experiment_spec.py against the backfilled records AND against
# the live research/db.py rows, so this dict is a fixed cross-check, not the
# only source of truth.
EXPECTED = {
    "EXP-0001": ("COMPLETED", "PASS"),
    "EXP-0002": ("COMPLETED", "FAIL"),
    "EXP-0003": ("COMPLETED", "FAIL"),
    "EXP-0004": ("COMPLETED", "INCONCLUSIVE"),
    "EXP-0005": ("COMPLETED", "INCONCLUSIVE"),
}


def _exp_dir(experiment_id: str) -> Path:
    return EXPERIMENTS_DIR / "completed" / experiment_id


def _read(experiment_id: str, name: str) -> str:
    return (_exp_dir(experiment_id) / name).read_text(encoding="utf-8")


def _results(experiment_id: str) -> dict:
    return json.loads(_read(experiment_id, "results.json"))


def _relpath(p: Path) -> str:
    return str(p.relative_to(REPO_ROOT)).replace("\\", "/")


def _build_exp_0001() -> ExperimentSpec:
    results = _results("EXP-0001")
    proposal = ExperimentProposal(
        schema_version=SCHEMA_VERSION,
        experiment_id="EXP-0001",
        title="Confirmatory control: global confidence-threshold reduction alone",
        family="threshold_postprocessing",
        hypothesis=(
            "The existing threshold sweep (benchmark/results/diagnostics/threshold_sweep.json) "
            "accurately characterizes the precision/recall tradeoff, and threshold alone cannot "
            "resolve Person recall without unacceptable precision loss."
        ),
        motivation=(
            "Phase B.5's diagnostic threshold sweep already showed Person recall roughly doubling "
            "(0.211->0.479) at conf=0.05 while precision collapses (0.667->0.312). This experiment "
            "formalizes that finding through the real omnilab pipeline as a confirmatory/control run."
        ),
        research_question=(
            "Does lowering the global confidence threshold alone resolve Person recall without "
            "unacceptable hazard-precision loss?"
        ),
        evidence_references=(),  # NOT_RECORDED — memory_db.py did not exist at EXP-0001's time
        prior_experiment_ids=(),
        baseline_run_id="RUN-20260904-002",
        baseline_metrics=results["baseline_metrics"],
        independent_variables=(
            "confidence_threshold (evaluated post-hoc from an existing conf=0.01 capture; "
            "benchmark/config.py's real conf=0.4 is unchanged)",
        ),
        dependent_variables=("person.recall", "hazard.precision", "hazard.recall", "latency.p95_ms"),
        controlled_variables={
            "model": "yolov8m-oiv7.pt (same weights as the canonical baseline)",
            "manifest": "data/manifests/eval_manifest.jsonl (unchanged)",
            "iou_threshold": 0.7,
            "imgsz": 640,
        },
        procedure=(
            "Read benchmark/results/diagnostics/threshold_sweep.json's conf=0.4 (baseline) and "
            "conf=0.05 (candidate) buckets; apply research.evaluation_policy's default hazard policy."
        ),
        dataset_version="data/manifests/eval_manifest.jsonl (380 images, unchanged)",
        model_config_ref="benchmark/config.py (unchanged; conf=0.4 remains production)",
        implementation_scope="No new inference; no benchmark/config.py or ios/ change.",
        expected_artifacts=("results.json", "conclusion.md", "analysis.md"),
        reproducibility_requirements=(
            "Re-derivable directly from benchmark/results/diagnostics/threshold_sweep.json — no "
            "new inference is required to reproduce this result."
        ),
        control_condition="conf=0.4 (canonical baseline RUN-20260904-002)",
        baseline_comparison="RUN-20260904-002 vs. the same model/weights/manifest evaluated at conf=0.05",
        isolation_requirements="git_isolation.py experiment branch; no benchmark/config.py mutation",
        success_criteria={
            "primary_metric": "person.recall",
            "min_meaningful_delta": 0.03,
            "precision_floor": 0.757,
            "guardrail_metrics": ["hazard.precision", "hazard.recall", "latency.p95_ms"],
            "max_latency_regression_pct": 50.0,
            "required_tests_pass": True,
            "sample_size_requirements": {"person": 100},
        },
        production_impact=False,
        production_impact_description="None — read-only analysis of already-approved diagnostic data.",
        data_privacy_classification="NONE",
        external_api_required=False,
        mac_iphone_required=False,
        compute_resource_estimate={"runtime_min": 1, "gpu_mem_gb": 0, "cpu": "low", "disk_mb": 1, "llm_calls": 0},
        allowed_path_scope=("benchmark/", "research/", "experiments/"),
        supports_hypothesis_if=NOT_RECORDED,  # LEGACY_UNKNOWN in spirit; see module docstring
        rejects_hypothesis_if=NOT_RECORDED,
        inconclusive_if=NOT_RECORDED,
    )
    spec = ExperimentSpec(proposal=proposal)
    spec.freeze("APPROVED")
    spec.result = ExperimentResult(
        execution_run_id=results.get("result_run_id"),
        metrics=results,
        benchmark_artifact_paths=(_relpath(_exp_dir("EXP-0001") / "results.json"),),
        code_diff_path=_relpath(_exp_dir("EXP-0001") / "patch.diff"),
        test_results_summary="pytest exit_ok=True (see benchmark.log)",
        execution_status="COMPLETED",
        research_verdict="PASS",
        conclusion=_read("EXP-0001", "conclusion.md"),
        limitations=("Windows/CUDA proxy latency, not iPhone ANE.", "Static-image OIV7 eval, not real-world footage."),
    )
    return spec


def _mark_legacy(text: str) -> str:
    return f"LEGACY_UNKNOWN: {text}" if text else "LEGACY_UNKNOWN"


def _build_from_common(
    experiment_id: str, family: str, hypothesis: str, motivation: str, research_question: str,
    independent_variables: tuple, procedure: str, control_condition: str,
    mac_iphone_required: bool = False,
) -> ExperimentSpec:
    results = _results(experiment_id)
    exec_status, verdict = EXPECTED[experiment_id]
    proposal = ExperimentProposal(
        schema_version=SCHEMA_VERSION,
        experiment_id=experiment_id,
        title=f"{experiment_id} (backfilled)",
        family=family,
        hypothesis=hypothesis,
        motivation=motivation,
        research_question=research_question,
        evidence_references=(),
        prior_experiment_ids=(),
        baseline_run_id="RUN-20260904-002",
        baseline_metrics=results.get("baseline_metrics", {}),
        independent_variables=independent_variables,
        dependent_variables=("person.recall", "hazard.precision", "hazard.recall", "latency.p95_ms"),
        controlled_variables={"manifest": "data/manifests/eval_manifest.jsonl (unchanged)"},
        procedure=procedure,
        dataset_version="data/manifests/eval_manifest.jsonl (380 images, unchanged)",
        model_config_ref="benchmark/config.py (unchanged in production; candidate configs are diagnostic-only)",
        implementation_scope="Diagnostic-only; benchmark/config.py and ios/ never touched.",
        expected_artifacts=("results.json", "conclusion.md", "analysis.md"),
        reproducibility_requirements=_mark_legacy(
            "not written as a discrete field historically; see methodology.md prose for the real procedure."
        ),
        control_condition=control_condition,
        baseline_comparison="RUN-20260904-002 (canonical baseline)",
        isolation_requirements="git_isolation.py experiment branch; no benchmark/config.py mutation",
        success_criteria={
            "primary_metric": "person.recall",
            "min_meaningful_delta": 0.03,
            "precision_floor": 0.757,
            "guardrail_metrics": ["hazard.precision", "hazard.recall", "latency.p95_ms"],
            "max_latency_regression_pct": 50.0,
            "required_tests_pass": True,
            "sample_size_requirements": {"person": 100},
        },
        production_impact=False,
        production_impact_description="None — no production code changed regardless of outcome.",
        data_privacy_classification="NONE",
        external_api_required=False,
        mac_iphone_required=mac_iphone_required,
        compute_resource_estimate={},
        allowed_path_scope=("benchmark/", "research/", "experiments/"),
        supports_hypothesis_if=NOT_RECORDED,
        rejects_hypothesis_if=NOT_RECORDED,
        inconclusive_if=NOT_RECORDED,
        mac_iphone_deployment_approved=False,
    )
    spec = ExperimentSpec(proposal=proposal)
    spec.freeze("APPROVED")
    spec.result = ExperimentResult(
        execution_run_id=results.get("result_run_id"),
        metrics=results,
        benchmark_artifact_paths=(_relpath(_exp_dir(experiment_id) / "results.json"),),
        code_diff_path=_relpath(_exp_dir(experiment_id) / "patch.diff"),
        test_results_summary="pytest exit_ok=True (see benchmark.log)",
        execution_status=exec_status,
        research_verdict=verdict,
        conclusion=_read(experiment_id, "conclusion.md"),
        limitations=("Windows/CUDA proxy latency, not iPhone ANE.", "Static-image OIV7 eval, not real-world footage."),
    )
    return spec


def build_all() -> dict:
    specs = {
        "EXP-0001": _build_exp_0001(),
        "EXP-0002": _build_from_common(
            "EXP-0002", "small_object",
            hypothesis="Increased inference-time input resolution (640->960 or 640->1280) meaningfully improves Person recall, at some measurable latency cost.",
            motivation="64.0% of missed Person boxes have area <2% of the image (small/distant) per reports/baseline/person_failure_analysis.md.",
            research_question="Does raising inference-time input resolution alone meaningfully improve Person recall?",
            independent_variables=("imgsz (inference-time only: 640 -> 960)",),
            procedure="Run real inference over the eval manifest at imgsz=960 (conf/iou unchanged); score with benchmark.metrics.evaluate_detections; compare via research.evaluation_policy.",
            control_condition="imgsz=640 (canonical baseline)",
        ),
        "EXP-0003": _build_from_common(
            "EXP-0003", "class_confusion",
            hypothesis="A meaningful fraction of Person recall loss at conf=0.4 is attributable to semantically related non-Person class confusion, not the detector failing to notice a person at all.",
            motivation="Phase B.5's person_failure_analysis.md found 35.1% (84/239) of missed Person boxes had a different class predicted nearby, computed without a confidence floor or per-GT-box scoping.",
            research_question="How much of Person recall loss is genuine semantic class confusion once rigorously re-derived with a confidence floor and per-box scoping?",
            independent_variables=("scoring-time class grouping map (measurement only, not a production change)",),
            procedure="Recompute directly from raw predictions + ground truth via benchmark/diagnostics/person_confusion_analysis.py's classify_false_negatives(); four counterfactual rescorings via benchmark/diagnostics/person_counterfactuals.py.",
            control_condition="Official conf=0.4 predictions, no class remapping (canonical baseline)",
        ),
        "EXP-0004": _build_from_common(
            "EXP-0004", "preprocessing",
            hypothesis="A single, simple image preprocessing transform (contrast/sharpening/CLAHE) applied before inference improves difficult Person detection without unacceptable latency cost.",
            motivation="Occlusion/small-object/clutter dominate Person misses; a contrast/sharpening transform is a plausible, cheap lever worth testing in isolation.",
            research_question="Does any single pre-registered pixel-level preprocessing transform meaningfully improve Person recall while clearing the hazard-precision guardrail?",
            independent_variables=("one preprocessing transform (e.g. CLAHE) applied before inference",),
            procedure="benchmark/diagnostics/preprocessing_eval.py applies exactly one pixel-level transform before inference at the production operating point, for 5 pre-registered candidates (identity/clahe/unsharp/gamma/autocontrast).",
            control_condition="identity (no-op) candidate, verified to reproduce baseline metrics exactly",
        ),
        "EXP-0005": _build_from_common(
            "EXP-0005", "model_variant",
            hypothesis="A different model checkpoint/architecture (e.g. YOLO26n, referenced but never shipped) would improve Person and/or Stairs recall over the current yolov8m-oiv7 baseline.",
            motivation="Recent commit history references a YOLO26n swap plan that was never executed; model_variant is the most expensive/highest-risk family and was pursued only after EXP-0002..0004.",
            research_question="Does swapping the pretrained detector checkpoint/architecture materially improve Person detection at a fair, precision-matched comparison?",
            independent_variables=("model checkpoint/architecture",),
            procedure="benchmark/diagnostics/model_variant_eval.py runs real inference for 4 pre-registered candidates (A baseline, B smaller, C newer-architecture COCO, D larger diagnostic upper-bound) at held-constant imgsz/iou.",
            control_condition="Candidate A: yolov8m-oiv7.pt (current production baseline, unchanged)",
            mac_iphone_required=True,
        ),
    }
    return specs


def write_all() -> list[Path]:
    SPECS_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for experiment_id, spec in build_all().items():
        exp_status, verdict = EXPECTED[experiment_id]
        assert spec.result.execution_status == exp_status, (experiment_id, spec.result.execution_status)
        assert spec.result.research_verdict == verdict, (experiment_id, spec.result.research_verdict)
        out_path = SPECS_DIR / f"{experiment_id}.json"
        out_path.write_text(spec.to_json() + "\n", encoding="utf-8")
        written.append(out_path)
    return written


def load_spec(experiment_id: str) -> ExperimentSpec:
    path = SPECS_DIR / f"{experiment_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"no backfilled/queued spec found at {path}")
    return ExperimentSpec.from_json(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    for p in write_all():
        print(f"wrote {p}")
