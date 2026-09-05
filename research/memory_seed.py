"""Phase E — one-time import of Phase A-D findings into `research/memory.db`.

Run once, by hand:

    uv run python -m research.memory_seed

Idempotent: refuses (raises RuntimeError) if the DB already has any records,
rather than silently duplicating or clobbering — same "guard rather than
double-run" pattern as `research/seed_experiments.py`.

Every record below cites a concrete on-disk artifact/experiment/run — no
fabricated numbers. Sources are named inline as comments; the exact figures
were read directly from the cited files as of this Phase E pass (see
research/README.md's Phase E section for the audit this seed script is the
output of).
"""

from __future__ import annotations

from research.memory_db import MemoryDB, MemoryRecord

# Git commit hashes, resolved via `git log --oneline -- <path>` (see
# research/README.md Phase E section for the exact commands run):
COMMIT_BASELINE_ARTIFACTS = "76c5508044549f945fb1da2ea2da86be85477172"  # v1.2 checkpoint that produced RUN-20260904-002
COMMIT_PHASE_AB_DOCS = "b648935"  # "checkpoint: commit Phase A/B/B.5 lab deliverables"
COMMIT_PHASE_C_INFRA = "e038d96"  # "feat: Phase C — experiment database..." (evaluation_policy.py guardrails)
COMMIT_EXP_0001 = "3e6d7e1"
COMMIT_EXP_0002 = "8a21c8b"
COMMIT_EXP_0003 = "f78ee10"
COMMIT_EXP_0004 = "51ebdf8"
COMMIT_EXP_0005 = "7a95eaa"
COMMIT_EXP_0005_ANALYSIS = "0a55e2b"

BASELINE_RUN_ID = "RUN-20260904-002"
DATASET_VERSION = "Open Images V7, 380-image eval manifest, 4916 GT boxes (data/manifests/eval_manifest.jsonl)"


def _mk(db: MemoryDB, **kw) -> MemoryRecord:
    rec = MemoryRecord(record_id=db.next_record_id(), **kw)
    return db.insert(rec)


def seed(db: MemoryDB) -> list[MemoryRecord]:
    existing = db.list_records(include_superseded=True)
    if existing:
        raise RuntimeError(
            f"research/memory.db already has {len(existing)} record(s) — refusing to reseed. "
            "Delete research/memory.db first if you really want a clean reseed."
        )

    created: list[MemoryRecord] = []

    # -----------------------------------------------------------------
    # VERIFIED — baseline facts
    # -----------------------------------------------------------------

    created.append(_mk(
        db,
        claim="Shipped production detector is Ultralytics YOLOv8m, trained on Open Images V7 "
              "(601-class vocabulary), conf=0.4, iou=0.7, imgsz=640. YOLO26n is referenced in "
              "commit history/docs but was never actually shipped (StepHazardDetector Swift code "
              "landed; the model swap itself did not).",
        tag="VERIFIED",
        run_id=BASELINE_RUN_ID,
        artifact_path="OMNISIGHT_ARCHITECTURE.md",
        metric_field="model identity / operating point (section 3)",
        dataset_version=DATASET_VERSION,
        git_commit=COMMIT_PHASE_AB_DOCS,
        category="baseline_model",
        notes="Confirmed directly from embedded Core ML model metadata inspection, not from docs alone.",
    ))

    created.append(_mk(
        db,
        claim="Baseline hazard-class metrics (person, car, truck, bus, bicycle, motorcycle, "
              "stairs, dog): Precision=0.807, Recall=0.480, F1=0.602, mAP@50=0.582 (TP=368, FP=88, FN=398).",
        tag="VERIFIED",
        run_id=BASELINE_RUN_ID,
        artifact_path="benchmark/results/baseline/metrics.json",
        metric_field="hazard.{precision,recall,f1,map50}",
        dataset_version=DATASET_VERSION,
        git_commit=COMMIT_BASELINE_ARTIFACTS,
        category="baseline_hazard",
    ))

    created.append(_mk(
        db,
        claim="Person recall = 0.211 at the production operating point (conf=0.4), precision = 0.667, "
              "GT=303 boxes (the largest and most statistically trustworthy hazard-class sample). "
              "This is the worst hazard-class recall in the dataset.",
        tag="VERIFIED",
        run_id=BASELINE_RUN_ID,
        artifact_path="benchmark/results/baseline/per_class.json",
        metric_field="person.{recall,precision,num_gt}",
        dataset_version=DATASET_VERSION,
        git_commit=COMMIT_BASELINE_ARTIFACTS,
        category="person_recall",
    ))

    created.append(_mk(
        db,
        claim="Hazard-precision guardrail floor used by the evaluation policy is baseline_precision - 0.05 "
              "= 0.807 - 0.05 = 0.757 (hazard.precision guardrail, `default_hazard_policy`); hazard-recall "
              "floor is baseline - 0.02; p95 latency floor is baseline * 1.5.",
        tag="VERIFIED",
        artifact_path="research/evaluation_policy.py",
        metric_field="default_hazard_policy() guardrails list",
        git_commit=COMMIT_PHASE_C_INFRA,
        category="evaluation_policy",
    ))

    created.append(_mk(
        db,
        claim="Windows/CUDA inference-only latency proxy (RTX 3070 Ti): p50=18.0ms, p95=57.1ms, p99=65.8ms, mean=24.3ms.",
        tag="VERIFIED",
        run_id=BASELINE_RUN_ID,
        artifact_path="benchmark/results/baseline/metrics.json",
        metric_field="latency.{p50_ms,p95_ms,p99_ms,mean_ms}",
        dataset_version=DATASET_VERSION,
        git_commit=COMMIT_BASELINE_ARTIFACTS,
        category="latency",
    ))

    created.append(_mk(
        db,
        claim="Thin-sample hazard classes and their GT counts: Stairs=45, Truck=42, Bus=49, Motorcycle=49 "
              "— each roughly an order of magnitude smaller than Person (303) or Car (148); "
              "research/evaluation_policy.py's sample_size_floors (min_gt_count=100 for each) encodes "
              "this as an automatic INCONCLUSIVE downgrade.",
        tag="VERIFIED",
        run_id=BASELINE_RUN_ID,
        artifact_path="reports/baseline/BASELINE_SCORECARD.md",
        metric_field="Section 2 per-class GT counts",
        dataset_version=DATASET_VERSION,
        git_commit=COMMIT_PHASE_AB_DOCS,
        category="sample_size",
    ))

    # -----------------------------------------------------------------
    # VERIFIED — EXP-0003's rigorous Person failure-mode breakdown (the
    # CURRENT, correct numbers — see the SUPERSEDED pair below for the
    # informal figure this replaces)
    # -----------------------------------------------------------------

    verified_failure_breakdown = _mk(
        db,
        claim="Rigorous IoU-based re-matching of all 239 Person ground-truth false negatives at the "
              "official baseline (conf=0.4, iou=0.7) yields 5 mutually-exclusive categories: "
              "TRUE_DETECTOR_MISS=92 (38.5%), LOW_CONFIDENCE_PERSON=82 (34.3%), "
              "SEMANTIC_CLASS_CONFUSION=13 (5.4%), LOCALIZATION_FAILURE=52 (21.8%). "
              "Secondary flag DUPLICATE_MULTI_LABEL present on 46/239 overall.",
        tag="VERIFIED",
        experiment_id="EXP-0003",
        run_id=BASELINE_RUN_ID,
        artifact_path="experiments/completed/EXP-0003/results.json",
        metric_field="five-category breakdown, Section 1",
        dataset_version=DATASET_VERSION,
        git_commit=COMMIT_EXP_0003,
        category="person_failure_modes",
        independent_variable="scoring-time class grouping map (measurement only, not a production change)",
        verdict="FAIL",
        notes="Also reported in reports/baseline/person_class_confusion_analysis.md Section 1.",
    )
    created.append(verified_failure_breakdown)

    # -----------------------------------------------------------------
    # SUPERSESSION: the flagship case — Phase B.5's informal 35.1% figure,
    # superseded by EXP-0003's rigorous 5.4% figure.
    # -----------------------------------------------------------------

    old_confusion_claim = _mk(
        db,
        claim="~35.1% of Person misses involve classification confusion with a different "
              "person-adjacent OIV7 class (Man/Woman/Human body/Clothing) — computed by counting "
              "ANY same-location alternate-class detection at ANY confidence, including near-zero "
              "noise at conf=0.01.",
        tag="VERIFIED",  # was presented as a verified figure at the time; correctness is what SUPERSEDED marks
        run_id=BASELINE_RUN_ID,
        artifact_path="reports/baseline/person_failure_analysis.md",
        metric_field="failure-breakdown percentage for classification confusion",
        dataset_version=DATASET_VERSION,
        git_commit=COMMIT_PHASE_AB_DOCS,
        category="person_failure_modes",
        notes="Phase B.5 finding. Also appears in reports/baseline/BASELINE_SCORECARD.md and "
              "research/memory/known_failures.md — SUPERSEDED by EXP-0003's rigorous re-matching, "
              "see superseded_by.",
    )
    created.append(old_confusion_claim)

    new_confusion_claim = _mk(
        db,
        claim="Genuine SEMANTIC_CLASS_CONFUSION (a different human-related class predicted at "
              "IoU>=0.5 and confidence>=0.4, the production floor) accounts for only 13/239 (5.4%) "
              "of Person false negatives — far below the earlier 35.1% (84/239) figure, which counted "
              "any same-location alternate-class prediction at any confidence (including near-zero "
              "conf=0.01 noise) as 'confusion'. Most of that gap reclassifies as LOCALIZATION_FAILURE "
              "(52, 21.8%) or TRUE_DETECTOR_MISS (92, 38.5%) under rigorous IoU-based matching.",
        tag="VERIFIED",
        experiment_id="EXP-0003",
        run_id=BASELINE_RUN_ID,
        artifact_path="experiments/completed/EXP-0003/results.json",
        metric_field="Section 3, 'Is the Phase B.5 35.1% figure still correct?'",
        dataset_version=DATASET_VERSION,
        git_commit=COMMIT_EXP_0003,
        category="person_failure_modes",
        independent_variable="scoring-time class grouping map (measurement only, not a production change)",
        verdict="FAIL",
        notes="Also reported in reports/baseline/person_class_confusion_analysis.md Section 3. "
              "SUPERSEDES the informal 35.1% figure.",
    )
    created.append(new_confusion_claim)

    db.supersede(old_confusion_claim.record_id, new_confusion_claim.record_id,
                 note="EXP-0003 rigorous IoU-based re-matching: 13/239 (5.4%), not 84/239 (35.1%)")

    # -----------------------------------------------------------------
    # REJECTED_HYPOTHESIS — the 5 mandatory records, one per experiment
    # -----------------------------------------------------------------

    created.append(_mk(
        db,
        claim="Global confidence-threshold reduction alone can resolve Person recall without "
              "unacceptable precision loss. REJECTED: at conf=0.05, Person recall rises 0.211->0.479 "
              "but hazard precision collapses 0.807->0.381 (guardrail floor 0.757), a violation far "
              "outside the noise margin.",
        tag="REJECTED_HYPOTHESIS",
        experiment_id="EXP-0001",
        run_id=BASELINE_RUN_ID + "+threshold_sweep@conf=0.05",
        artifact_path="experiments/completed/EXP-0001/results.json",
        metric_field="candidate_metrics.hazard.precision vs guardrail",
        dataset_version=DATASET_VERSION,
        git_commit=COMMIT_EXP_0001,
        category="rejected_intervention",
        independent_variable="confidence_threshold",
        verdict="PASS",  # research_verdict=PASS because this is a confirmatory/NEGATIVE hypothesis — see research/README.md
        notes="EXP-0001's research_verdict is PASS because its hypothesis IS the negative claim "
              "('threshold alone cannot fix Person recall') — PASS means the negative claim was "
              "confirmed, not that lowering the threshold is production-viable. See "
              "research/README.md 'EXP-0001's PASS verdict, explicitly'.",
    ))

    created.append(_mk(
        db,
        claim="Increasing inference-time input resolution alone (640->960) meaningfully improves "
              "Person recall. REJECTED: Person recall actually dropped 0.211->0.165 and hazard "
              "recall dropped below its guardrail floor (0.449 vs 0.460), at 1.27x the baseline latency.",
        tag="REJECTED_HYPOTHESIS",
        experiment_id="EXP-0002",
        run_id="EXP-0002-imgsz960-inline",
        artifact_path="experiments/completed/EXP-0002/results.json",
        metric_field="candidate_metrics.{person.recall,hazard.recall}",
        dataset_version=DATASET_VERSION,
        git_commit=COMMIT_EXP_0002,
        category="rejected_intervention",
        independent_variable="imgsz (inference-time only: 640 -> 960)",
        verdict="FAIL",
    ))

    created.append(_mk(
        db,
        claim="Broad semantic aliasing (remapping Man/Woman/Boy/Girl/Human body to Person at "
              "scoring time) recovers Person recall while preserving precision. REJECTED: accepting "
              "whole-person aliases at conf>=0.4 recovers only 14/239 GTs but introduces 93 new false "
              "positives, dropping hazard precision 0.807->0.679 (0.129 below floor, non-noisy). No "
              "confidence floor in the swept range (0.25-0.8) rescues the tradeoff; subpart classes "
              "(Human hand/face) recover 0 additional GTs while adding more FPs.",
        tag="REJECTED_HYPOTHESIS",
        experiment_id="EXP-0003",
        run_id=BASELINE_RUN_ID,
        artifact_path="experiments/completed/EXP-0003/results.json",
        metric_field="counterfactual B (Section 5 of person_class_confusion_analysis.md)",
        dataset_version=DATASET_VERSION,
        git_commit=COMMIT_EXP_0003,
        category="rejected_intervention",
        independent_variable="scoring-time class grouping map (measurement only, not a production change)",
        verdict="FAIL",
    ))

    created.append(_mk(
        db,
        claim="A generic pixel-level preprocessing transform (contrast/sharpening/CLAHE-style) applied "
              "before inference improves Person recall enough to be actionable. REJECTED "
              "(INCONCLUSIVE, not a clean pass): best candidate ('gamma') moved person.recall by only "
              "+0.0198 (0.211->0.231), below the 0.03 minimum-meaningful-delta threshold — a small, "
              "not-clearly-real effect.",
        tag="REJECTED_HYPOTHESIS",
        experiment_id="EXP-0004",
        run_id="EXP-0004-preprocessing-inline-representative=gamma",
        artifact_path="experiments/completed/EXP-0004/results.json",
        metric_field="reasons: primary metric 'person.recall' delta",
        dataset_version=DATASET_VERSION,
        git_commit=COMMIT_EXP_0004,
        category="rejected_intervention",
        independent_variable="one preprocessing transform (e.g. CLAHE) applied before inference",
        verdict="INCONCLUSIVE",
        notes="Recorded as REJECTED_HYPOTHESIS per the task's mandatory 5, though the DB "
              "research_verdict is technically INCONCLUSIVE, not FAIL — the effect was too small to "
              "act on, which is the operative conclusion for a future agent deciding whether to retry "
              "this direction (do not re-propose 'apply CLAHE' as if untested).",
    ))

    created.append(_mk(
        db,
        claim="Simple model-size/checkpoint scaling alone (same OIV7 vocabulary, larger backbone) "
              "meaningfully improves Person recall at production confidence. REJECTED for the "
              "as-tested candidates: the best fixed-conf=0.4 candidate (yolov8l-oiv7) moved "
              "person.recall by only +0.0198 (0.211->0.231), below the 0.03 minimum-meaningful-delta "
              "threshold — the same negligible-effect-size result as EXP-0004.",
        tag="REJECTED_HYPOTHESIS",
        experiment_id="EXP-0005",
        run_id="EXP-0005-model-variant-inline-representative=D_yolov8l_oiv7_diagnostic_upper_bound",
        artifact_path="experiments/completed/EXP-0005/results.json",
        metric_field="reasons: primary metric 'person.recall' delta",
        dataset_version=DATASET_VERSION,
        git_commit=COMMIT_EXP_0005,
        category="rejected_intervention",
        independent_variable="model checkpoint/architecture",
        verdict="INCONCLUSIVE",
        notes="'Just use a larger YOLO' (naive model-size scaling, same training vocabulary) is "
              "REJECTED by this result. See the separate SUPPORTED_HYPOTHESIS record below for the "
              "narrower, NOT-equivalent claim about architecture/representation differences "
              "(candidate C, a different architecture family) that this same experiment surfaced.",
    ))

    # -----------------------------------------------------------------
    # SUPPORTED_HYPOTHESIS — architecture/representation, carefully worded
    # -----------------------------------------------------------------

    created.append(_mk(
        db,
        claim="Architecture, training-data, and/or learned-representation differences between "
              "detector checkpoints MAY matter for recovering TRUE_DETECTOR_MISS Person cases — "
              "candidate C (yolo11m, a different architecture family, COCO-trained) recovered 17/92 "
              "(18.5%) TRUE_DETECTOR_MISS cases at fixed conf=0.4, the first candidate across "
              "EXP-0001 through EXP-0005 to recover ANY TRUE_DETECTOR_MISS case, versus 1/92 for the "
              "same-family, larger yolov8l-oiv7 candidate and 0/92 implied by EXP-0004's negligible "
              "overall recall movement. This is NOT proof that model capacity is the bottleneck — "
              "candidate C's gain is confounded with its different training data/class vocabulary "
              "(COCO vs Open Images V7), and it was rejected as a production candidate on hazard-"
              "precision grounds regardless of this recall signal.",
        tag="SUPPORTED_HYPOTHESIS",
        experiment_id="EXP-0005",
        run_id="EXP-0005-model-variant-inline",
        artifact_path="experiments/completed/EXP-0005/person_transitions.json",
        metric_field="candidate C TRUE_DETECTOR_MISS -> TP transitions (17/92)",
        dataset_version=DATASET_VERSION,
        git_commit=COMMIT_EXP_0005_ANALYSIS,
        category="model_representation",
        independent_variable="model checkpoint/architecture",
        verdict="INCONCLUSIVE",
        notes="Explicitly worded to avoid the rejected framing 'model capacity is the bottleneck' — "
              "see experiments/completed/EXP-0005/analysis.md lines ~64-129 for the full reasoning "
              "and the confound with training-data/vocabulary differences.",
    ))

    # -----------------------------------------------------------------
    # LIMITATION — the 7 mandatory records
    # -----------------------------------------------------------------

    limitation_claims = [
        ("Windows/CUDA (RTX 3070 Ti) inference latency is NOT iPhone Neural Engine latency. "
         "No CoreML/ANE dispatch, no camera capture, no ARKit, no SORT tracker, no TTS — this is a "
         "desktop-GPU inference-only proxy.",
         "reports/baseline/BASELINE_SCORECARD.md", "Section 5", "latency"),
        ("Open Images V7 static-image evaluation is NOT real-world OmniSight validation. It is a "
         "corpus of static internet photos, not handheld-camera accessibility footage — it does not "
         "reproduce live camera motion, chest-height framing, indoor low light, walking-pace motion "
         "blur, or unusual viewpoints.",
         "reports/baseline/BASELINE_SCORECARD.md", "Section 6", "eval_validity"),
        ("Ground-truth box area is used as a proxy for physical distance/size; it is not a measured "
         "physical distance and has no depth/LiDAR grounding in this dataset.",
         "reports/baseline/person_failure_analysis.md", "small/distant proxy definition (<2% image area)", "eval_methodology"),
        ("Thin-sample hazard classes (Stairs GT=45, Truck GT=42, Bus GT=49, Motorcycle GT=49) require "
         "caution: a swing of a handful of boxes moves their recall by ~10 percentage points. Never "
         "present their numbers with Person/Car-level statistical confidence.",
         "reports/baseline/BASELINE_SCORECARD.md", "Section 2/6", "sample_size"),
        ("Occlusion-tagged failures are confounded with small size and image clutter, not an "
         "independently-isolated cause: of all occlusion-tagged failures, 56.0% are also small "
         "(<2% area) and 88.7% are also in a cluttered image (>8 boxes).",
         "research/memory/known_failures.md", "occlusion_analysis.json summary", "eval_methodology"),
        ("Fixed-confidence (conf=0.4) cross-architecture comparisons can mislead: different model "
         "families/checkpoints may have different confidence calibration, so comparing recall at one "
         "fixed threshold across architectures (as EXP-0005 does for its primary verdict) can "
         "understate or overstate a candidate's real potential relative to a precision-matched "
         "comparison.",
         "experiments/completed/EXP-0005/analysis.md", "precision-matched sweep discussion", "eval_methodology"),
        ("Production (`ios/`, `benchmark/config.py`'s real operating point, the canonical baseline run "
         "`RUN-20260904-002`) remains protected throughout this lab's work — no experiment modifies "
         "shipped code, and diagnostic/candidate configurations are never mistaken for production "
         "settings.",
         "research/README.md", "Safety / permission boundaries", "safety"),
    ]
    for claim, artifact, metric, category in limitation_claims:
        created.append(_mk(
            db,
            claim=claim,
            tag="LIMITATION",
            artifact_path=artifact,
            metric_field=metric,
            dataset_version=DATASET_VERSION,
            git_commit=COMMIT_PHASE_AB_DOCS,
            category=category,
        ))

    # -----------------------------------------------------------------
    # OPEN_QUESTION — the 5 the user listed + others from open_questions.md
    # -----------------------------------------------------------------

    open_questions = [
        ("Does Person recall degrade differently for small-vs-occluded-vs-confused causes when "
         "analyzed independently (fully deconfounded)? Open Images' binary IsOccluded flag cannot "
         "support this alone.", "person_failure_modes"),
        ("What is the real on-device (ANE/CoreML) latency for any candidate change? Nothing in this "
         "lab can answer this without a Mac + physical iPhone (REQUIRES_MAC/REQUIRES_IPHONE).",
         "latency"),
        ("Would a human-collected OmniSight-specific dataset (docs/DATASETS.md Section 8) change any "
         "of these findings? Open Images V7 is documented as not representative of real accessibility-"
         "usage conditions.", "eval_validity"),
        ("Would YOLO26n (referenced in commit history, never shipped) improve Person/Stairs recall? "
         "EXP-0005 tested other model variants but not YOLO26n specifically, and Phase D is now "
         "closed — this remains untested.", "model_representation"),
        ("Is there a combination of interventions (e.g. a different architecture family AND targeted "
         "preprocessing) that could recover more TRUE_DETECTOR_MISS cases than any single lever tested "
         "in EXP-0001-0005 alone? No combined/interaction experiment was run; Phase D is closed.",
         "model_representation"),
        ("What, mechanistically, distinguishes the 92 TRUE_DETECTOR_MISS cases from the other 147 "
         "Person FNs beyond size (68/92 are small)? No feature-level analysis (attention maps, "
         "activation inspection) was attempted.", "person_failure_modes"),
        ("Literature-grounded hypothesis generation (research/literature/) was never started — no "
         "OPENROUTER_API_KEY was available in this environment, and Phase E explicitly makes no LLM "
         "calls either.", "process"),
    ]
    for claim, category in open_questions:
        created.append(_mk(
            db,
            claim=claim,
            tag="OPEN_QUESTION",
            artifact_path="research/memory/open_questions.md",
            metric_field="Unresolved from Phase B/B.5" if category != "process" else "Literature-grounded hypothesis generation",
            dataset_version=DATASET_VERSION,
            git_commit=COMMIT_PHASE_AB_DOCS,
            category=category,
        ))

    return created


def main() -> int:
    db = MemoryDB()
    try:
        created = seed(db)
    finally:
        db.close()
    print(f"Seeded {len(created)} memory record(s) into research/memory.db")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
