"""EXP-0003 (class_confusion): rigorous, IoU-based, bug-free re-classification
of every Person ground-truth false negative at the official baseline
(conf=0.4, iou=0.7 -- benchmark/config.py, run RUN-20260904-002), into one of
5 mutually-exclusive primary categories, plus secondary/overlapping flags.

Recomputes DIRECTLY from raw predictions + ground truth (per the EXP-0003
methodology: "recomputing directly from raw predictions+GT is more rigorous
and self-contained than trusting failures.jsonl's categorization"), reusing
`benchmark/results/diagnostics/low_conf_predictions.jsonl` (Phase B.5's
already-captured conf=0.01 full per-image raw detections) so NO new
inference is run and `benchmark/results/baseline/` is never touched.

Bug-class avoided (see benchmark/evaluate.py::_classify_failure's own
bug-fix docstring for the historical version of this bug): a sample with
MULTIPLE Person ground-truth boxes must have each FN's candidate search
scoped to that SPECIFIC box (by index, not by re-matching on class_name
alone), and a prediction already legitimately claimed by a DIFFERENT GT box
in the same image must be excluded from another box's candidate pool (no
"reusing" one detection as evidence for two different ground-truth
instances -- see `_match_person_boxes_in_sample` and the exclusion logic in
`classify_false_negatives`).

Floors used (all distinct, all documented explicitly per the task spec):
  - MATCH_IOU = 0.5            "counts as a match" (mirrors
                                 benchmark/metrics.py's default scoring IoU;
                                 same value used to compute the official
                                 Person FN count in the first place).
  - SPATIAL_ASSOC_IOU = 0.3    "spatially associated candidate" floor (looser
                                 than MATCH_IOU on purpose, so a near-miss
                                 candidate is still surfaced for diagnosis,
                                 not just exact matches -- mirrors
                                 person_failure_analysis.py's existing
                                 same_location_diff_class convention).
  - DIAG_CONF_FLOOR_C = 0.4    confidence floor for a same-location alias/
                                 subpart class to count as genuine
                                 SEMANTIC_CLASS_CONFUSION -- deliberately the
                                 SAME as the production conf threshold, so
                                 category C means "the model actually would
                                 have surfaced a detection right here, just
                                 under the wrong label" (not "there's a
                                 vanishingly faint hint of a different
                                 class"). Documented explicitly per the task
                                 spec's instruction to state and justify
                                 whichever floor is chosen.
  - CONF_NOISE_FLOOR = 0.05    below this, a raw conf=0.01-capture detection
                                 is treated as noise and ignored entirely for
                                 candidate-pool purposes (every image has
                                 dozens of near-zero-confidence boxes at
                                 conf=0.01; without this floor those boxes
                                 would spuriously "explain" TRUE_DETECTOR_MISS
                                 cases as something else). This is stricter
                                 than the task spec's literal "any
                                 confidence" wording for category A -- an
                                 explicit, documented methodological choice,
                                 not a silent omission.

Run with: uv run python -m benchmark.diagnostics.person_confusion_analysis
Writes benchmark/results/diagnostics/person_confusion_analysis.json
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from benchmark.config import EVAL_MANIFEST_PATH, REPO_ROOT
from benchmark.dataset import load_manifest
from benchmark.diagnostics.human_class_map import (
    CLOTHING_AND_ACCESSORIES,
    HUMAN_LIKE_CLASSES,
    PERSON_SUBPARTS,
    WHOLE_PERSON_ALIASES,
    verify_against_model,
)
from benchmark.metrics import Detection, GroundTruth, greedy_match, iou_xywh

DIAG_DIR = REPO_ROOT / "benchmark" / "results" / "diagnostics"
LOW_CONF_PATH = DIAG_DIR / "low_conf_predictions.jsonl"
BASELINE_PRED_PATH = REPO_ROOT / "benchmark" / "results" / "baseline" / "predictions.jsonl"
OUT_PATH = DIAG_DIR / "person_confusion_analysis.json"

MATCH_IOU = 0.5
SPATIAL_ASSOC_IOU = 0.3
DIAG_CONF_FLOOR_C = 0.4
CONF_NOISE_FLOOR = 0.05
BASELINE_CONF = 0.4
SMALL_OBJECT_AREA_PCT = 2.0  # matches Phase B.5's existing convention

CATEGORIES = (
    "TRUE_DETECTOR_MISS",
    "LOW_CONFIDENCE_PERSON",
    "SEMANTIC_CLASS_CONFUSION",
    "LOCALIZATION_FAILURE",
)  # DUPLICATE_MULTI_LABEL (E) is a secondary flag, not a primary bucket


def _load_jsonl_by_id(path, key_field="sample_id") -> dict:
    out = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            out[d[key_field]] = d
    return out


@dataclass
class Candidate:
    class_name: str
    confidence: float
    bbox: tuple
    iou: float
    is_baseline_prediction: bool  # was this in predictions.jsonl (conf>=0.4)?


@dataclass
class FNRecord:
    sample_id: str
    gt_index: int
    gt_bbox: list
    gt_area_pct: float
    gt_is_small: bool
    gt_is_occluded: bool
    candidates: list = field(default_factory=list)  # list[dict], sorted
    primary_category: str = ""
    secondary_flags: list = field(default_factory=list)
    top_alt_class: str | None = None


def _match_person_boxes_in_sample(person_preds: list, person_gts: list) -> tuple:
    """Run the SAME greedy per-image matching algorithm as
    benchmark/metrics.py (reused directly, not reimplemented) scoped to one
    sample's Person-only predictions/GTs. Returns (claimed_gt_indices,
    claimed_pred_indices) -- the latter used to exclude an already-claimed
    detection from a DIFFERENT (unmatched) GT box's candidate pool."""
    if not person_gts:
        return set(), set()
    dets = [Detection(sample_id="s", class_name="Person", bbox=p["bbox"], confidence=p["confidence"])
            for p in person_preds]
    gts = [GroundTruth(sample_id="s", class_name="Person", bbox=g) for g in person_gts]
    match = greedy_match(dets, gts, MATCH_IOU)
    claimed_gt_indices = {gi for (_sid, gi) in match.matched_gt_ids}
    # recover which detection (by index into `person_preds`, confidence-sorted
    # order) claimed a GT -- rebuild the same sort order greedy_match used.
    order = sorted(range(len(dets)), key=lambda i: dets[i].confidence, reverse=True)
    claimed_pred_indices = set()
    rank_to_orig = {rank: orig_i for rank, orig_i in enumerate(order)}
    matched_ranks = [r for r in range(len(order)) if r not in match.unmatched_detection_indices]
    for r in matched_ranks:
        claimed_pred_indices.add(rank_to_orig[r])
    return claimed_gt_indices, claimed_pred_indices


def _classify_one(gt_bbox: tuple, candidates: list) -> tuple:
    """Priority-order decision tree (see module docstring for floors).
    Returns (primary_category, secondary_flags, top_alt_class)."""
    associated = [c for c in candidates if c.iou >= SPATIAL_ASSOC_IOU and c.confidence >= CONF_NOISE_FLOOR]

    secondary = []
    human_related_names = {c.class_name for c in associated if c.class_name in HUMAN_LIKE_CLASSES}
    if len(human_related_names) >= 2:
        secondary.append("DUPLICATE_MULTI_LABEL")

    # 1. Person-class candidate at match quality (necessarily conf<0.4 --
    #    already-claimed baseline Person predictions were excluded upstream).
    person_match = [c for c in associated if c.class_name == "Person" and c.iou >= MATCH_IOU]
    if person_match:
        assert all(c.confidence < BASELINE_CONF for c in person_match), (
            "invariant violated: an unclaimed Person candidate with IoU>=0.5 and "
            "conf>=0.4 should have been matched by greedy_match already"
        )
        return "LOW_CONFIDENCE_PERSON", secondary, None

    # 2. Alias/subpart human-related candidate at match quality AND at/above
    #    the diagnostic confidence floor -> genuine semantic confusion.
    alias_match = [
        c for c in associated
        if c.class_name in (WHOLE_PERSON_ALIASES | PERSON_SUBPARTS)
        and c.iou >= MATCH_IOU and c.confidence >= DIAG_CONF_FLOOR_C
    ]
    if alias_match:
        top = max(alias_match, key=lambda c: (c.confidence, c.iou))
        return "SEMANTIC_CLASS_CONFUSION", secondary, top.class_name

    # 3. Any human-related candidate (Person included) with IoU in
    #    [SPATIAL_ASSOC_IOU, MATCH_IOU), OR an alias/subpart at match-quality
    #    IoU but below the diagnostic confidence floor (localized, but the
    #    label doesn't clear the confidence bar for genuine confusion) ->
    #    localization failure.
    localization_candidates = [
        c for c in associated
        if c.class_name in HUMAN_LIKE_CLASSES
        and (SPATIAL_ASSOC_IOU <= c.iou < MATCH_IOU or (c.iou >= MATCH_IOU and c.class_name != "Person"))
    ]
    if localization_candidates:
        top = max(localization_candidates, key=lambda c: (c.iou, c.confidence))
        return "LOCALIZATION_FAILURE", secondary, top.class_name

    return "TRUE_DETECTOR_MISS", secondary, None


def classify_false_negatives(manifest_path=EVAL_MANIFEST_PATH) -> list:
    manifest = load_manifest(manifest_path)
    baseline_preds = _load_jsonl_by_id(BASELINE_PRED_PATH)
    low_conf_preds = _load_jsonl_by_id(LOW_CONF_PATH)

    records: list[FNRecord] = []

    for sample in manifest:
        person_gts = [lbl for lbl in sample.labels if lbl.class_name == "Person"]
        if not person_gts:
            continue

        person_baseline_preds = [
            p for p in baseline_preds.get(sample.sample_id, {}).get("predictions", [])
            if p["class_name"] == "Person"
        ]
        gt_bboxes = [g.bbox for g in person_gts]
        claimed_gt_idx, claimed_pred_idx = _match_person_boxes_in_sample(person_baseline_preds, gt_bboxes)

        low_conf_all = low_conf_preds.get(sample.sample_id, {}).get("predictions", [])
        # exclude baseline Person predictions already claimed by a DIFFERENT
        # GT box in this image, so they cannot double as "evidence" for an
        # unrelated missed box (no cross-contamination between multi-instance
        # GTs in the same image).
        claimed_pred_bboxes = {
            tuple(round(v, 6) for v in person_baseline_preds[i]["bbox"]) for i in claimed_pred_idx
        }

        def _candidate_pool_for(gt_bbox):
            pool = []
            for p in low_conf_all:
                key = tuple(round(v, 6) for v in p["bbox"])
                if p["class_name"] == "Person" and key in claimed_pred_bboxes:
                    continue  # already legitimately claimed by a different GT box
                i = iou_xywh(gt_bbox, tuple(p["bbox"]))
                if i <= 0.0:
                    continue
                pool.append(Candidate(
                    class_name=p["class_name"], confidence=p["confidence"], bbox=tuple(p["bbox"]),
                    iou=i, is_baseline_prediction=p["confidence"] >= BASELINE_CONF,
                ))
            return pool

        for gi, gt in enumerate(person_gts):
            if gi in claimed_gt_idx:
                continue  # matched at baseline -- not a false negative
            pool = _candidate_pool_for(gt.bbox)
            associated_sorted = sorted(
                [c for c in pool if c.iou >= SPATIAL_ASSOC_IOU and c.confidence >= CONF_NOISE_FLOOR],
                key=lambda c: (-c.confidence, -c.iou),
            )
            primary, secondary, top_alt = _classify_one(gt.bbox, pool)

            x, y, w, h = gt.bbox
            area_pct = round(w * h * 100.0, 4)
            records.append(FNRecord(
                sample_id=sample.sample_id,
                gt_index=gi,
                gt_bbox=list(gt.bbox),
                gt_area_pct=area_pct,
                gt_is_small=area_pct < SMALL_OBJECT_AREA_PCT,
                gt_is_occluded=gt.is_occluded,
                candidates=[
                    {
                        "class_name": c.class_name, "confidence": round(c.confidence, 4),
                        "bbox": list(c.bbox), "iou": round(c.iou, 4),
                        "above_production_threshold": c.confidence >= BASELINE_CONF,
                    }
                    for c in associated_sorted
                ],
                primary_category=primary,
                secondary_flags=secondary,
                top_alt_class=top_alt,
            ))

    return records


def aggregate(records: list) -> dict:
    n = len(records)
    counts = Counter(r.primary_category for r in records)
    pct = {k: (100.0 * counts.get(k, 0) / n if n else 0.0) for k in CATEGORIES}

    n_duplicate_flag = sum(1 for r in records if "DUPLICATE_MULTI_LABEL" in r.secondary_flags)
    semantic_records = [r for r in records if r.primary_category == "SEMANTIC_CLASS_CONFUSION"]
    semantic_and_duplicate = sum(1 for r in semantic_records if "DUPLICATE_MULTI_LABEL" in r.secondary_flags)

    alt_class_counter = Counter(r.top_alt_class for r in semantic_records if r.top_alt_class)

    small = [r for r in records if r.gt_is_small]
    non_small = [r for r in records if not r.gt_is_small]

    def _breakdown(subset):
        m = len(subset)
        c = Counter(r.primary_category for r in subset)
        return {
            "n": m,
            "counts": dict(c),
            "pct": {k: (100.0 * c.get(k, 0) / m if m else 0.0) for k in CATEGORIES},
        }

    return {
        "total_fn": n,
        "counts": dict(counts),
        "pct": pct,
        "sums_to_100_check": round(sum(pct.values()), 3),
        "duplicate_multi_label_secondary_flag_count": n_duplicate_flag,
        "semantic_class_confusion_count": len(semantic_records),
        "semantic_and_also_duplicate_multi_label": semantic_and_duplicate,
        "alt_class_ranking_for_semantic_confusion": alt_class_counter.most_common(),
        "small_object_subgroup": _breakdown(small),
        "non_small_object_subgroup": _breakdown(non_small),
    }


def main() -> None:
    from benchmark.model import BaselineModel

    model = BaselineModel()
    verification = verify_against_model(model.class_names)
    if not verification["ok"]:
        raise RuntimeError(f"human_class_map.py declares classes not present in the live model: {verification['missing']}")
    print(f"human_class_map verified against live model.names: {verification['num_declared']} classes, all present.")

    records = classify_false_negatives()
    agg = aggregate(records)

    print(f"Total Person FNs (recomputed): {agg['total_fn']}")
    print(f"Primary category breakdown: {agg['counts']}")
    print(f"Percentages (should sum to ~100): {agg['pct']}")
    print(f"Alt-class ranking (SEMANTIC_CLASS_CONFUSION): {agg['alt_class_ranking_for_semantic_confusion']}")

    out = {
        "methodology": {
            "match_iou": MATCH_IOU,
            "spatial_assoc_iou": SPATIAL_ASSOC_IOU,
            "diag_conf_floor_c": DIAG_CONF_FLOOR_C,
            "conf_noise_floor": CONF_NOISE_FLOOR,
            "baseline_conf": BASELINE_CONF,
            "small_object_area_pct_threshold": SMALL_OBJECT_AREA_PCT,
            "source_predictions": "benchmark/results/baseline/predictions.jsonl (official conf=0.4 run RUN-20260904-002)",
            "source_low_conf_capture": "benchmark/results/diagnostics/low_conf_predictions.jsonl (conf=0.01, reused, no new inference)",
            "source_ground_truth": "data/manifests/eval_manifest.jsonl",
        },
        "aggregate": agg,
        "records": [
            {
                "sample_id": r.sample_id, "gt_index": r.gt_index, "gt_bbox": r.gt_bbox,
                "gt_area_pct": r.gt_area_pct, "gt_is_small": r.gt_is_small, "gt_is_occluded": r.gt_is_occluded,
                "primary_category": r.primary_category, "secondary_flags": r.secondary_flags,
                "top_alt_class": r.top_alt_class, "candidates": r.candidates,
            }
            for r in records
        ],
    }
    DIAG_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
    n_bytes = OUT_PATH.stat().st_size
    print(f"Wrote {OUT_PATH} ({n_bytes} bytes, {len(records)} FN records)")


if __name__ == "__main__":
    main()
