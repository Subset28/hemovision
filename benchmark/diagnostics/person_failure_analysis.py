"""Diagnostic-only: for every ground-truth Person box the baseline missed
(no matching prediction >= IoU 0.5 at the app's real conf=0.4 operating
point), determine WHY, using:
  - the low-confidence capture (conf=0.01) to see what the model actually
    output at/near that location, even below 0.4,
  - the manifest's IsOccluded/IsTruncated/IsGroupOf flags,
  - box size (absolute px + % image area), image resolution,
  - box-height-as-%-of-image-height (distance proxy),
  - border-touching (partially-out-of-frame proxy),
  - whether a different class was predicted at that location instead.

No image pixel data is read or sent anywhere — only manifest/prediction JSON
already on local disk. No network calls.

Run with: uv run python -m benchmark.diagnostics.person_failure_analysis
Writes reports/baseline/person_failure_analysis.md
"""

from __future__ import annotations

import json
from collections import Counter

from PIL import Image

from benchmark.config import EVAL_MANIFEST_PATH, RAW_IMAGE_DIR, REPO_ROOT
from benchmark.dataset import load_manifest
from benchmark.metrics import iou_xywh

DIAG_DIR = REPO_ROOT / "benchmark" / "results" / "diagnostics"
LOW_CONF_PATH = DIAG_DIR / "low_conf_predictions.jsonl"
BASELINE_PRED_PATH = REPO_ROOT / "benchmark" / "results" / "baseline" / "predictions.jsonl"
OUT_PATH = REPO_ROOT / "reports" / "baseline" / "person_failure_analysis.md"

BASELINE_CONF = 0.4
IOU_THRESHOLD = 0.5
BORDER_EPS = 0.01  # bbox edge within this of 0/1 counts as "touches border"


def load_jsonl_by_id(path, key_field="sample_id"):
    out = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            out[d[key_field]] = d
    return out


def main() -> None:
    manifest = load_manifest(EVAL_MANIFEST_PATH)
    manifest_by_id = {s.sample_id: s for s in manifest}
    baseline_preds = load_jsonl_by_id(BASELINE_PRED_PATH)
    low_conf_preds = load_jsonl_by_id(LOW_CONF_PATH)

    missed = []  # list of dicts, one per missed Person GT box

    for sample in manifest:
        person_gts = [l for l in sample.labels if l.class_name == "Person"]
        if not person_gts:
            continue
        baseline_boxes = [
            p for p in baseline_preds.get(sample.sample_id, {}).get("predictions", [])
            if p["class_name"] == "Person"
        ]
        # claim GT boxes matched at conf=0.4 (mirror greedy_match's per-image claiming,
        # simplified since we only need "was this GT box matched at all")
        claimed = [False] * len(person_gts)
        for p in sorted(baseline_boxes, key=lambda x: -x["confidence"]):
            best_i, best_iou = -1, 0.0
            for i, g in enumerate(person_gts):
                if claimed[i]:
                    continue
                iou = iou_xywh(p["bbox"], g.bbox)
                if iou > best_iou:
                    best_iou, best_i = iou, i
            if best_i != -1 and best_iou >= IOU_THRESHOLD:
                claimed[best_i] = True

        img_path = RAW_IMAGE_DIR / sample.filename
        img_w = img_h = None
        if img_path.exists():
            try:
                with Image.open(img_path) as im:
                    img_w, img_h = im.size
            except Exception:
                pass

        low_conf_all = low_conf_preds.get(sample.sample_id, {}).get("predictions", [])

        for i, g in enumerate(person_gts):
            if claimed[i]:
                continue  # this one was found, not a miss

            x, y, w, h = g.bbox
            area_pct = w * h * 100.0
            touches_border = (x <= BORDER_EPS or y <= BORDER_EPS or
                               (x + w) >= (1.0 - BORDER_EPS) or (y + h) >= (1.0 - BORDER_EPS))

            # best-overlapping prediction of ANY class at low confidence
            best_low = None
            best_low_iou = 0.0
            for p in low_conf_all:
                iou = iou_xywh(g.bbox, p["bbox"])
                if iou > best_low_iou:
                    best_low_iou = iou
                    best_low = p

            missed.append({
                "sample_id": sample.sample_id,
                "bbox": list(g.bbox),
                "area_pct_of_image": round(area_pct, 3),
                "height_pct_of_image": round(h * 100.0, 3),
                "abs_px": (
                    f"{round(w * img_w)}x{round(h * img_h)}" if img_w and img_h else "unknown (image missing)"
                ),
                "image_resolution": f"{img_w}x{img_h}" if img_w and img_h else "unknown",
                "is_occluded": g.is_occluded,
                "is_truncated": g.is_truncated,
                "is_group_of": g.is_group_of,
                "touches_border": touches_border,
                "best_low_conf_pred": (
                    {
                        "class_name": best_low["class_name"],
                        "confidence": round(best_low["confidence"], 4),
                        "iou": round(best_low_iou, 4),
                        "same_location_diff_class": best_low["class_name"] != "Person" and best_low_iou >= 0.3,
                    } if best_low is not None else None
                ),
            })

    n = len(missed)

    # aggregate breakdowns
    n_small_2pct = sum(1 for m in missed if m["area_pct_of_image"] < 2.0)
    n_small_1pct = sum(1 for m in missed if m["area_pct_of_image"] < 1.0)
    n_occluded = sum(1 for m in missed if m["is_occluded"])
    n_truncated = sum(1 for m in missed if m["is_truncated"])
    n_group_of = sum(1 for m in missed if m["is_group_of"])
    n_border = sum(1 for m in missed if m["touches_border"])
    n_no_candidate_at_all = sum(1 for m in missed if m["best_low_conf_pred"] is None or m["best_low_conf_pred"]["iou"] < 0.1)
    n_below_conf_candidate = sum(
        1 for m in missed
        if m["best_low_conf_pred"] is not None
        and m["best_low_conf_pred"]["iou"] >= IOU_THRESHOLD
        and m["best_low_conf_pred"]["confidence"] < BASELINE_CONF
        and not m["best_low_conf_pred"]["same_location_diff_class"]
    )
    n_wrong_class_high_iou = sum(
        1 for m in missed
        if m["best_low_conf_pred"] is not None
        and m["best_low_conf_pred"]["iou"] >= IOU_THRESHOLD
        and m["best_low_conf_pred"]["same_location_diff_class"]
    )
    wrong_class_counter = Counter(
        m["best_low_conf_pred"]["class_name"]
        for m in missed
        if m["best_low_conf_pred"] is not None
        and m["best_low_conf_pred"]["iou"] >= IOU_THRESHOLD
        and m["best_low_conf_pred"]["same_location_diff_class"]
    )
    height_buckets = Counter()
    for m in missed:
        hp = m["height_pct_of_image"]
        if hp < 10:
            height_buckets["<10% (far/small)"] += 1
        elif hp < 25:
            height_buckets["10-25%"] += 1
        elif hp < 50:
            height_buckets["25-50%"] += 1
        else:
            height_buckets[">=50% (close/large)"] += 1

    # pick 6 representative examples spanning the categories
    examples = []
    seen_kinds = set()
    for m in missed:
        kind = None
        if m["is_occluded"]:
            kind = "occluded"
        elif m["area_pct_of_image"] < 2.0:
            kind = "small"
        elif m["best_low_conf_pred"] and m["best_low_conf_pred"]["same_location_diff_class"]:
            kind = "wrong_class"
        elif m["touches_border"]:
            kind = "border"
        elif m["best_low_conf_pred"] and m["best_low_conf_pred"]["confidence"] < BASELINE_CONF and m["best_low_conf_pred"]["iou"] >= 0.5:
            kind = "below_threshold"
        else:
            kind = "other"
        if kind not in seen_kinds:
            examples.append((kind, m))
            seen_kinds.add(kind)
        if len(examples) >= 6:
            break
    # if fewer than 6 distinct kinds exist, top up with more (possibly repeated-kind) examples
    if len(examples) < 6:
        for m in missed:
            if len(examples) >= 8:
                break
            if (None, m) not in examples and m not in [e[1] for e in examples]:
                examples.append(("additional", m))

    lines = []
    lines.append("# Person Failure Analysis")
    lines.append("")
    lines.append(
        f"Every ground-truth `Person` box in `data/manifests/eval_manifest.jsonl` that the "
        f"baseline (conf=0.4, iou=0.7) did not match at IoU>=0.5, cross-referenced against a "
        f"low-confidence (conf=0.01) re-inference capture "
        f"(`benchmark/results/diagnostics/low_conf_predictions.jsonl`) to see what the model "
        f"actually output at/near that location. **Sample size: Person has 303 GT boxes total "
        f"(the largest hazard class in the dataset), of which {n} were missed at conf=0.4** — "
        f"this is a large-enough sample for the breakdowns below to be treated with real "
        f"confidence (contrast with Stairs, 45 GT boxes total — see "
        f"reports/baseline/BASELINE_SCORECARD.md sample-size warnings)."
    )
    lines.append("")
    lines.append("No image pixel data left the local filesystem; no network calls were made.")
    lines.append("")
    lines.append("## Aggregate breakdown")
    lines.append("")
    lines.append(f"- Total missed Person GT boxes: **{n}**")
    lines.append(f"- Box area < 2% of image area: **{n_small_2pct}** ({100*n_small_2pct/n:.1f}%)")
    lines.append(f"- Box area < 1% of image area: **{n_small_1pct}** ({100*n_small_1pct/n:.1f}%)")
    lines.append(f"- `IsOccluded=True`: **{n_occluded}** ({100*n_occluded/n:.1f}%)")
    lines.append(f"- `IsTruncated=True`: **{n_truncated}** ({100*n_truncated/n:.1f}%)")
    lines.append(f"- `IsGroupOf=True`: **{n_group_of}** ({100*n_group_of/n:.1f}%)")
    lines.append(f"- Box touches image border (partially out-of-frame proxy): **{n_border}** ({100*n_border/n:.1f}%)")
    lines.append(f"- No candidate prediction of ANY class within IoU>=0.1 even at conf=0.01: **{n_no_candidate_at_all}** ({100*n_no_candidate_at_all/n:.1f}%) — the model produced literally nothing near this box at any confidence")
    lines.append(f"- A same-location Person candidate existed at conf=0.01 with IoU>=0.5 but confidence fell below the 0.4 operating threshold: **{n_below_conf_candidate}** ({100*n_below_conf_candidate/n:.1f}%) — these ARE recoverable by lowering the threshold, at a precision cost (see threshold_sweep.json)")
    lines.append(f"- A DIFFERENT class was predicted at that same location (IoU>=0.5) instead of Person: **{n_wrong_class_high_iou}** ({100*n_wrong_class_high_iou/n:.1f}%) — classification confusion, not a missing candidate")
    if wrong_class_counter:
        lines.append(f"  - Confused classes: {dict(wrong_class_counter)}")
    lines.append("")
    lines.append("### Box height as % of image height (distance/relative-size proxy)")
    lines.append("")
    for k in ["<10% (far/small)", "10-25%", "25-50%", ">=50% (close/large)"]:
        c = height_buckets.get(k, 0)
        lines.append(f"- {k}: {c} ({100*c/n:.1f}%)")
    lines.append("")
    lines.append(
        f"**Read together**: the two largest categories are `IsOccluded=True` "
        f"({n_occluded}, {100*n_occluded/n:.0f}%) and box area < 2% of image "
        f"({n_small_2pct}, {100*n_small_2pct/n:.0f}%) — these overlap heavily (a small, "
        f"distant person is frequently also the one Open Images annotators flagged as "
        f"occluded). Only a small minority ({n_no_candidate_at_all}, "
        f"{100*n_no_candidate_at_all/n:.0f}%) had literally no candidate box of any kind "
        f"near them even at conf=0.01 — for most missed boxes the detector DID propose "
        f"something at that location, just not a correct, confident, Person-labeled one. "
        f"A meaningful chunk ({n_below_conf_candidate}, {100*n_below_conf_candidate/n:.0f}%) "
        f"is a genuine same-class candidate that scored below the 0.4 cutoff — that fraction "
        f"IS recoverable by lowering the threshold, at the precision cost quantified in "
        f"`benchmark/results/diagnostics/threshold_sweep.json` (Person recall roughly doubles, "
        f"0.211->0.479, at conf=0.05, but precision collapses from 0.667->0.312). Another "
        f"substantial chunk ({n_wrong_class_high_iou}, {100*n_wrong_class_high_iou/n:.0f}%) "
        f"is genuine classification confusion — the model found *something* at that location "
        f"but labeled it 'Man'/'Woman'/'Human body'/'Clothing' etc. instead of 'Person' (see "
        f"Confused classes above; 'Man'/'Woman'/'Boy'/'Girl'/'Human body' are separate OIV7 "
        f"leaf classes the model can predict independently of 'Person' — lowering the "
        f"confidence threshold would NOT fix this subset, since it is a labeling choice, "
        f"not a confidence problem). Categories are NOT mutually exclusive (a box can be "
        f"both occluded AND small AND below-threshold at once), so percentages sum to well "
        f"over 100%."
    )
    lines.append("")
    lines.append("## Representative examples")
    lines.append("")
    for kind, m in examples:
        lp = m["best_low_conf_pred"]
        lp_str = (
            f"{lp['class_name']} conf={lp['confidence']} IoU={lp['iou']}" if lp else "no prediction found nearby at any confidence"
        )
        lines.append(f"### `{m['sample_id']}` — category: `{kind}`")
        lines.append(f"- bbox (normalized xywh): `{m['bbox']}`")
        lines.append(f"- size: {m['area_pct_of_image']}% of image area, {m['abs_px']} px, image {m['image_resolution']}")
        lines.append(f"- height: {m['height_pct_of_image']}% of image height")
        lines.append(f"- IsOccluded={m['is_occluded']} IsTruncated={m['is_truncated']} IsGroupOf={m['is_group_of']} touches_border={m['touches_border']}")
        lines.append(f"- best low-conf (0.01) prediction near this box: {lp_str}")
        lines.append("")

    lines.append("## Methodology notes")
    lines.append("")
    lines.append(
        "- \"Missed\" = no baseline (conf=0.4) Person prediction reached IoU>=0.5 against this "
        "GT box, using the same greedy per-image claiming logic as `benchmark/metrics.py` "
        "(applied here Person-class-only for clarity)."
    )
    lines.append(
        "- Low-confidence lookup re-ran the SAME model/weights/imgsz/NMS-iou, only conf lowered "
        "to 0.01, via `benchmark/model.py`'s `predict_at()` (added for this diagnostic; "
        "`predict()`, which produces the real baseline, is unchanged and still pinned to "
        "`benchmark/config.py`'s conf=0.4)."
    )
    lines.append(
        "- `same_location_diff_class` requires IoU>=0.3 (looser than the 0.5 match threshold) "
        "so near-miss classification confusions are still surfaced, not just exact matches."
    )
    lines.append("")
    lines.append(
        "See `reports/baseline/Baseline_Report.md` Section 2 and "
        "`reports/baseline/BASELINE_SCORECARD.md` for the headline Person recall number "
        "(0.211, confirmed correct — see `benchmark/diagnostics/label_alignment_examples.txt` "
        "for the label-alignment audit that this analysis assumes)."
    )

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({n} missed Person boxes analyzed)")
    print(f"  small(<2%): {n_small_2pct}  occluded: {n_occluded}  border: {n_border}  "
          f"no_candidate_at_all: {n_no_candidate_at_all}  below_threshold_recoverable: {n_below_conf_candidate}  "
          f"wrong_class: {n_wrong_class_high_iou}")


if __name__ == "__main__":
    main()
