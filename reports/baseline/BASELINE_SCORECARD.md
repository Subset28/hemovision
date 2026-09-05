# OmniSight Detector Baseline Scorecard

Run: `RUN-20260904-002` (`benchmark/results/baseline/run_metadata.json`). Model:
`benchmark/models/yolov8m-oiv7.pt`, imgsz=640, conf=0.4, iou=0.7 — the app's real
operating point, unchanged (`benchmark/config.py`). Dataset: 380 Open Images V7
validation images, 4,916 GT boxes (`data/manifests/eval_manifest.jsonl`,
`docs/DATASETS.md`). This is a Phase B validation-pass output — see
`reports/baseline/Baseline_Report.md` for full narrative detail and
`reports/baseline/person_failure_analysis.md` for the Person-recall deep dive.

One real bug was found and fixed during this validation pass (a failure-taxonomy
mislabeling issue in `benchmark/evaluate.py::_classify_failure` — see the addendum at
the top of `Baseline_Report.md`). It did NOT affect any P/R/F1/mAP number below; it
only corrected the occlusion/small_object/clutter failure-type breakdown. Label mapping
(class-name strings, bbox coordinate convention, IoU calculation) was independently
audited and found CORRECT — no bug there.

---

## 1. Detector — hazard classes only (the metric that matters for OmniSight)

Hazard classes = `person, car, truck, bus, bicycle, motorcycle, stairs, dog`
(`ios/OmniSightKit/.../OpticalCore.swift`), mapped 1:1 to OIV7 leaf classes.

| Metric | Value |
|---|---|
| mAP@50 | **0.582** |
| mAP@50:95 | 0.499 |
| Precision | 0.807 |
| Recall | **0.480** |
| F1 | 0.602 |
| TP / FP / FN | 368 / 88 / 398 |
| GT boxes / predictions | 766 / 456 |
| Miss-rate proxy (1 − recall) | 0.520 |

## 2. Important classes (GT sample count shown inline — read the count before the number)

| Class | GT boxes | Precision | Recall | AP@50 | Confidence |
|---|---|---|---|---|---|
| **Person** | **303** | 0.667 | **0.211** | 0.174 | High (largest sample in dataset) |
| **Car** | 148 | 0.718 | 0.601 | 0.543 | Medium-high |
| **Dog** | 52 | 0.962 | 0.962 | 0.953 | Medium (borderline low) |
| **Stairs** | **45** | 0.682 | 0.333 | 0.286 | **Low — under 50 samples, treat as directional only** |

**Person** (303 GT boxes, largest hazard class): recall 0.211 is the worst of the 8
hazard classes and is a high-confidence finding given the sample size. Root-caused in
`reports/baseline/person_failure_analysis.md`: 65.3% of the 239 missed boxes are
`IsOccluded=True`, 64.0% have box area <2% of image, 41.8% have a genuine below-threshold
candidate (partially threshold-recoverable, at a precision cost — see Section 4), and
35.1% are classification confusion with a different person-adjacent OIV7 class
(`Man`/`Woman`/`Human body`/`Clothing`). Only 6.3% have literally no model candidate at
any confidence.

**SUPERSEDED (Phase E)**: the 35.1% classification-confusion figure above was an
informal count (any same-location alternate-class detection at any confidence).
EXP-0003's rigorous IoU-based re-matching found genuine semantic class confusion is
only 13/239 = 5.4% — see `reports/baseline/person_class_confusion_analysis.md` and the
structured, queryable correction in `research/memory.db` (`uv run python -m research.cli
memory query person-failure-modes`).

**Stairs** (45 GT boxes): recall 0.333 looks better than Person's but rests on a sample
9x smaller. A swing of 4-5 boxes would move this recall figure by roughly 10 percentage
points — do not compare it to Person's number with equal confidence, and do not treat
0.333 as a stable, precise estimate.

## 3. Overall (all ~146 OIV7 classes in the eval set) — context only, not the primary metric

| Metric | Value |
|---|---|
| Precision | 0.734 |
| Recall | 0.247 |
| mAP@50 | 0.201 |
| mAP@50:95 | 0.167 |

**Why this is less informative than Section 1**: Open Images V7 exhaustively labels
every object type present in a photo, so the "all classes" ground truth includes ~67
OIV7 ontology ancestor/superclass categories (`Mammal`, `Vehicle`, `Land vehicle`,
`Furniture`, `Human body`, `Tableware`, ...) that the model structurally almost never
predicts as a leaf label at conf≥0.4, even though they're technically in its 601-class
vocabulary. This drags "overall" numbers down for reasons that have nothing to do with
OmniSight's real hazard-detection accuracy. Section 1's hazard-only numbers are the
ones that reflect what OmniSight actually announces to a user.

## 4. Diagnostic: confidence-threshold sensitivity (does NOT change the real config)

From `benchmark/results/diagnostics/threshold_sweep.json` (single conf=0.01 capture,
filtered post-hoc — `benchmark/config.py`'s conf=0.4 is unchanged and remains the real
operating point):

| Person conf cutoff | Precision | Recall |
|---|---|---|
| 0.05 | 0.312 | 0.479 |
| 0.20 | 0.498 | 0.343 |
| **0.40 (real baseline)** | **0.667** | **0.211** |
| 0.60 | 0.789 | 0.099 |

Lowering the threshold roughly doubles Person recall (0.211→0.479 at conf=0.05) but
more than halves precision (0.667→0.312) — a real but partial, expensive lever, not a
free fix. See `reports/baseline/figures/pr_curve_person.png` and the other 7 hazard-class
PR curves in the same directory.

## 5. Performance — Windows/CUDA proxy, NOT on-device

| Metric | Value |
|---|---|
| p50 | 18.0 ms |
| p95 | 57.1 ms |
| p99 | 65.8 ms |
| Mean | 24.3 ms |

**This is a Windows/CUDA inference-only proxy. It is explicitly NOT iPhone Neural
Engine latency, NOT full camera-to-announcement latency, NOT end-to-end OmniSight
latency.** It measures only `ultralytics.YOLO.predict()` wall-clock time on an RTX 3070
Ti for a single still image — no camera capture, no ARKit, no CoreML/ANE dispatch, no
SORT tracker, no distance estimation, no TTS. Real on-device numbers require the actual
Mac/iPhone device benchmark (`BENCHMARK_PLAN.md` Phase 2), which has not been done.

## 6. Limitations — everything this benchmark does NOT measure

- **Detection stability / temporal continuity** — this is a static-image benchmark; no
  frame-to-frame tracking is exercised (the SORT `ObjectTracker` is never instantiated).
- **TTS announcement latency/cadence** — `SpeechEngine` is not invoked here at all.
- **LiDAR spatial usefulness / distance estimation** — no depth data exists in Open
  Images V7; no LiDAR-equipped device was used.
- **Cross-frame duplicate-announcement rate** — the `duplicate_box_rate_proxy` here is a
  same-image, single-frame proxy only, not the tracker/cooldown-driven production metric.
- **Real on-device Apple Neural Engine latency** — Section 5's numbers are a desktop-GPU
  proxy only.
- **True accessibility-scenario coverage** — Open Images V7 is a corpus of static
  internet photos, not handheld-camera accessibility footage. It does not reproduce live
  camera motion, chest-height framing, indoor low light/backlighting, walking-pace
  motion blur, or unusual viewpoints. See `docs/DATASETS.md` Section 1 and Section 8 for
  the planned human-collected OmniSight-specific dataset that would close this gap.
- **Occlusion severity** — Open Images' `IsOccluded` is a coarse binary flag; this
  benchmark cannot measure how occluded a box is, only whether an annotator ticked the
  box, and occlusion-tagged failures are heavily confounded with small size/clutter (see
  `docs/FAILURE_TAXONOMY.md` "Priority order and confounding").
- **Statistical confidence varies sharply by class** — Person (303 GT), Car (148) support
  high-confidence per-class numbers; Bicycle (78), Dog (52), Motorcycle (49), Bus (49),
  Stairs (45), Truck (42) do not — treat all of the latter, and Stairs especially, as
  directional signal, not precise measurement.

## 7. Recommendation

See the final report-back for this validation pass for an explicit go/no-go
recommendation on proceeding to Phase C. This scorecard itself makes no such judgment —
it is a numbers reference only.
