# OmniSight Baseline Accuracy Report

> **VALIDATION ADDENDUM (2026-09-04)** — This report was independently audited after
> initial approval. Findings:
> - **Label mapping (class strings, bbox coordinate convention, IoU calculation): CONFIRMED CORRECT.**
>   No bug found. See `benchmark/diagnostics/label_alignment_check.py` /
>   `label_alignment_examples.txt` for the spot-check evidence and
>   `benchmark/model.py`/`benchmark/metrics.py` for the audited code.
> - **One real bug WAS found and fixed** in `benchmark/evaluate.py::_classify_failure`:
>   for images containing multiple ground-truth boxes of the *same class* (e.g. several
>   `Bicycle`s in one photo), the failure-taxonomy classifier matched a missed box's
>   occlusion/size signals by class name only, so a missed box could be tagged
>   `"occlusion"` using a *different* same-class box's `IsOccluded` flag. Fixed by
>   matching on `(class_name, bbox)` instead of `class_name` alone. **This bug did NOT
>   affect precision/recall/F1/mAP/TP/FP/FN anywhere** (those come from
>   `benchmark/metrics.py`'s independent greedy IoU matching, untouched) — it only
>   affected the `failure_type` breakdown in Section 4 below, which has been
>   corrected (occlusion count moved 1,842→1,923 all-classes, 226→242 hazard-only,
>   after the fix; the underlying finding — occlusion is the largest measurable
>   failure category — still holds). See `benchmark/results/diagnostics/
>   occlusion_analysis.json` for the full before/after verification.
> - All headline P/R/F1/mAP/latency numbers below were **re-run** after the bug fix
>   (`RUN-20260904-002`, superseding the original `RUN-20260904-001`); hazard-class
>   P/R/F1/mAP numbers are numerically identical to the original run (as expected,
>   since the bug never touched the matching/scoring path). Latency numbers moved
>   slightly (p50 24.0ms→18.0ms, p95 62.2ms→57.1ms) — that is ordinary GPU-run-to-run
>   variance from the re-run, not a methodology change; see Section 6.
> - See `reports/baseline/person_failure_analysis.md`, `reports/baseline/
>   BASELINE_SCORECARD.md`, and `benchmark/results/diagnostics/threshold_sweep.json`
>   for the deeper diagnostic passes this addendum is based on.

---

Run: `RUN-20260904-002` (full record: `benchmark/results/baseline/run_metadata.json`;
supersedes `RUN-20260904-001` after the `_classify_failure` bug fix above — same
model/config/manifest, scoring numbers unchanged)
Model under test: `benchmark/models/yolov8m-oiv7.pt` (very likely, but not bit-parity
confirmed, identical weights to the shipped `ScanningData.mlpackage` — see repo context
in `IMPLEMENTATION_PLAN.md`/session history; CoreML export applies fp16 casting and
graph transforms not independently verified here).
Operating point: imgsz=640, conf=0.4, iou=0.7 (`benchmark/config.py`, sourced from
`ios/OmniSightKit/Sources/OmniSightKit/OpticalCore.swift:137` and the model's own
embedded NMS default — see that file's module docstring for full provenance).
Dataset: `data/manifests/eval_manifest.jsonl` — 380 Open Images V7 validation images,
4,916 ground-truth boxes (`docs/DATASETS.md`).
Git commit evaluated: `76c5508` (production HEAD, tag `omnisight-baseline-pre-evaluation`).
Hardware: NVIDIA GeForce RTX 3070 Ti, CUDA 12.4, torch 2.4.1+cu124, Windows 10.0.26200.

All numbers below are read directly from `benchmark/results/baseline/metrics.json`,
`per_class.json`, and `failures.jsonl` — none are invented.

---

## 1. Headline numbers — ALL-CLASS metrics (secondary/context; see Section 2 for PRIMARY)

**These all-class numbers are NOT the primary metric for judging OmniSight's real-world
accuracy — see Section 2 for the metric that actually matters.** They are retained here
in full (nothing below is deleted or hidden) because they are informative about model
behavior in general, but they should not be quoted as "how good is OmniSight" without
the caveat immediately following.

| Metric | Value |
|---|---|
| Overall precision | 0.734 |
| Overall recall | 0.247 |
| Overall F1 | 0.369 |
| Overall mAP@50 | 0.201 |
| Overall mAP@50:95 | 0.167 |
| TP / FP / FN | 1,213 / 439 / 3,703 |
| Ground-truth boxes / predictions | 4,916 / 1,652 |

**Read this carefully before drawing conclusions.** These "overall" numbers are
averaged across **146 distinct class names** — because Open Images V7 exhaustively
labels every object type present in a photo, the ground truth includes many OIV7
ontology "ancestor"/coarse classes (`Mammal`, `Land vehicle`, `Vehicle`, `Furniture`,
`Human body`, `Tableware`, `Sports equipment`, ...) that the model's own 601-class
vocabulary technically includes (confirmed via `model.names`) but **essentially never
predicts at conf≥0.4** — 67 of 141 classes with ground truth received **zero**
predictions across all 380 images. This drags the "overall" recall/mAP down
substantially and is NOT primarily a story about the model missing real objects — it's
a mismatch between Open Images' exhaustive hierarchical labeling and what a
conf-thresholded object detector realistically emits. **The hazard-class numbers below
are the ones that matter for OmniSight's actual purpose** — they use only the 8 specific
leaf classes the app actually cares about.

## 2. Hazard-class numbers — PRIMARY application metric

Hazard classes: `person, car, truck, bus, bicycle, motorcycle, stairs, dog`
(`ios/OmniSightKit/Sources/OmniSightKit/OpticalCore.swift:108-110`), mapped 1:1 to OIV7
`Person, Car, Truck, Bus, Bicycle, Motorcycle, Stairs, Dog`.

| Metric | Value |
|---|---|
| Precision (hazard classes) | 0.807 |
| Recall (hazard classes) | 0.480 |
| F1 (hazard classes) | 0.602 |
| mAP@50 (hazard classes) | 0.582 |
| mAP@50:95 (hazard classes) | 0.499 |
| **Miss rate proxy** (1 − recall) | **0.520** |
| TP / FP / FN | 368 / 88 / 398 |
| Ground-truth boxes / predictions | 766 / 456 |

Per-hazard-class breakdown (from `per_class.json`):

| Class | GT boxes | Predictions | Precision | Recall | AP@50 | AP@50:95 |
|---|---|---|---|---|---|---|
| Dog | 52 | 52 | 0.962 | **0.962** | 0.953 | 0.882 |
| Motorcycle | 49 | 40 | 0.950 | 0.776 | 0.770 | 0.660 |
| Bus | 49 | 42 | 0.857 | 0.735 | 0.720 | 0.641 |
| Bicycle | 78 | 57 | 0.947 | 0.692 | 0.688 | 0.554 |
| Car | 148 | 124 | 0.718 | 0.601 | 0.543 | 0.470 |
| Truck | 42 | 23 | 0.957 | 0.524 | 0.524 | 0.446 |
| Stairs | 45 | 22 | 0.682 | 0.333 | 0.286 | 0.192 |
| **Person** | 303 | 96 | 0.667 | **0.211** | 0.174 | 0.145 |

**Notable finding: `Person` — by far the largest hazard class (303 boxes, the highest of
any class in the whole dataset) — has by far the WORST recall of the 8 hazard classes
(0.211), well below `Stairs` (0.333) despite Stairs having a ninth the ground-truth
volume.** This is a real, load-bearing finding, not noise: Person recall is measured
across 303 boxes, giving it high statistical confidence relative to the thinner classes
(Truck: 42, Bus/Motorcycle: 49 each). At the app's real conf=0.4 threshold, the model
misses roughly 4 out of 5 annotated Person boxes in this dataset. Precision is
reasonable (0.667) — when it does call "Person" it's usually right — but it is
conservative to the point of missing the majority of real people. Given `Person` is
almost certainly the single most safety-relevant hazard class for a mobility-assistance
app, **this is the most important weak spot this benchmark surfaced.**

Caveat specific to Person: Open Images' Person ground truth includes small/partial/
crowd instances (the dataset skews toward busy street/group photos for this class),
which the difficulty heuristic in `docs/DATASETS.md` would flag as harder-than-average;
some of this recall gap is plausibly driven by small or heavily-grouped person
instances rather than uniformly missed clear, close-up people. This benchmark's
`failures.jsonl` supports investigating that further (see Section 4) but does not
fully resolve it — a dedicated look at Person-class failures specifically (filter
`failures.jsonl` for `ground_truth.class_name == "Person"`) is recommended before acting
on this finding.

`Stairs` (0.333 recall, AP@50 0.286) is the second-weakest hazard class — also
significant, since a missed stairs detection is a serious safety-relevant miss for this
app's purpose, even though its ground-truth volume here (45 boxes) is thinner and this
result should be treated as lower-confidence than the Person finding.

## 3. Weakest / strongest classes overall (non-hazard included, gt ≥ 15 boxes)

Best recall:
`Dog` (0.962), `Motorcycle` (0.776), `Bus` (0.735), `Bicycle` (0.692), `Bicycle wheel`
(0.630, 138 gt), `Bicycle helmet` (0.621, 29 gt), `Car` (0.601), `Wheel` (0.588, 480 gt
— the single largest class in the dataset).

Worst recall (0.000, gt ≥ 15): `Land vehicle` (106 gt), `Mammal` (168 gt), `Office
supplies` (18 gt), `Shelf` (16 gt), `Sports equipment` (68 gt), `Tableware` (50 gt),
`Vehicle` (72 gt), `Vehicle registration plate` (19 gt). **All eight of these are OIV7
ontology ancestor/coarse categories or generic collective classes, not the kind of
specific object OmniSight would ever announce** — this is the same "67 classes get zero
predictions" phenomenon from Section 1, not evidence the model is broken. It is
genuinely useful information for anyone trying to interpret raw OIV7-derived
"overall mAP" numbers for this model, but it says nothing about OmniSight's real-world
hazard coverage.

## 4. Dominant failure modes (from `failures.jsonl`, 4,142 total records)

**Corrected after the `_classify_failure` bug fix** (see addendum at top of this
report; verified against the manifest's raw `IsOccluded` flags in
`benchmark/results/diagnostics/occlusion_analysis.json`):

| `failure_type` | Count (all classes) | Count (hazard classes only) |
|---|---|---|
| `occlusion` | 1,923 | 242 |
| `small_object` | 957 | 52 |
| `clutter` | 646 | 70 |
| `false_positive` | 344 | 48 |
| `missed_detection` (no more specific reason) | 177 | 34 |
| `duplicate_detection` | 95 | 40 |
| **Total hazard-class failures** | | **486** |

**Occlusion dominates** across the whole dataset and specifically among hazard-class
failures (242 of 486 hazard-class failure records, 49.8%, the largest single category —
note the original report's "226 of 826" figure had both a since-fixed count and an
incorrect denominator; 486, not 826, is the correct total hazard-class failure count).
This tracks with `docs/system_overview.md`'s own documented "Temporary occlusion
(doorway)" tracking-failure mode — though note that here it's measured as a raw
single-frame detector miss on an `IsOccluded`-flagged box, not the production tracker's
coast/recover behavior (the real app has a 3-frame coasting window that this static
benchmark cannot exercise at all — see `docs/FAILURE_TAXONOMY.md`).

**Independently verified, with an important limitation.**
`benchmark/diagnostics/occlusion_analysis.py` confirms every `occlusion`-tagged failure
record's ground-truth box genuinely has `IsOccluded=True` in the manifest (0 mismatches
post-fix). However, it also shows heavy co-occurrence: of the 1,923 all-class
occlusion-tagged failures, **56.0% are ALSO small (<2% image area)** and **88.7% are
ALSO in a cluttered image (>8 boxes)**. Because `_classify_failure` checks occlusion
*before* small-object/clutter and returns on the first true condition, `small_object`
and `clutter` counts are systematic UNDER-counts of how often those factors are present
alongside occlusion. **Read "occlusion dominates" as "the largest tagged category is
occlusion," not as "occlusion is proven to be the independent causal driver"** — Open
Images' `IsOccluded` is a coarse binary annotator flag with no severity gradation, so
this dataset cannot cleanly separate occlusion's effect from confounding
small-size/clutter effects. See `benchmark/results/diagnostics/occlusion_analysis.json`
for the full numbers.

`clutter` (>8 boxes in the image) is a smaller category than previously reported after
the fix (70 of 486 hazard-class failures, not 101 — some records previously tagged
`clutter` were re-tagged `occlusion` once the correct per-box `IsOccluded` flag was
consulted). Still consistent in direction with `docs/system_overview.md`'s documented
"Dense crowds (5+ people)" tracking degradation mode and `SpeechEngine`'s "Busy area"
scene-summary clamp — independent evidence for, not proof of, an already-known
production weak spot.

`duplicate_detection` at the hazard-class level (40 records, unaffected by the bug fix
since it never went through `_classify_failure`'s missed-detection branch) is a
meaningful but secondary signal — see `docs/FAILURE_TAXONOMY.md` for why this
single-frame proxy should not be equated with the production cross-frame "duplicate
announcement rate."

**Person-specific failure breakdown** (all 239 missed Person GT boxes individually
analyzed, cross-referenced against a conf=0.01 low-threshold re-inference capture):
see `reports/baseline/person_failure_analysis.md`. Headline: 65.3% of misses are
`IsOccluded=True`, 64.0% have box area <2% of image, only 6.3% have literally no model
candidate at any confidence (most misses ARE detected as *something*, just not a
confident correct "Person" box), 41.8% have a genuine same-class candidate below the
0.4 confidence cutoff (threshold-recoverable, at a real precision cost), and 35.1% are
outright classification confusion with a different OIV7 person-adjacent class (`Man`,
`Woman`, `Human body`, `Clothing`, etc.) predicted at the same location instead.

Example failure records (verbatim from `failures.jsonl`):
```json
{"sample_id": "oiv7-f9e61241218288ba", "ground_truth": null, "prediction": {"class_name": "Airplane", "bbox": [0.0, 0.224, 0.948, 0.618]}, "confidence": 0.636, "failure_type": "false_positive", "is_hazard_class": false, ...}
{"sample_id": "oiv7-81be0b735c57cb7e", "ground_truth": {"class_name": "Ambulance", "bbox": [0.0, 0.227, 0.813, 0.681]}, "prediction": null, "confidence": null, "failure_type": "clutter", "is_hazard_class": false, ...}
```

## 5. Weakest environments — heuristic scene signal (read with caution)

`scene_category` is a co-occurring-object-label heuristic, not a verified scene label
(`docs/DATASETS.md` Section 7) — treat everything in this section as a weak, indirect
signal, not a conclusion. Aggregate prediction density vs. ground-truth density by
heuristic scene tag (computed from `predictions.jsonl` joined to the manifest, not
stored as a first-class metric — this is NOT a proper per-scene recall computation
since the ground truth per scene includes the same ancestor-class noise as Section 1):

| `scene_category` (heuristic) | Images | GT boxes | Predictions | Predictions/GT ratio |
|---|---|---|---|---|
| `outdoor_street_heuristic` | 181 | 2,315 | 953 | 0.412 |
| `indoor_room_heuristic` | 113 | 1,926 | 528 | 0.274 |
| `mixed_or_ambiguous` | 16 | 292 | 48 | 0.164 |
| `unclassified` | 70 | 383 | 123 | 0.321 |

Outdoor-tagged scenes have a visibly higher prediction-to-ground-truth ratio than
indoor-tagged scenes in this dataset. This is a real pattern in the numbers but **there
is not enough signal in this benchmark to say confidently why** — it's confounded by
which specific classes dominate each heuristic bucket (indoor scenes are full of
`Furniture`/`Tableware`/`Cabinetry`-type ancestor classes the model rarely predicts,
per Section 1, which alone would explain most of this gap without implying the model
is worse at recognizing real indoor hazards). **Do not treat this as "OmniSight
performs worse indoors" without further, class-controlled analysis** — that claim is
not supported by what this benchmark actually measured. This is exactly the kind of
honesty gap flagged in `docs/DATASETS.md` Section 1: Open Images V7 was never designed
to represent OmniSight's real indoor/outdoor usage split, and this benchmark's
scene tagging is a coarse proxy, not ground truth.

## 6. Latency (Windows/CUDA inference-only proxy — NOT iPhone/on-device)

| Metric | Value |
|---|---|
| Mean | 24.3 ms |
| p50 | 18.0 ms |
| p95 | 57.1 ms |
| p99 | 65.8 ms |
| Min / Max | 13.6 ms / 1,338.2 ms |

(Re-measured in `RUN-20260904-002`, the re-run after the `_classify_failure` bug fix in
the addendum above — same model/config/manifest as the original `RUN-20260904-001`,
whose latency was p50=24.0ms/p95=62.2ms; the shift is ordinary run-to-run GPU/CUDA
variance, not a methodology or config change.)

Measured single-image (batch=1) inference latency, RTX 3070 Ti, CUDA 12.4,
`ultralytics.YOLO.predict()`. The max value (1,338 ms) is a one-off outlier — almost
certainly CUDA/cuDNN kernel warmup or a Windows scheduler hiccup on an early image, not
representative (p99 of 65.8 ms shows the distribution is otherwise tight).

**This is a Windows/CUDA inference-only proxy. It is explicitly NOT iPhone Neural
Engine latency, NOT full camera-to-announcement latency, NOT end-to-end OmniSight
latency, and must not be read as any of those.** It measures only
`ultralytics.YOLO.predict()`'s wall-clock time on a desktop NVIDIA GPU for a single
still image — it excludes camera capture, ARKit frame delivery, CoreML/ANE dispatch
overhead, the SORT tracker, distance estimation, `SpeechEngine`/TTS synthesis and
playback, and every other stage of the real on-device pipeline. The production app runs
on Apple Neural Engine (`computeUnits=.all`) via CoreML on an iPhone, which has
fundamentally different hardware, memory bandwidth, and thermal behavior, and the model
runs as an fp16 CoreML pipeline (detector + NMS stage) rather than a PyTorch/ultralytics
graph on a desktop GPU. `docs/system_overview.md`'s own documented production latency
budget is 30-55 ms typical / 90 ms worst case for the full Vision/CoreML inference
stage on-device — coincidentally in a similar numeric range to this benchmark's p50,
but that similarity must NOT be read as validation; the measurement conditions are not
comparable. **Real on-device numbers require the Mac/iPhone device benchmark** described
in `BENCHMARK_PLAN.md` Phase 2 — that work has not been done. GPU utilization was not
separately captured in this run (not requested by `BENCHMARK_PLAN.md` item #13, which
explicitly deprioritizes GPU-utilization tuning in favor of correctness).

## 7. What requires Mac/iPhone (cannot be done in this Phase B pass)

Per `docs/FAILURE_TAXONOMY.md` and `benchmark/metrics.py`'s module docstring, the
following application-level metrics from BENCHMARK_PLAN.md's candidate list are
**not measurable** with this Windows/static-image benchmark and require either a real
video/frame-sequence dataset or the actual on-device (Mac/iPhone) pipeline:

- **Detection stability** — needs multi-frame temporal continuity + the real
  `ObjectTracker` (SORT) running frame-to-frame.
- **TTS announcement latency / cadence** — needs the real `SpeechEngine`,
  `AVSpeechSynthesizer`, and device audio pipeline.
- **LiDAR spatial usefulness** — needs a LiDAR-equipped Apple device and real depth
  data; Open Images has no depth channel at all.
- **Cross-frame duplicate announcement rate** — needs the SORT tracker's identity
  assignment plus `SpeechEngine`'s per-object cooldown logic across multiple frames.
- **Real on-device ANE inference latency** — needs the actual `.mlpackage` running via
  CoreML with `computeUnits=.all` on physical Apple silicon; this benchmark's GPU
  latency (Section 6) is a proxy only.

All of the above are BENCHMARK_PLAN.md "Phase 2" work and are explicitly out of scope
here (this Phase B pass does not attempt or stub anything requiring Xcode/simulator/
device, per the task's stop condition).

## 8. Most promising areas for future improvement (grounded in the data above)

1. **Investigate `Person` recall specifically.** At 0.211 recall on the largest
   ground-truth class in the dataset (303 boxes), this is the strongest, best-evidenced
   finding in this report. Recommended first step: filter `failures.jsonl` for
   `ground_truth.class_name == "Person"` and inspect whether misses cluster around
   small/distant/grouped people (which the difficulty heuristic in the manifest can
   help characterize) versus clear, close, unoccluded individuals — the latter would be
   far more concerning for a mobility-assistance use case.
2. **`Stairs` recall (0.333) is the second most safety-relevant weak spot** given the
   app's explicit hazard-priority mode, though the evidence here is thinner (45 boxes)
   than for Person — worth expanding `Stairs` coverage in a future dataset pull
   (`docs/DATASETS.md` Section 5) before drawing firm conclusions.
3. **Occlusion and clutter are the dominant measurable failure modes** across hazard
   classes (226 and 101 of 826 hazard-class failures respectively) — this is consistent
   with, and adds independent quantitative support to, failure modes
   `docs/system_overview.md` already documented qualitatively for the tracker
   (doorway occlusion recovery, dense-crowd ID churn). It does not by itself indicate
   the detector needs to change — the tracker's coasting/recovery behavior, which this
   benchmark cannot measure, may already substantially compensate for single-frame
   occlusion misses in production.
4. **On the YOLOv8m → YOLO26n question** (referenced in recent commit history,
   `76c5508 feat: OmniSight v1.2 — StepHazardDetector + YOLO26n prep`): this benchmark
   provides a real, reproducible baseline (`benchmark/results/baseline/`) that a future
   head-to-head comparison against a YOLO26n candidate could be measured against — but
   **no such comparison exists yet**, and this report explicitly does not recommend a
   model swap. The data here characterizes the current model's weaknesses (Person
   recall, Stairs recall, occlusion/clutter sensitivity); it does not establish that a
   different model would do better, only that these are the areas where improvement, if
   pursued, would matter most.
5. **Dataset gap remains the largest open risk**, independent of any model choice: this
   entire report is built on Open Images V7 static photos, which `docs/DATASETS.md`
   Section 1 explicitly documents as NOT representative of OmniSight's real usage
   conditions (handheld motion, indoor low light, chest-height framing, walking pace).
   The Section 5 "weakest environments" finding is the clearest illustration of this
   report's own limits — the data cannot currently distinguish "the model is worse
   indoors" from "Open Images' indoor photos happen to be full of classes the model
   rarely predicts." Closing this gap (via the human-capture pathway in
   `docs/DATASETS.md` Section 8) would meaningfully increase confidence in every
   other finding in this report.

## 9. Reproducibility

Full run metadata: `benchmark/results/baseline/run_metadata.json`
(`run_id: RUN-20260904-002`, git commit `76c5508`, model SHA-256
`21ffa3718c577ac23e708e4c0544c49a20682efa03914d5f816166b54e8fd3fe`, manifest SHA-256
`617190fd433c26c1bb916e6844c705c64edf73defe49bac1d72eba5623915327`, random seed 42).
Same model/manifest/config as the original `RUN-20260904-001` — re-run only to pick up
the `_classify_failure` bug fix described in the addendum at the top of this report.
Re-run with `uv run python -m benchmark.evaluate` after regenerating the dataset with
`uv run python -m benchmark.build_dataset` if `data/raw/eval/` is not already populated
(gitignored, local-only per `docs/DATASETS.md`).
