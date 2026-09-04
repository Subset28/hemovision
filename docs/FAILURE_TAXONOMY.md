# OmniSight Failure Taxonomy

> **Bug-fix note (2026-09-04 validation pass):** `benchmark/evaluate.py::_classify_failure`
> previously matched a missed ground-truth box's occlusion/size signals by `class_name`
> only, taking the first same-class label found in that image. For images with multiple
> ground-truth boxes of the same class, this could tag a missed box `occlusion` using a
> *different* same-class box's `IsOccluded` flag. Fixed to match on `(class_name, bbox)`.
> Independently re-verified: every `occlusion`-tagged `failures.jsonl` record's ground
> truth box now genuinely has `IsOccluded=True` in the manifest (0 mismatches — see
> `benchmark/diagnostics/occlusion_analysis.py` /
> `benchmark/results/diagnostics/occlusion_analysis.json`). That same script also found
> heavy co-occurrence between `occlusion` and `small_object`/`clutter` (because occlusion
> is checked first in the priority order below and "wins" whenever present) — see the
> "Priority order and confounding" section near the end of this document.

Starting point: `docs/system_overview.md`'s "Failure Modes & Known Limitations" section
(Tracking / Distance Estimation / TTS / LiDAR / Hazard Priority Mode tables), which
documents real, already-observed production failure modes of the shipped app. This
taxonomy generalizes those into stable categories usable by the benchmark's
`failures.jsonl` output (`benchmark/evaluate.py`), and is explicit about which
categories a **static-image** benchmark can and cannot actually populate.

## Categories

| Category | Description | Populated by this static-image benchmark? |
|---|---|---|
| `missed_detection` | Ground-truth object present, no matching prediction at any confidence/IoU that clears the operating threshold, and none of the more specific reasons below apply | **Yes** |
| `false_positive` | Predicted box with no matching ground-truth object in the image | **Yes** |
| `duplicate_detection` | Multiple predicted boxes matching the same ground-truth object in a single image (single-frame proxy only — see note below) | **Yes, but as a weaker proxy** |
| `small_object` | Missed detection where the ground-truth box covers less than 2% of image area | **Yes** |
| `occlusion` | Missed detection where the ground-truth box is flagged `IsOccluded` by Open Images' own annotators | **Yes** |
| `clutter` | Missed detection in an image with more than 8 total ground-truth boxes | **Yes** |
| `confusing_object_classes` | Model predicts a plausible but wrong class at high IoU with a ground-truth box of a *different* class (near-miss classification error) | **Partially** — the current `evaluate.py` does not separately break this out from generic `false_positive`/`missed_detection`; a future refinement could cross-reference high-IoU predictions of the wrong class specifically. Not implemented in this Phase B pass — documented here as a known gap, not silently skipped. |
| `unstable_detection` | A tracked object's box/identity flickers across consecutive frames (appears/disappears/ID-churns) | **No — structurally impossible.** Requires a video/frame-sequence with temporal continuity and the actual `ObjectTracker` (SORT) running. A single static image has no "next frame" to compare against. |
| `motion_blur` | Object blurred due to camera or subject motion | **No.** Open Images V7 is a corpus of static, generally well-composed photos; it has no controlled motion-blur signal, and this benchmark does not attempt to detect blur heuristically (that would be inventing a stand-in metric, which the spec explicitly forbids). |
| `distance` | Object mis-estimated in real-world distance (meters) | **No.** Distance estimation (`CoreMLDetector.swift`'s focal-length formula / LiDAR override) is not exercised at all by this benchmark — there is no camera intrinsics or depth data in Open Images. |
| `unusual_viewpoint` | Object photographed/viewed from an atypical angle (e.g. camera tilted down, object from above/below) | **No, not directly measured.** Open Images includes some off-angle photos incidentally, but this benchmark has no ground-truth viewpoint label and does not tag or measure it — would require either manual annotation or a human-captured dataset (see `docs/DATASETS.md` Section 8). |
| `tracking_failure` | SORT tracker loses, mis-assigns, or fails to recover an object's identity across frames | **No — structurally impossible**, same reason as `unstable_detection`: no frame sequence, no tracker is even instantiated in this benchmark (`benchmark/evaluate.py` only calls the detector, never `ObjectTracker`). |
| `lidar_fusion_failure` | LiDAR depth sample is wrong/missing/on a glass or specular surface, corrupting distance estimation | **No.** No LiDAR data exists in Open Images; this benchmark never runs on a LiDAR-equipped device. |
| `tts_announcement_failure` | `SpeechEngine` mis-prioritizes, drops, or garbles an announcement (cooldown bug, queue starvation, wrong class name spoken, mode-switch cutoff) | **No.** `SpeechEngine.swift` is not invoked anywhere in this benchmark — it is pure iOS app code, read-only per this task's scope, and has no static-image equivalent. |
| `other` | Any failure that doesn't fit the above — free-text description required | **Yes, as an escape hatch.** `evaluate.py`'s `_classify_failure` does not currently emit `other` (every failure it sees falls into one of the implemented categories), but the taxonomy reserves it for future refinement rather than force-fitting edge cases. |

## Categories this benchmark CAN populate (static single-image detector output only)

`missed_detection`, `false_positive`, `duplicate_detection` (weak proxy),
`small_object`, `occlusion`, `clutter`. These come directly from
`benchmark/results/baseline/failures.jsonl`, produced by `benchmark/evaluate.py`'s
`_classify_failure()` using only signals a static image genuinely provides: whether a
ground-truth box was matched, its size relative to the image, its Open-Images-annotated
`IsOccluded` flag, and the total box count in that image.

## Categories this benchmark structurally CANNOT populate (need video/device)

`unstable_detection`, `motion_blur`, `distance`, `unusual_viewpoint` (unmeasured, not
strictly impossible but not attempted here), `tracking_failure`,
`lidar_fusion_failure`, `tts_announcement_failure`. All of these require either (a) a
real multi-frame video with temporal continuity, or (b) the actual on-device pipeline
(ARKit + SORT tracker + LiDAR + SpeechEngine) running on a physical iPhone/Mac. Per
BENCHMARK_PLAN.md, that is Phase 2 (Mac/iPhone device benchmark), explicitly out of
scope for this Windows-only Phase B pass. This benchmark does not implement stand-ins or
heuristic guesses for any of these — see `benchmark/metrics.py`'s module docstring and
`reports/baseline/Baseline_Report.md` for the same honesty constraint applied to
metrics.

## `duplicate_detection` — why it's a weaker proxy, precisely

Production "duplicate announcement rate" is a **cross-frame** phenomenon: the same
physical object gets announced twice because the SORT tracker assigned it two different
track IDs (e.g. after a brief occlusion) and `SpeechEngine`'s per-class/per-object
cooldown didn't suppress the second announcement. This benchmark's
`duplicate_detection` category is a **single-frame** proxy: two predicted boxes from one
model inference pass both landing on (i.e., matching) the same ground-truth object in
one static image. These are related in spirit (both are "the same object announced/
detected more than once") but are different mechanisms with different root causes —
the static-image version is purely a detector NMS/confidence artifact, while the
production version is a tracker identity/TTS-cooldown artifact. Do not conflate the two
numbers when reading `benchmark/results/baseline/metrics.json`'s
`duplicate_box_rate_proxy`.

## `failure_type` field values used in `failures.jsonl`

Exactly the "Yes" rows above: `missed_detection`, `false_positive`,
`duplicate_detection`, `small_object`, `occlusion`, `clutter`. Every record also carries
`is_hazard_class` (bool), `model_version`, and `benchmark_version` for
reproducibility/filtering. See `benchmark/evaluate.py::_classify_failure` for the exact
decision order (duplicate/false-positive kind is passed in explicitly by the caller;
for missed detections, occlusion is checked before small-object before clutter — i.e.
categories are not mutually exclusive in the underlying data, but each failure record
gets exactly one label, assigned by that priority order).

## Priority order and confounding — read before citing "occlusion dominates"

Because `_classify_failure` checks `IsOccluded` first and returns immediately if true, a
missed box that is simultaneously occluded, small, and in a cluttered image is ALWAYS
tagged `occlusion`, never `small_object` or `clutter`. `benchmark/diagnostics/
occlusion_analysis.py` quantifies this: of all `occlusion`-tagged failures, ~56% are
ALSO small (<2% image area) and ~89% are ALSO in a cluttered image (>8 boxes) — see
`benchmark/results/diagnostics/occlusion_analysis.json` for exact current counts. This
means the taxonomy's occlusion count should be read as "annotator-flagged-occluded
boxes that were missed," not as an isolated, confound-free measurement of occlusion's
causal contribution — it is very often ALSO a small or cluttered-scene box, and Open
Images' `IsOccluded` flag itself is a coarse binary with no severity gradation (it
cannot distinguish "clipped by a doorframe" from "90% hidden"). Treat "occlusion
dominates failures" as a real, verified pattern in the tagged data, not as a proven
independent cause.
