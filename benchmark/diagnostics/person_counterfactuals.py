"""EXP-0003 (class_confusion): diagnostic-only counterfactual rescoring of
Person (and hazard-level) performance under measurement-time class-alias
acceptance rules. NEVER modifies benchmark/config.py, NEVER re-runs
production inference, NEVER touches benchmark/results/baseline/ -- reads the
existing official predictions (conf=0.4, run RUN-20260904-002) and the
existing conf=0.01 low-confidence capture, and recomputes metrics under
alternate SCORING rules only.

Four counterfactuals (see experiments/*/EXP-0003/methodology.md for the
full writeup):
  A. Person only            -- the actual official baseline, restated.
  B. Whole-person alias map -- Man/Woman/Boy/Girl/Human body accepted as a
                                 Person hit if IoU>=0.5 and confidence>=0.4
                                 (the SAME production threshold -- this asks
                                 "what if we accepted this label as Person",
                                 not "what if we lowered the threshold").
  C. + person subparts      -- B's alias set plus Human face/head/arm/leg/
                                 hand/foot/ear/eye/nose/mouth/hair.
  D. Confidence-conditioned -- B's alias set (whole-person only, matching
     alias sweep              the spec's explicit ask), swept over
                                 confidence floors [0.25, 0.4, 0.6, 0.8].

Implementation: for each counterfactual, build an augmented Person detection
list = (real baseline Person predictions, unchanged) UNION (alias/subpart
predictions from the low-conf capture that pass the counterfactual's
confidence floor, relabeled as "Person" for scoring purposes only -- no
production label is ever changed). Score with the EXACT SAME
benchmark.metrics.greedy_match/evaluate_detections algorithm used everywhere
else in this repo (not a reimplementation), against the real Person ground
truth, at the real matching IoU of 0.5. This automatically handles
double-counting/duplicate-claim correctness the same way the official
baseline scoring does (greedy per-image claiming, one detection per GT box).

For the hazard-level rollup, the other 7 hazard classes' detections are left
completely unchanged; only the Person-class detection list is swapped for
the augmented one.

Run with: uv run python -m benchmark.diagnostics.person_counterfactuals
Writes benchmark/results/diagnostics/person_counterfactuals.json
"""

from __future__ import annotations

import json

from benchmark.config import EVAL_MANIFEST_PATH, HAZARD_CLASS_MAP, REPO_ROOT
from benchmark.dataset import load_manifest
from benchmark.diagnostics.human_class_map import PERSON_SUBPARTS, WHOLE_PERSON_ALIASES
from benchmark.metrics import Detection, GroundTruth, evaluate_detections

DIAG_DIR = REPO_ROOT / "benchmark" / "results" / "diagnostics"
LOW_CONF_PATH = DIAG_DIR / "low_conf_predictions.jsonl"
BASELINE_PRED_PATH = REPO_ROOT / "benchmark" / "results" / "baseline" / "predictions.jsonl"
OUT_PATH = DIAG_DIR / "person_counterfactuals.json"

HAZARD_CLASSES_OIV7 = set(HAZARD_CLASS_MAP.values())
BASELINE_CONF = 0.4
D_SWEEP_FLOORS = (0.25, 0.4, 0.6, 0.8)


def _load_jsonl_by_id(path, key_field="sample_id") -> dict:
    out = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            out[d[key_field]] = d
    return out


def _load_data():
    manifest = load_manifest(EVAL_MANIFEST_PATH)
    baseline_preds = _load_jsonl_by_id(BASELINE_PRED_PATH)
    low_conf_preds = _load_jsonl_by_id(LOW_CONF_PATH)
    return manifest, baseline_preds, low_conf_preds


def _all_ground_truths(manifest) -> list:
    gts = []
    for sample in manifest:
        for lbl in sample.labels:
            gts.append(GroundTruth(sample_id=sample.sample_id, class_name=lbl.class_name, bbox=lbl.bbox))
    return gts


def _baseline_hazard_detections(manifest, baseline_preds, exclude_person: bool) -> list:
    """All baseline (conf=0.4) detections for the 7 non-Person hazard
    classes, unchanged -- optionally excluding Person too (caller supplies
    the Person-class detections separately for counterfactual scoring)."""
    dets = []
    other_classes = HAZARD_CLASSES_OIV7 - ({"Person"} if exclude_person else set())
    for sample in manifest:
        for p in baseline_preds.get(sample.sample_id, {}).get("predictions", []):
            if p["class_name"] in other_classes:
                dets.append(Detection(sample_id=sample.sample_id, class_name=p["class_name"],
                                       bbox=tuple(p["bbox"]), confidence=p["confidence"]))
    return dets


def _person_detections_baseline(manifest, baseline_preds) -> list:
    dets = []
    for sample in manifest:
        for p in baseline_preds.get(sample.sample_id, {}).get("predictions", []):
            if p["class_name"] == "Person":
                dets.append(Detection(sample_id=sample.sample_id, class_name="Person",
                                       bbox=tuple(p["bbox"]), confidence=p["confidence"]))
    return dets


def _person_detections_with_alias(manifest, baseline_preds, low_conf_preds, alias_classes: frozenset,
                                   alias_conf_floor: float) -> list:
    """Real baseline Person detections + alias-class low-conf-capture
    detections >= alias_conf_floor, relabeled 'Person' for scoring only."""
    dets = _person_detections_baseline(manifest, baseline_preds)
    for sample in manifest:
        for p in low_conf_preds.get(sample.sample_id, {}).get("predictions", []):
            if p["class_name"] in alias_classes and p["confidence"] >= alias_conf_floor:
                dets.append(Detection(sample_id=sample.sample_id, class_name="Person",
                                       bbox=tuple(p["bbox"]), confidence=p["confidence"]))
    return dets


def _score_counterfactual(manifest, all_gts, person_dets: list, other_hazard_dets: list) -> dict:
    person_gts = [g for g in all_gts if g.class_name == "Person"]
    person_overall, _, _ = evaluate_detections(person_dets, person_gts, ["Person"], map_ious=(0.5,))

    hazard_dets = person_dets + other_hazard_dets
    hazard_overall, _, _ = evaluate_detections(hazard_dets, all_gts, sorted(HAZARD_CLASSES_OIV7), map_ious=(0.5,))

    return {
        "person": {
            "precision": person_overall.precision, "recall": person_overall.recall,
            "f1": person_overall.f1, "tp": person_overall.tp, "fp": person_overall.fp,
            "fn": person_overall.fn, "num_gt": person_overall.num_gt,
        },
        "hazard": {
            "precision": hazard_overall.precision, "recall": hazard_overall.recall,
            "f1": hazard_overall.f1, "tp": hazard_overall.tp, "fp": hazard_overall.fp,
            "fn": hazard_overall.fn, "num_gt": hazard_overall.num_gt,
        },
    }


def run_all() -> dict:
    manifest, baseline_preds, low_conf_preds = _load_data()
    all_gts = _all_ground_truths(manifest)
    other_hazard_dets = _baseline_hazard_detections(manifest, baseline_preds, exclude_person=True)

    results = {}

    # ---- A. Person only (the actual official baseline, restated) ----------
    person_dets_a = _person_detections_baseline(manifest, baseline_preds)
    scored_a = _score_counterfactual(manifest, all_gts, person_dets_a, other_hazard_dets)
    scored_a["recovered_gts"] = 0
    scored_a["new_false_positives"] = 0
    results["A_person_only_baseline"] = scored_a

    # ---- B. Whole-person alias mapping (conf>=0.4, IoU>=0.5) --------------
    person_dets_b = _person_detections_with_alias(
        manifest, baseline_preds, low_conf_preds, WHOLE_PERSON_ALIASES, BASELINE_CONF
    )
    scored_b = _score_counterfactual(manifest, all_gts, person_dets_b, other_hazard_dets)
    scored_b["recovered_gts"] = scored_b["person"]["tp"] - scored_a["person"]["tp"]
    scored_b["new_false_positives"] = scored_b["person"]["fp"] - scored_a["person"]["fp"]
    results["B_whole_person_alias_conf0.4"] = scored_b

    # ---- C. + person subparts (conf>=0.4, IoU>=0.5) ------------------------
    person_dets_c = _person_detections_with_alias(
        manifest, baseline_preds, low_conf_preds, WHOLE_PERSON_ALIASES | PERSON_SUBPARTS, BASELINE_CONF
    )
    scored_c = _score_counterfactual(manifest, all_gts, person_dets_c, other_hazard_dets)
    scored_c["recovered_gts"] = scored_c["person"]["tp"] - scored_a["person"]["tp"]
    scored_c["new_false_positives"] = scored_c["person"]["fp"] - scored_a["person"]["fp"]
    scored_c["recovered_gts_beyond_B"] = scored_c["person"]["tp"] - scored_b["person"]["tp"]
    results["C_plus_subparts_conf0.4"] = scored_c

    # ---- D. Confidence-conditioned whole-person alias sweep ----------------
    sweep = {}
    for floor in D_SWEEP_FLOORS:
        person_dets_d = _person_detections_with_alias(
            manifest, baseline_preds, low_conf_preds, WHOLE_PERSON_ALIASES, floor
        )
        scored_d = _score_counterfactual(manifest, all_gts, person_dets_d, other_hazard_dets)
        scored_d["recovered_gts"] = scored_d["person"]["tp"] - scored_a["person"]["tp"]
        scored_d["new_false_positives"] = scored_d["person"]["fp"] - scored_a["person"]["fp"]
        sweep[str(floor)] = scored_d
    results["D_confidence_conditioned_alias_sweep"] = sweep

    results["_methodology"] = {
        "match_iou": 0.5,
        "alias_conf_floor_B_and_C": BASELINE_CONF,
        "whole_person_aliases": sorted(WHOLE_PERSON_ALIASES),
        "person_subparts": sorted(PERSON_SUBPARTS),
        "d_sweep_floors": list(D_SWEEP_FLOORS),
        "note": (
            "All counterfactuals reuse the real official baseline Person detections "
            "(conf=0.4) plus alias/subpart detections drawn from the existing conf=0.01 "
            "low-confidence capture (benchmark/results/diagnostics/low_conf_predictions.jsonl) "
            "-- filtered to each counterfactual's own confidence floor. No new inference was "
            "run. benchmark/config.py and benchmark/results/baseline/ are never modified."
        ),
    }
    return results


def main() -> None:
    results = run_all()
    a = results["A_person_only_baseline"]["person"]
    b = results["B_whole_person_alias_conf0.4"]
    c = results["C_plus_subparts_conf0.4"]
    print(f"A (baseline)      Person P={a['precision']:.3f} R={a['recall']:.3f}")
    print(f"B (whole-alias)   Person P={b['person']['precision']:.3f} R={b['person']['recall']:.3f} "
          f"recovered={b['recovered_gts']} new_fp={b['new_false_positives']}")
    print(f"C (+subparts)     Person P={c['person']['precision']:.3f} R={c['person']['recall']:.3f} "
          f"recovered={c['recovered_gts']} new_fp={c['new_false_positives']} beyond_B={c['recovered_gts_beyond_B']}")
    for floor, d in results["D_confidence_conditioned_alias_sweep"].items():
        print(f"D (floor={floor}) Person P={d['person']['precision']:.3f} R={d['person']['recall']:.3f} "
              f"recovered={d['recovered_gts']} new_fp={d['new_false_positives']}")

    DIAG_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
