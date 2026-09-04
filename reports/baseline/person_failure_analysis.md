# Person Failure Analysis

Every ground-truth `Person` box in `data/manifests/eval_manifest.jsonl` that the baseline (conf=0.4, iou=0.7) did not match at IoU>=0.5, cross-referenced against a low-confidence (conf=0.01) re-inference capture (`benchmark/results/diagnostics/low_conf_predictions.jsonl`) to see what the model actually output at/near that location. **Sample size: Person has 303 GT boxes total (the largest hazard class in the dataset), of which 239 were missed at conf=0.4** — this is a large-enough sample for the breakdowns below to be treated with real confidence (contrast with Stairs, 45 GT boxes total — see reports/baseline/BASELINE_SCORECARD.md sample-size warnings).

No image pixel data left the local filesystem; no network calls were made.

## Aggregate breakdown

- Total missed Person GT boxes: **239**
- Box area < 2% of image area: **153** (64.0%)
- Box area < 1% of image area: **128** (53.6%)
- `IsOccluded=True`: **156** (65.3%)
- `IsTruncated=True`: **46** (19.2%)
- `IsGroupOf=True`: **38** (15.9%)
- Box touches image border (partially out-of-frame proxy): **71** (29.7%)
- No candidate prediction of ANY class within IoU>=0.1 even at conf=0.01: **15** (6.3%) — the model produced literally nothing near this box at any confidence
- A same-location Person candidate existed at conf=0.01 with IoU>=0.5 but confidence fell below the 0.4 operating threshold: **100** (41.8%) — these ARE recoverable by lowering the threshold, at a precision cost (see threshold_sweep.json)
- A DIFFERENT class was predicted at that same location (IoU>=0.5) instead of Person: **84** (35.1%) — classification confusion, not a missing candidate
  - Confused classes: {'Human body': 11, 'Cat': 1, 'Man': 41, 'Clothing': 11, 'Book': 1, 'Tree': 1, 'Car': 4, 'Human leg': 1, 'Jeans': 2, 'Woman': 6, 'Bus': 1, 'Window': 1, 'Tent': 1, 'Boy': 1, 'Office building': 1}

### Box height as % of image height (distance/relative-size proxy)

- <10% (far/small): 84 (35.1%)
- 10-25%: 75 (31.4%)
- 25-50%: 42 (17.6%)
- >=50% (close/large): 38 (15.9%)

**Read together**: the two largest categories are `IsOccluded=True` (156, 65%) and box area < 2% of image (153, 64%) — these overlap heavily (a small, distant person is frequently also the one Open Images annotators flagged as occluded). Only a small minority (15, 6%) had literally no candidate box of any kind near them even at conf=0.01 — for most missed boxes the detector DID propose something at that location, just not a correct, confident, Person-labeled one. A meaningful chunk (100, 42%) is a genuine same-class candidate that scored below the 0.4 cutoff — that fraction IS recoverable by lowering the threshold, at the precision cost quantified in `benchmark/results/diagnostics/threshold_sweep.json` (Person recall roughly doubles, 0.211->0.479, at conf=0.05, but precision collapses from 0.667->0.312). Another substantial chunk (84, 35%) is genuine classification confusion — the model found *something* at that location but labeled it 'Man'/'Woman'/'Human body'/'Clothing' etc. instead of 'Person' (see Confused classes above; 'Man'/'Woman'/'Boy'/'Girl'/'Human body' are separate OIV7 leaf classes the model can predict independently of 'Person' — lowering the confidence threshold would NOT fix this subset, since it is a labeling choice, not a confidence problem). Categories are NOT mutually exclusive (a box can be both occluded AND small AND below-threshold at once), so percentages sum to well over 100%.

## Representative examples

### `oiv7-5a6f76adceec9d57` — category: `wrong_class`
- bbox (normalized xywh): `[0.09264706, 0.14855877, 0.2, 0.53436806]`
- size: 10.687% of image area, 205x363 px, image 1024x680
- height: 53.437% of image height
- IsOccluded=False IsTruncated=False IsGroupOf=False touches_border=False
- best low-conf (0.01) prediction near this box: Human body conf=0.0101 IoU=0.8385

### `oiv7-aef199d66371e318` — category: `occluded`
- bbox (normalized xywh): `[0.0, 0.17477876, 1.0, 0.30088496]`
- size: 30.088% of image area, 1024x205 px, image 1024x681
- height: 30.088% of image height
- IsOccluded=True IsTruncated=True IsGroupOf=False touches_border=True
- best low-conf (0.01) prediction near this box: Car conf=0.024 IoU=0.3998

### `oiv7-591eff0709a14d1c` — category: `other`
- bbox (normalized xywh): `[0.40707964, 0.27687776, 0.24557526000000002, 0.24889541000000004]`
- size: 6.112% of image area, 167x255 px, image 682x1024
- height: 24.89% of image height
- IsOccluded=False IsTruncated=True IsGroupOf=False touches_border=False
- best low-conf (0.01) prediction near this box: Person conf=0.4803 IoU=0.6498

### `oiv7-c0dea6f5a9da743e` — category: `border`
- bbox (normalized xywh): `[0.396875, 0.35208333, 0.24843749999999998, 0.64791667]`
- size: 16.097% of image area, 254x498 px, image 1024x768
- height: 64.792% of image height
- IsOccluded=False IsTruncated=False IsGroupOf=False touches_border=True
- best low-conf (0.01) prediction near this box: Person conf=0.3873 IoU=0.9545

### `oiv7-86cf240adb1303b2` — category: `small`
- bbox (normalized xywh): `[0.6921875, 0.20208333, 0.05625000000000002, 0.17708332999999998]`
- size: 0.996% of image area, 58x136 px, image 1024x768
- height: 17.708% of image height
- IsOccluded=False IsTruncated=False IsGroupOf=False touches_border=False
- best low-conf (0.01) prediction near this box: Person conf=0.3107 IoU=0.9176

### `oiv7-6e9dcdbee43b0346` — category: `below_threshold`
- bbox (normalized xywh): `[0.553125, 0.51875, 0.27812500000000007, 0.1812499999999999]`
- size: 5.041% of image area, 285x139 px, image 1024x768
- height: 18.125% of image height
- IsOccluded=False IsTruncated=True IsGroupOf=False touches_border=False
- best low-conf (0.01) prediction near this box: Person conf=0.0791 IoU=0.9343

## Methodology notes

- "Missed" = no baseline (conf=0.4) Person prediction reached IoU>=0.5 against this GT box, using the same greedy per-image claiming logic as `benchmark/metrics.py` (applied here Person-class-only for clarity).
- Low-confidence lookup re-ran the SAME model/weights/imgsz/NMS-iou, only conf lowered to 0.01, via `benchmark/model.py`'s `predict_at()` (added for this diagnostic; `predict()`, which produces the real baseline, is unchanged and still pinned to `benchmark/config.py`'s conf=0.4).
- `same_location_diff_class` requires IoU>=0.3 (looser than the 0.5 match threshold) so near-miss classification confusions are still surfaced, not just exact matches.

See `reports/baseline/Baseline_Report.md` Section 2 and `reports/baseline/BASELINE_SCORECARD.md` for the headline Person recall number (0.211, confirmed correct — see `benchmark/diagnostics/label_alignment_examples.txt` for the label-alignment audit that this analysis assumes).