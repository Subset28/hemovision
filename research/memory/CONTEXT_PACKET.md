# Research Memory — Context Packet

Regenerable artifact — produced by `research/memory_context.py::generate_context_packet()`. Do not hand-edit; re-run the generator instead.

**Read this before proposing any new experiment.** Phase D (EXP-0001 through EXP-0005) is closed. Do not re-propose anything in 'Rejected directions' below.

## Verified baseline
- **[MEM-0001]** Shipped production detector is Ultralytics YOLOv8m, trained on Open Images V7 (601-class vocabulary), conf=0.4, iou=0.7, imgsz=640. YOLO26n is referenced in commit history/docs but was never actually shipped (StepHazardDetector Swift code landed; the model swap itself did not). (`OMNISIGHT_ARCHITECTURE.md`)
- **[MEM-0002]** Baseline hazard-class metrics (person, car, truck, bus, bicycle, motorcycle, stairs, dog): Precision=0.807, Recall=0.480, F1=0.602, mAP@50=0.582 (TP=368, FP=88, FN=398). (`benchmark/results/baseline/metrics.json`)
- **[MEM-0003]** Person recall = 0.211 at the production operating point (conf=0.4), precision = 0.667, GT=303 boxes (the largest and most statistically trustworthy hazard-class sample). This is the worst hazard-class recall in the dataset. (`benchmark/results/baseline/per_class.json`)
- **[MEM-0004]** Hazard-precision guardrail floor used by the evaluation policy is baseline_precision - 0.05 = 0.807 - 0.05 = 0.757 (hazard.precision guardrail, `default_hazard_policy`); hazard-recall floor is baseline - 0.02; p95 latency floor is baseline * 1.5. (`research/evaluation_policy.py`)
- **[MEM-0005]** Windows/CUDA inference-only latency proxy (RTX 3070 Ti): p50=18.0ms, p95=57.1ms, p99=65.8ms, mean=24.3ms. (`benchmark/results/baseline/metrics.json`)

## Strongest findings
- **[MEM-0015]** (SUPPORTED_HYPOTHESIS) Architecture, training-data, and/or learned-representation differences between detector checkpoints MAY matter for recovering TRUE_DETECTOR_MISS Person cases — candidate C (yolo11m, a different architecture family, COCO-trained) recovered 17/92 (18.5%) TRUE_DETECTOR_MISS cases at fixed conf=0.4, the first candidate across EXP-0001 through EXP-0005 to recover ANY TRUE_DETECTOR_MISS case, versus 1/92 for the same-family, larger yolov8l-oiv7 candidate and 0/92 implied by EXP-0004's negligible overall recall movement. This is NOT proof that model capacity is the bottleneck — candidate C's gain is confounded with its different training data/class vocabulary (COCO vs Open Images V7), and it was rejected as a production candidate on hazard-precision grounds regardless of this recall signal.

## Rejected directions — do not re-propose these
- **[MEM-0010]** (EXP-0001) Global confidence-threshold reduction alone can resolve Person recall without unacceptable precision loss. REJECTED: at conf=0.05, Person recall rises 0.211->0.479 but hazard precision collapses 0.807->0.381 (guardrail floor 0.757), a violation far outside the noise margin.
- **[MEM-0011]** (EXP-0002) Increasing inference-time input resolution alone (640->960) meaningfully improves Person recall. REJECTED: Person recall actually dropped 0.211->0.165 and hazard recall dropped below its guardrail floor (0.449 vs 0.460), at 1.27x the baseline latency.
- **[MEM-0012]** (EXP-0003) Broad semantic aliasing (remapping Man/Woman/Boy/Girl/Human body to Person at scoring time) recovers Person recall while preserving precision. REJECTED: accepting whole-person aliases at conf>=0.4 recovers only 14/239 GTs but introduces 93 new false positives, dropping hazard precision 0.807->0.679 (0.129 below floor, non-noisy). No confidence floor in the swept range (0.25-0.8) rescues the tradeoff; subpart classes (Human hand/face) recover 0 additional GTs while adding more FPs.
- **[MEM-0013]** (EXP-0004) A generic pixel-level preprocessing transform (contrast/sharpening/CLAHE-style) applied before inference improves Person recall enough to be actionable. REJECTED (INCONCLUSIVE, not a clean pass): best candidate ('gamma') moved person.recall by only +0.0198 (0.211->0.231), below the 0.03 minimum-meaningful-delta threshold — a small, not-clearly-real effect.
- **[MEM-0014]** (EXP-0005) Simple model-size/checkpoint scaling alone (same OIV7 vocabulary, larger backbone) meaningfully improves Person recall at production confidence. REJECTED for the as-tested candidates: the best fixed-conf=0.4 candidate (yolov8l-oiv7) moved person.recall by only +0.0198 (0.211->0.231), below the 0.03 minimum-meaningful-delta threshold — the same negligible-effect-size result as EXP-0004.

## Unresolved questions
- **[MEM-0023]** Does Person recall degrade differently for small-vs-occluded-vs-confused causes when analyzed independently (fully deconfounded)? Open Images' binary IsOccluded flag cannot support this alone.
- **[MEM-0024]** What is the real on-device (ANE/CoreML) latency for any candidate change? Nothing in this lab can answer this without a Mac + physical iPhone (REQUIRES_MAC/REQUIRES_IPHONE).
- **[MEM-0025]** Would a human-collected OmniSight-specific dataset (docs/DATASETS.md Section 8) change any of these findings? Open Images V7 is documented as not representative of real accessibility-usage conditions.
- **[MEM-0026]** Would YOLO26n (referenced in commit history, never shipped) improve Person/Stairs recall? EXP-0005 tested other model variants but not YOLO26n specifically, and Phase D is now closed — this remains untested.
- **[MEM-0027]** Is there a combination of interventions (e.g. a different architecture family AND targeted preprocessing) that could recover more TRUE_DETECTOR_MISS cases than any single lever tested in EXP-0001-0005 alone? No combined/interaction experiment was run; Phase D is closed.
- **[MEM-0028]** What, mechanistically, distinguishes the 92 TRUE_DETECTOR_MISS cases from the other 147 Person FNs beyond size (68/92 are small)? No feature-level analysis (attention maps, activation inspection) was attempted.
- **[MEM-0029]** Literature-grounded hypothesis generation (research/literature/) was never started — no OPENROUTER_API_KEY was available in this environment, and Phase E explicitly makes no LLM calls either.

## Limitations
- **[MEM-0016]** Windows/CUDA (RTX 3070 Ti) inference latency is NOT iPhone Neural Engine latency. No CoreML/ANE dispatch, no camera capture, no ARKit, no SORT tracker, no TTS — this is a desktop-GPU inference-only proxy.
- **[MEM-0017]** Open Images V7 static-image evaluation is NOT real-world OmniSight validation. It is a corpus of static internet photos, not handheld-camera accessibility footage — it does not reproduce live camera motion, chest-height framing, indoor low light, walking-pace motion blur, or unusual viewpoints.
- **[MEM-0018]** Ground-truth box area is used as a proxy for physical distance/size; it is not a measured physical distance and has no depth/LiDAR grounding in this dataset.
- **[MEM-0019]** Thin-sample hazard classes (Stairs GT=45, Truck GT=42, Bus GT=49, Motorcycle GT=49) require caution: a swing of a handful of boxes moves their recall by ~10 percentage points. Never present their numbers with Person/Car-level statistical confidence.
- **[MEM-0020]** Occlusion-tagged failures are confounded with small size and image clutter, not an independently-isolated cause: of all occlusion-tagged failures, 56.0% are also small (<2% area) and 88.7% are also in a cluttered image (>8 boxes).
- **[MEM-0021]** Fixed-confidence (conf=0.4) cross-architecture comparisons can mislead: different model families/checkpoints may have different confidence calibration, so comparing recall at one fixed threshold across architectures (as EXP-0005 does for its primary verdict) can understate or overstate a candidate's real potential relative to a precision-matched comparison.
- **[MEM-0022]** Production (`ios/`, `benchmark/config.py`'s real operating point, the canonical baseline run `RUN-20260904-002`) remains protected throughout this lab's work — no experiment modifies shipped code, and diagnostic/candidate configurations are never mistaken for production settings.

## Experiments closed (Phase D)
- EXP-0001: independent_variable='confidence_threshold', verdict=PASS
- EXP-0002: independent_variable='imgsz (inference-time only: 640 -> 960)', verdict=FAIL
- EXP-0003: independent_variable='scoring-time class grouping map (measurement only, not a production change)', verdict=FAIL
- EXP-0004: independent_variable='one preprocessing transform (e.g. CLAHE) applied before inference', verdict=INCONCLUSIVE
- EXP-0005: independent_variable='model checkpoint/architecture', verdict=INCONCLUSIVE

> Phase D is CLOSED. Do not create EXP-0006 or any new experiment based on this packet alone without explicit human approval of a new phase.
