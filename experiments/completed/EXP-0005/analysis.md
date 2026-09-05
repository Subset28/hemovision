# EXP-0005 — Analysis

- primary metric 'person.recall' delta (+0.0198) is below the minimum meaningful delta (0.03)

## Full picture across all 4 candidates (not just the representative)

The DB verdict above reflects only the pre-registered REPRESENTATIVE candidate
(D_yolov8l_oiv7_diagnostic_upper_bound — best fixed-conf=0.4 Person recall delta
among candidates that clear every guardrail). The representative-selection rule
is a summary convention for a single DB row; the full evidentiary picture,
computed and reported for every candidate regardless, is below. See
`model_comparison.json`, `person_transitions.json`, and
`reports/baseline/model_variant_analysis.md` for the complete numeric detail.

**A (baseline, yolov8m-oiv7)**: hazard-8 P=0.8070 R=0.4804, Person P=0.6667
R=0.2112. Reference point.

**B (yolov8n-oiv7, smaller/same vocab)**: Person recall DROPS to 0.1188
(-0.092 vs baseline), hazard recall drops to 0.3238 — hard-fails the
hazard-recall guardrail (baseline-0.02 floor). 29/64 baseline Person TPs
regressed. Verdict: FAILED. A strictly smaller model, same architecture and
training data as the baseline, is strictly worse — consistent with capacity
(within this architecture family) mattering in the expected direction.

**C (yolo11m, COCO, newer architecture)**: at the fixed conf=0.4 operating
point, common-class Person recall looks dramatically better (0.5677 vs
0.2112, +0.357) and it recovers 17/92 (18.5%) TRUE_DETECTOR_MISS cases — the
first candidate across EXP-0001–0005 to recover ANY TRUE_DETECTOR_MISS case
at all (EXP-0004's best preprocessing candidate recovered 0/92). However,
common-class hazard precision COLLAPSES to 0.4540 (vs baseline 0.8070),
hard-failing the hazard-precision guardrail by a huge, non-noisy margin, and
5/64 baseline Person TPs regressed. At the precision-matched comparison
(Person recall once precision is brought back up to the baseline's own
0.6667), C's recall falls to 0.0066 — essentially nothing. At the
guardrail-matched comparison (recall once hazard precision is brought back
up to the 0.757 floor), C's recall is 0.1221 — still worse than baseline's
own guardrail-matched recall of 0.2442. **C's large fixed-threshold gain is a
confidence-calibration artifact, not a genuine detection improvement**: this
COCO-trained model produces far more (and much lower-confidence) boxes at
conf=0.4 than the OIV7 baseline does at the same nominal threshold, and its
raw recall/precision curve sits well below the baseline's once matched on
precision. Verdict: FAILED.

**D (yolov8l-oiv7, larger, same vocab/arch, "capacity ceiling probe")**:
hazard-8 P=0.7971 R=0.5078, Person P=0.6542 R=0.2310 (+0.0198 vs baseline —
directionally positive, guardrails all clear, but below the pre-registered
0.03 meaningful-delta floor). At the guardrail-matched comparison, D's Person
recall is 0.2640 vs baseline's 0.2442 — also a small, real, guardrail-clean
improvement, but again well under a magnitude that would be called
"meaningful" anywhere else in this lab. D recovers only 1/92 TRUE_DETECTOR_MISS
cases despite ~1.7x the baseline's parameters. Verdict: INCONCLUSIVE
(representative).

## Explicit answers to the task's analysis questions

**(1) Does changing the pretrained detector materially improve Person
detection?** Not at a fair, precision-matched comparison. One candidate (D)
shows a small, guardrail-clean, real improvement that falls short of this
lab's own meaningful-delta bar. Another (C) shows an apparently large
fixed-threshold improvement that is a calibration artifact, not a genuine
gain — it evaporates (and inverts) once precision is matched.

**(2) Does any candidate recover a meaningful fraction of the 92
TRUE_DETECTOR_MISS cases?** Yes — candidate C recovers 17/92 (18.5%) at the
fixed conf=0.4 threshold, the first genuine recovery of ANY TRUE_DETECTOR_MISS
case across EXP-0001–0005 (EXP-0004's preprocessing recovered 0/92). This is
the headline result of this experiment. BUT it comes bundled with a hazard
precision collapse that hard-fails the production guardrail and 5/64 baseline
TP regressions — so while it is evidence that a genuinely different
architecture/training pipeline CAN see things the baseline structurally
cannot, this specific candidate's operating point is not viable as-is. D
(same architecture family, just bigger) recovers essentially none (1/92) —
capacity alone, without also changing architecture/training data, does not
touch TRUE_DETECTOR_MISS.

**(3) Does any candidate materially improve small-Person detection?** Yes,
directionally, again only candidate C: of the 68 small-Person (<2% GT area)
TRUE_DETECTOR_MISS cases, C recovers 14 to TP; of 49 small-Person
LOW_CONFIDENCE_PERSON cases, C recovers 39 to TP (see
`person_transitions.json`'s size_transitions.small breakdown). D recovers 0
and 2 respectively. This is the first small-Person recovery seen across
EXP-0001–0005 (EXP-0004 recovered zero). Same caveat as (2): C's overall
precision collapse means this is not a clean win.

**(4) Is any improvement still present at matched precision, not just
different calibration?** For C: no — its precision-matched recall (0.0066)
and guardrail-matched recall (0.1221) are both far WORSE than the baseline's
own guardrail-matched recall (0.2442). C's apparent gain is calibration, not
capability, at least at the fixed threshold; whether its underlying raw
detections genuinely contain more signal than the baseline (just poorly
calibrated) versus genuinely less signal at matched precision cannot be
resolved further with a single confidence-threshold sweep — see Methodological
limitations. For D: yes, D's small improvement (guardrail-matched recall
0.2640 vs baseline's 0.2442) persists at matched precision, but is small.

**(5) Compute/latency cost?** All figures are Windows/CUDA relative compute
proxies, NOT iPhone. B (nano) is fastest (p95=54.5ms) and smallest
(6.9MB/3.5M params) but the weakest performer. D (large) is the slowest to
first-token (p95 inference varies run-to-run in the 45-70ms band on this
hardware) and largest (84.5MB/44.1M params, ~1.7x baseline size) for a
sub-threshold gain — poor cost/benefit. C (yolo11m) is mid-sized (38.8MB/
20.1M params) with comparable latency to the baseline. Peak GPU memory scales
roughly with parameter count (187MB for B up to 373MB for D).

**(6) Is evidence now consistent with YOLOv8m capacity/representation being
a major limitation?** Partially, and only weakly. D isolates "capacity alone,
same architecture/training data" and shows almost no effect (+0.02 Person
recall, 1/92 TRUE_DETECTOR_MISS recovered) — this is evidence AGAINST pure
capacity being the bottleneck within the YOLOv8/OIV7 family. C, which
changes architecture AND training data AND vocabulary simultaneously, shows
a much larger raw signal (at least on TRUE_DETECTOR_MISS recovery and
small-Person recovery) even though its overall operating point fails
guardrails. Per the task's own caution: a better/different model producing a
different result supports, but does not PROVE, that "capacity" specifically
was the limiting factor in the baseline — architecture (anchor-free head
design, YOLO11 vs YOLOv8), training data (COCO vs OIV7 distribution/labeling
density), label vocabulary, and optimization/training recipe all differ
between A and C at once, and this experiment cannot cleanly separate them.
The cleanest reading of the accumulated EXP-0001–0005 evidence is: capacity
alone (D) is not the answer; something about C's different architecture/
training pipeline (not isolated) shows a real, if costly, capability the
baseline lacks entirely (TRUE_DETECTOR_MISS/small-Person recovery) that no
threshold, class-remapping, preprocessing, or same-family capacity increase
could produce.

**(7) Which candidate, if any, deserves Mac/iPhone validation?** None of the
4 candidates tested here, as evaluated. D is guardrail-clean but its gain is
too small to justify the ~1.7x model-size cost. C shows the single most
interesting signal in this entire lab (real TRUE_DETECTOR_MISS/small-Person
recovery, something no other EXP-0001–0005 candidate achieved) but its
current operating point badly fails the precision guardrail and cannot be
recommended for device validation as-is. If a follow-on experiment
recalibrates C's confidence threshold/NMS specifically for this OIV7-style
evaluation (rather than reusing 0.4 uncritically across two differently-
calibrated models) and still shows meaningful signal at matched precision,
THAT would be the first genuinely promising model_variant candidate for
Mac/iPhone validation. This experiment does not perform that recalibration
exercise itself (would require re-picking a new "production-representative"
threshold per candidate, a materially different pre-registration than the
one made here) — it is flagged as the most concrete, evidence-based next
step, not decided or acted on.

**(8) If no candidate wins, what should EXP-0001–0005's accumulated evidence
imply for what's tested next?** (Assessment only — not a decision, and
nothing is acted on here.) Five families have now been tried:
threshold/postprocessing (EXP-0001, confirmed non-viable), resolution
(EXP-0002, FAILED), class-confusion remapping (EXP-0003, FAILED), preprocessing
(EXP-0004, INCONCLUSIVE, best candidate sub-threshold), and model variant
(EXP-0005, INCONCLUSIVE at the representative level). Of all five, EXP-0005's
candidate C is the only one to show a real (non-zero) TRUE_DETECTOR_MISS and
small-Person recovery — a qualitatively different kind of evidence than
"different threshold on the same underlying detections." That suggests the
next most informative test would isolate WHY C recovers those cases
(architecture vs. training-data distribution vs. label density) rather than
returning to inference-time-only levers (threshold/preprocessing/resolution)
already shown not to move TRUE_DETECTOR_MISS at all, or to a same-family
capacity increase (D) already shown to barely move it either. The training_data
family (F) — never yet tried — and a properly recalibrated, guardrail-aware
re-run of a newer-architecture candidate are the two most evidence-backed
candidates for what to look at next. This is explicitly not a decision to
pursue either; EXP-0006 is out of scope for this task.

## Methodological limitations

- Fixed conf=0.4 was held constant across all candidates as the PRIMARY
  comparison per the pre-registration (matching every other experiment in
  this lab, and the app's real production operating point) — but candidate
  C's evaluation demonstrates this can be actively misleading for a
  cross-architecture/cross-training-data comparison. The precision-matched
  and guardrail-matched sweeps mitigate this but do not fully resolve it
  (see (4) above): a genuinely optimal, independently-tuned operating point
  per candidate was out of scope for this pre-registration.
- CoreML export was attempted for 2 candidates (A, B) and failed for a
  structural, platform-level reason (ultralytics refuses CoreML export on
  Windows outright, `AssertionError: CoreML export is not supported on
  Windows, please run on macOS or Linux`) — this says nothing about whether
  either checkpoint COULD export successfully on macOS; it is untested here
  by construction (Windows-only environment).
- Latency/peak-GPU-memory figures are Windows/CUDA (RTX 3070 Ti) proxies,
  not iPhone/ANE numbers, and cannot be used to infer real on-device
  behavior, especially since none of these checkpoints were actually
  converted to CoreML and run on Apple Neural Engine hardware.
- 380 static images is a modest sample for some hazard classes (Stairs=45,
  Truck=42, Bus=49, Motorcycle=49 GT boxes) — the sample-size floors in
  research/evaluation_policy.py's default_hazard_policy already downgrade
  low-confidence conclusions on those classes; Person (303 GT boxes) is
  well-supported.
- C's COCO vocabulary structurally cannot be evaluated on Stairs at all —
  the common-class comparison (hazard-7) is the primary basis for judging C,
  and is explicitly a strict subset of the full hazard-8 evaluation used for
  A/B/D.
