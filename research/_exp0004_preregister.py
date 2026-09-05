"""One-time pre-registration update for EXP-0004 (preprocessing).

Run BEFORE `omnilab experiment EXP-0004` is invoked (and before any result is
looked at) to replace the seeded stub's generic evaluation_method/
success_criteria/controls with the full, candidate-by-candidate
pre-registration required by the EXP-0004 task spec: parameters, rationale,
expected benefit, possible failure mode, compute-cost expectation, and
success criteria for each candidate, plus the explicit denoising-exclusion
and combination-skip rationale. hypothesis.md/methodology.md/config.yaml are
regenerated from these DB fields by research/experiment_schema.py at every
QUEUED/RUNNING artifact write, so writing it here (once, before running) IS
the pre-registration record — dated by this update's git commit, which lands
BEFORE the run_exp_0004 commit.

Not part of the reusable research/ pipeline itself (no runner imports this
module) — a deliberate one-shot setup script, analogous to
research/seed_experiments.py's one-shot nature.
"""

from __future__ import annotations

from research.db import OmniLabDB
from research.experiment_lifecycle import find_current_dir
from research.experiment_schema import write_queued_artifacts

EVALUATION_METHOD = """\
Standalone diagnostic script (benchmark/diagnostics/preprocessing_eval.py, \
transforms in benchmark/diagnostics/preprocessing.py) applies exactly ONE \
pixel-level preprocessing transform to each image BEFORE it is handed to \
BaselineModel's underlying ultralytics call, at the app's exact operating \
point (imgsz=640, conf=0.4, iou=0.7, same yolov8m-oiv7.pt weights, same \
data/manifests/eval_manifest.jsonl). benchmark/config.py, benchmark/model.py, \
and benchmark/results/baseline/ (RUN-20260904-002) are never modified — this \
is a pure input-transform inserted only in the diagnostic script's own \
inference calls.

PRE-REGISTERED CANDIDATE SET (chosen and parameterized BEFORE any result was \
inspected; see also CANDIDATE_REGISTRY in benchmark/diagnostics/preprocessing.py):

0. identity (no-op control). Parameters: none. Rationale: correctness check \
-- feeding an unmodified image back into the model through the same in-memory \
array code path used by every other candidate must reproduce the official \
baseline metrics EXACTLY (not just approximately). Expected benefit: none \
(control). Failure mode: if this does NOT reproduce baseline exactly, every \
other candidate's delta is untrustworthy and must not be interpreted. \
Compute cost: 1x baseline inference cost, negligible preprocessing overhead \
(a numpy copy).

1. clahe (contrast-limited adaptive histogram equalization, clip_limit=2.0, \
tile_grid_size=8x8, applied to the L channel in LAB space). Rationale: \
targets the 34.3% LOW_CONFIDENCE_PERSON and 21.8% LOCALIZATION_FAILURE \
buckets from EXP-0003's baseline FN classification (person_confusion_analysis.json) \
-- both plausibly driven by a person blending into a visually similar/low-contrast \
background. Expected benefit: some LOW_CONFIDENCE_PERSON cases cross the 0.4 \
threshold; some LOCALIZATION_FAILURE boxes gain enough edge definition for a \
tighter, IoU-passing box. Possible failure mode: CLAHE amplifies noise/texture \
in already-noisy image regions, potentially creating new false positives \
(hazard.precision guardrail) or shifting existing correct detections' boxes \
slightly, causing IoU regressions among the 64 baseline Person TPs. Compute \
cost: low (a LAB colorspace round-trip + OpenCV's native CLAHE), <5ms/image \
expected on the Windows/CUDA proxy hardware -- negligible relative to model \
inference (baseline p50=18ms/p95=57ms).

2. unsharp (mild unsharp-mask sharpening, gaussian sigma=1.0, amount=0.5). \
Rationale: targets LOCALIZATION_FAILURE (52 cases) via tighter box precision \
from sharper edges, and speculatively a handful of small-object \
TRUE_DETECTOR_MISS cases (92 cases, 38.5% of FNs) where edge contrast against \
background may be the limiting cue. Expected benefit: modest IoU gains on \
LOCALIZATION_FAILURE candidates already near the 0.5 match threshold; unlikely \
to meaningfully move TRUE_DETECTOR_MISS (a genuine capacity/resolution limit \
for very small/heavily-occluded people is not something a sharpening filter \
can manufacture detail for). Possible failure mode: halo artifacts / \
over-sharpening at amount=0.5 could introduce spurious edge-like false \
positives, or destabilize the box regression head's coordinates on already-correct \
detections. Compute cost: low (one Gaussian blur + weighted add), similar \
order of magnitude to CLAHE.

3. gamma (power-law gamma correction, gamma=0.75, i.e. brightening). \
Rationale: targets LOW_CONFIDENCE_PERSON cases specifically in the dataset's \
lighting_category='dim'/'night'/underexposed samples (data/manifests/eval_manifest.jsonl \
records a lighting_category field per sample) -- recovering shadow detail may \
raise the model's raw Person-class confidence for detections currently sitting \
just under 0.4. Expected benefit: a subset of LOW_CONFIDENCE_PERSON cases \
crossing threshold, concentrated in dark-scene samples. Possible failure mode: \
brightening a scene that was NOT actually underexposed washes out contrast \
instead of helping (net-negative on well-lit images), and could raise false-positive \
rate on non-Person hazard classes if noise in dark regions becomes more \
visible. Compute cost: negligible (a 256-entry lookup table applied via \
cv2.LUT).

4. autocontrast (per-channel percentile histogram stretch, low_pct=2.0, \
high_pct=98.0). Rationale: standardizes exposure variance across the \
dataset's mixed indoor/outdoor/lighting conditions; a more global, \
less-locally-aggressive alternative to CLAHE that may reduce confidence \
variance for borderline Person detections without CLAHE's local \
noise-amplification risk. Expected benefit: similar in kind to gamma/CLAHE \
but likely smaller/more diffuse (a global stretch cannot target a specific \
dim region the way CLAHE or gamma can). Possible failure mode: an image \
with a small number of very bright/dark outlier pixels distorts the \
percentile clip range and produces a less useful stretch than intended \
(mitigated by using 2nd/98th percentile rather than true min/max). Compute \
cost: negligible (per-channel percentile + linear rescale via numpy).

EXCLUDED: denoising was on the master spec's suggested-candidate list but is \
explicitly EXCLUDED here -- the eval dataset (Open Images V7 photographs, \
already JPEG-compressed, sourced from real-world photography, not synthetic \
sensor-noise-injected images) shows no noise-related failure signature in \
EXP-0003's FN classification (no baseline FN record's candidate-classification \
reasoning cites visual noise/grain as a factor; the four buckets are \
TRUE_DETECTOR_MISS/LOW_CONFIDENCE_PERSON/SEMANTIC_CLASS_CONFUSION/LOCALIZATION_FAILURE, \
none of which this dataset supports as noise-driven). Including denoising \
without an evidenced hypothesis would violate this experiment's own \
"hypothesis-driven, not tutorial-grab-bag" mandate.

COMBINATIONS: not run as part of the pre-registered candidate set. Per the \
master spec, a combination (e.g. CLAHE+unsharp) is only justified AFTER \
individual results are understood and only with a specific, non-"more is \
better" hypothesis for the combination. This is decided post-hoc, in \
analysis.md, and is clearly labeled EXPLORATORY if run at all -- never \
blended into these five candidates' pre-registered, primary reported results.

Two real inference passes are run per candidate: conf=0.4 (the official \
operating point, used for hazard/Person precision/recall/F1/AP50 and the \
metrics fed to research/evaluation_policy.py) and conf=0.01 (mirrors Phase \
B.5's low_conf_predictions.jsonl / EXP-0003's diagnostic-capture convention, \
used ONLY for the failure-bucket-transition, confidence-distribution, \
localization, and true-miss-recovery analyses -- never for the official \
candidate metrics). Preprocessing wall-clock is measured SEPARATELY from \
model inference wall-clock for every image (never summed silently) -- see \
benchmark/diagnostics/preprocessing_eval.py::run_pass. All latency is \
labeled "Windows/CUDA inference-compute proxy only -- not iPhone, not \
end-to-end" everywhere it is reported.

Person failure-bucket transitions (per EXP-0003's existing 239-record \
classification in benchmark/results/diagnostics/person_confusion_analysis.json) \
are recomputed per candidate by reusing person_confusion_analysis.py's own \
matching (_match_person_boxes_in_sample, reusing benchmark.metrics.greedy_match) \
and classification decision tree (_classify_one) directly -- not a second, \
possibly-drifting reimplementation. Baseline Person TPs (64) are re-checked \
under every candidate for regressions with the same rigor as gains.

Overall verdict convention (stated explicitly, per the master spec's \
requirement to pick one and be explicit): each candidate is independently \
scored through the SAME UNMODIFIED research.evaluation_policy.default_hazard_policy \
guardrail set. The candidate with the largest person.recall improvement that \
does not hard-fail a guardrail is selected as the REPRESENTATIVE result fed \
into this experiment's single stored baseline_metrics/candidate_metrics pair \
and DB verdict (mirroring EXP-0003's convention of feeding one representative \
counterfactual to the policy while reporting all candidates fully). If no \
candidate clears the guardrails with a real (non-noise) improvement, the \
representative is the numerically best candidate by person.recall regardless \
(so a genuine FAILED/INCONCLUSIVE verdict is not hidden), and the overall \
EXPERIMENT status is FAILED/INCONCLUSIVE accordingly -- a "no candidate works" \
outcome is an acceptable, useful result, not something to be massaged into a \
marginal PASS. Every individual candidate's own verdict (via the same policy) \
is also computed and reported in results.json/analysis.md.

Explicit scope reminder: 380 static images, no video/tracking/LiDAR/TTS/real-camera \
processing/real accessibility scenarios. Any benchmark delta here is a Windows/CUDA, \
static-image, offline measurement -- never a claim about real-world OmniSight \
performance."""

SUCCESS_CRITERIA = {
    "primary_metric": "person.recall",
    "min_meaningful_delta": 0.03,
    "guardrails": [
        "hazard.precision >= baseline-0.05",
        "hazard.recall >= baseline-0.02",
        "latency.p95_ms <= baseline*1.5 (preprocess+inference combined)",
    ],
    "representative_candidate_selection": (
        "best person.recall delta among candidates clearing all guardrails; "
        "if none clear, numerically-best person.recall candidate regardless "
        "(does not hide a FAILED/INCONCLUSIVE outcome)"
    ),
    "candidates_preregistered": ["identity", "clahe", "unsharp", "gamma", "autocontrast"],
    "combination_candidates": "none pre-registered; only considered post-hoc/exploratory if individual results warrant it",
    "excluded_candidates": ["denoising (no noise-driven failure signature in EXP-0003's FN classification)"],
}

CONTROLS = {
    "model": "yolov8m-oiv7.pt (same weights)",
    "conf_threshold": 0.4,
    "iou_threshold": 0.7,
    "imgsz": 640,
    "manifest": "data/manifests/eval_manifest.jsonl (unchanged)",
    "matching_algorithm": "benchmark.metrics.greedy_match (reused, not reimplemented)",
    "low_confidence_capture_probe": 0.01,
}

RISKS = (
    "Runtime cost of TWO additional full inference passes per candidate (conf=0.4 and "
    "conf=0.01) x 5 candidates = 10 inference passes over 380 images, on top of the "
    "already-captured baseline; preprocessing itself (CLAHE/unsharp/gamma/autocontrast) "
    "adds a small, separately-measured per-image overhead. No production code touched. "
    "Risk that a transform improves recall but degrades hazard precision or introduces "
    "IoU regressions on already-correct baseline Person TPs -- explicitly checked (see "
    "evaluation_method's regression-check description) rather than assumed away."
)

EXPECTED_OUTCOME = (
    "Directional, evidence-based answer to whether any of the 5 pre-registered candidates "
    "clears the existing hazard-precision guardrail while producing a real (non-noise) "
    "Person recall improvement, with a full failure-bucket-transition breakdown per "
    "candidate. A result of 'no candidate works' (overall FAILED) is an explicitly "
    "anticipated, acceptable outcome, not a defect in the experiment design."
)


def main() -> None:
    with OmniLabDB() as db:
        db.update_fields(
            "EXP-0004",
            evaluation_method=EVALUATION_METHOD,
            success_criteria=SUCCESS_CRITERIA,
            controls=CONTROLS,
            risks=RISKS,
            expected_outcome=EXPECTED_OUTCOME,
        )
        exp = db.get_experiment("EXP-0004")

    exp_dir = find_current_dir("EXP-0004")
    if exp_dir is not None:
        write_queued_artifacts(exp, exp_dir)
    print(f"EXP-0004 pre-registration written. status={exp.status}, dir={exp_dir}")


if __name__ == "__main__":
    main()
