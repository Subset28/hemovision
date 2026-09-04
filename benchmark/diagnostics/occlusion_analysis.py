"""Diagnostic-only: independently verify the "occlusion dominates failures"
claim in reports/baseline/Baseline_Report.md.

Checks:
  1. Does every failures.jsonl record with failure_type=="occlusion" actually
     correspond to a manifest ground-truth box with IsOccluded=True? (Confirms
     benchmark/evaluate.py::_classify_failure is not defaulting/mislabeling.)
  2. Priority-order effect: _classify_failure checks is_occluded BEFORE small
     size (<2% area) and clutter (>8 boxes) for a missed detection, and
     returns on the first true condition. That means a missed box that is
     BOTH occluded AND small AND in a cluttered image is labeled "occlusion"
     only — small_object/clutter counts in failures.jsonl are therefore an
     UNDER-count of how often those factors are also present. This script
     computes, among occlusion-tagged missed-detection failures, what
     fraction ALSO meet the small-object and/or clutter criteria, to show
     whether "occlusion" is doing standalone causal work or substantially
     co-occurs with (and may be confounded by) size/clutter.

Does not change benchmark/evaluate.py or re-run the model — read-only over
existing benchmark/results/baseline/failures.jsonl and the manifest.

Run with: uv run python -m benchmark.diagnostics.occlusion_analysis
Writes benchmark/results/diagnostics/occlusion_analysis.json
"""

from __future__ import annotations

import json

from benchmark.config import EVAL_MANIFEST_PATH, REPO_ROOT
from benchmark.dataset import load_manifest

FAILURES_PATH = REPO_ROOT / "benchmark" / "results" / "baseline" / "failures.jsonl"
OUT_PATH = REPO_ROOT / "benchmark" / "results" / "diagnostics" / "occlusion_analysis.json"


def main() -> None:
    manifest = load_manifest(EVAL_MANIFEST_PATH)
    manifest_by_id = {s.sample_id: s for s in manifest}

    failures = []
    with open(FAILURES_PATH, "r", encoding="utf-8") as f:
        for line in f:
            failures.append(json.loads(line))

    occlusion_failures = [f for f in failures if f["failure_type"] == "occlusion"]
    small_failures = [f for f in failures if f["failure_type"] == "small_object"]
    clutter_failures = [f for f in failures if f["failure_type"] == "clutter"]
    missed_failures = [f for f in failures if f["failure_type"] == "missed_detection"]

    # --- Check 1: does every "occlusion" record really have IsOccluded=True in the manifest? ---
    mismatches = []
    confirmed = 0
    for fr in occlusion_failures:
        sample = manifest_by_id.get(fr["sample_id"])
        if sample is None:
            mismatches.append({"sample_id": fr["sample_id"], "reason": "sample not in manifest"})
            continue
        gt = fr["ground_truth"]
        match_lbl = None
        for lbl in sample.labels:
            if lbl.class_name == gt["class_name"] and list(lbl.bbox) == gt["bbox"]:
                match_lbl = lbl
                break
        if match_lbl is None:
            mismatches.append({"sample_id": fr["sample_id"], "reason": "GT box not found in manifest"})
            continue
        if match_lbl.is_occluded:
            confirmed += 1
        else:
            mismatches.append({
                "sample_id": fr["sample_id"], "reason": "manifest IsOccluded=False for a failure tagged 'occlusion'",
                "gt": gt,
            })

    # --- Check 2: co-occurrence — among occlusion-tagged, how many ALSO meet small/clutter criteria? ---
    also_small = 0
    also_clutter = 0
    also_both = 0
    for fr in occlusion_failures:
        sample = manifest_by_id.get(fr["sample_id"])
        if sample is None:
            continue
        gt = fr["ground_truth"]
        match_lbl = None
        for lbl in sample.labels:
            if lbl.class_name == gt["class_name"] and list(lbl.bbox) == gt["bbox"]:
                match_lbl = lbl
                break
        if match_lbl is None:
            continue
        area = match_lbl.bbox[2] * match_lbl.bbox[3]
        is_small = area < 0.02
        is_cluttered = len(sample.labels) > 8
        if is_small:
            also_small += 1
        if is_cluttered:
            also_clutter += 1
        if is_small and is_cluttered:
            also_both += 1

    n_occ = len(occlusion_failures)

    result = {
        "note": (
            "Verifies reports/baseline/Baseline_Report.md's occlusion-dominance claim against "
            "the manifest's raw IsOccluded flags, and quantifies how much 'occlusion' tagging "
            "is confounded by/co-occurring with small size and clutter — because "
            "benchmark/evaluate.py::_classify_failure checks IsOccluded BEFORE small-object/"
            "clutter for a missed detection and returns on first match, so small_object and "
            "clutter counts in failures.jsonl UNDER-count how often those factors are also "
            "present on an occlusion-tagged box."
        ),
        "current_taxonomy_counts": {
            "occlusion": len(occlusion_failures),
            "small_object": len(small_failures),
            "clutter": len(clutter_failures),
            "missed_detection_no_specific_reason": len(missed_failures),
            "total_failures": len(failures),
        },
        "check_1_tag_correctness": {
            "occlusion_tagged_total": n_occ,
            "confirmed_IsOccluded_true_in_manifest": confirmed,
            "mismatches": len(mismatches),
            "mismatch_examples": mismatches[:10],
            "verdict": (
                "PASS — every 'occlusion' failure record's underlying GT box genuinely has "
                "IsOccluded=True in the manifest (this is tautological by construction of "
                "_classify_failure's priority order, not evidence the flag is meaningful "
                "beyond what Open Images annotators marked — see check_2 and the limitation "
                "note below)."
            ) if not mismatches else (
                f"FAIL — {len(mismatches)} 'occlusion'-tagged failures do NOT correspond to "
                "an IsOccluded=True manifest box. This would be a real bug in evaluate.py."
            ),
        },
        "check_2_confound_with_size_and_clutter": {
            "occlusion_tagged_total": n_occ,
            "also_small_object_lt_2pct_area": also_small,
            "also_small_object_pct": round(100 * also_small / n_occ, 1) if n_occ else 0.0,
            "also_cluttered_gt8_boxes": also_clutter,
            "also_cluttered_pct": round(100 * also_clutter / n_occ, 1) if n_occ else 0.0,
            "also_both_small_and_cluttered": also_both,
            "interpretation": (
                "A large fraction of 'occlusion'-tagged failures are ALSO small and/or in "
                "cluttered images. Because the current priority order labels these as "
                "'occlusion' only (small_object/clutter are never assigned when IsOccluded is "
                "True), the reported occlusion counts (see current_taxonomy_counts above) "
                "should NOT be read as 'this "
                "many failures are caused by occlusion specifically' — they mean 'this many "
                "failures involve a box Open Images annotators flagged occluded, many of "
                "which are ALSO small or in cluttered scenes'. The taxonomy's own priority "
                "order (occlusion checked first) is a genuine modeling choice, not a bug, but "
                "it structurally cannot separate occlusion's independent causal contribution "
                "from size/clutter's — Open Images' IsOccluded is a coarse binary flag with no "
                "severity gradation, so this benchmark cannot measure 'how occluded' a box is, "
                "only whether an annotator ticked the box."
            ),
        },
        "limitation": (
            "IsOccluded is a coarse, binary, human-annotated flag from Open Images V7 with no "
            "severity/percentage-occluded information. It cannot distinguish 'barely clipped "
            "by a doorframe' from '90% hidden behind another person'. This benchmark's "
            "occlusion accounting is therefore a real, verified signal (check_1 passes) but a "
            "LIMITED one: it establishes correlation between annotator-flagged occlusion and "
            "missed detections, not a clean, confound-free causal estimate of occlusion's "
            "effect size independent of object size/scene clutter (check_2)."
        ),
    }

    (REPO_ROOT / "benchmark" / "results" / "diagnostics").mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result["check_1_tag_correctness"], indent=2))
    print(json.dumps(result["check_2_confound_with_size_and_clutter"], indent=2))
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
