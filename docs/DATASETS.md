# OmniSight Evaluation Datasets

Status: Phase B eval-only benchmark. This document is durable project record per
`CLAUDE.md` — keep it current when the dataset changes.

## 1. Two categories of eval data — be honest about the gap

- **(A) General object-detection eval** — static single images from a licensed public
  dataset (Open Images V7). Measures raw detector precision/recall/mAP against a broad,
  well-annotated class vocabulary. This is what this document and the current
  `data/manifests/eval_manifest.jsonl` provide.
- **(B) OmniSight-specific eval** — real accessibility usage scenes: indoor rooms,
  hallways, kitchens, sidewalks, stores, classrooms, desks, cluttered environments,
  low-light, backlit, occluded objects, small/distant objects, close-to-camera objects,
  unusual angles, moving-camera video sequences. **This does not exist yet.** Open
  Images V7 is a corpus of static internet photos, not accessibility-scenario capture —
  it can approximate some of (B)'s visual conditions by chance (clutter, occlusion,
  distance are all present in it because the underlying photos vary), but it was never
  designed to represent how a blind/low-vision user's phone camera actually sees the
  world (handheld motion blur, chest-height framing, indoor low light, walking pace).
  Do not treat (A) results as a proxy for how well OmniSight performs in real use. See
  Section 8 for the concrete human-collection pathway to eventually build (B).

## 2. Dataset used: Open Images V7 (validation split), small subset

- **Source**: Google's Open Images V7, downloaded via `fiftyone.zoo.load_zoo_dataset`
  (FiftyOne's managed OIV7 loader), split=`validation`.
- **Why**: only source we have on Windows that (a) is CC-licensed, (b) has real,
  human-drawn bounding boxes with occlusion/truncation/group-of attributes (not
  auto-generated), (c) already contains exact-name overlap with the shipped model's
  601-class vocabulary (the model IS trained on OIV7), so ground-truth class names match
  the model's output classes with no remapping/synonym risk.
- **How it was pulled**: `benchmark/build_dataset.py`, run via
  `uv run python -m benchmark.build_dataset`. For each target class (see Section 4),
  it calls `foz.load_zoo_dataset(..., classes=[class_name], max_samples=40, shuffle=True,
  seed=42)`, copies each newly-seen image into `data/raw/eval/<ImageID>.jpg`, and
  accumulates the FULL set of ground-truth boxes fiftyone attaches to that image (Open
  Images is exhaustively multi-labeled per image — pulling "Car" also yields any other
  annotated classes present in that same photo, e.g. "Person", "Wheel", "Window"). This
  is why the final manifest's class list (>100 distinct class names) is much broader
  than the ~28 explicitly queried target classes.
- **Actual size achieved**: **380 images**, **4,916 ground-truth boxes**, in
  `data/manifests/eval_manifest.jsonl`. Within the spec's "roughly 150-400 images"
  target range.

## 3. License verification — what was checked, and how

Verified 2026-09-04 via `WebFetch` against
`https://storage.googleapis.com/openimages/web/factsfigures_v7.html` (Google's own
current OIV7 facts/figures page) and corroborated via web search of the published
`validation-images-with-rotation.csv` column schema. Do not rely on training-memory
claims about Open Images licensing — the terms below are quoted/paraphrased from that
live fetch, not recalled from a prior knowledge cutoff.

- **Images**: "The images are listed as having a CC BY 2.0 license. However... we make
  no representations or warranties regarding the license status of each image and you
  should verify the license for each image yourself" (Google's own disclaimer, quoted
  from the fetched page). Practically: OIV7 images are individually licensed by their
  original photographers (mostly Flickr uploads), predominantly CC BY 2.0, but Google
  explicitly does NOT guarantee this per-image.
- **Annotations (bounding boxes)**: "The annotations are licensed by Google LLC under
  CC BY 4.0 license." — unambiguous, single license, from Google directly.
- **Per-image attribution data**: Open Images publishes a separate CSV per split
  (`validation-images-with-rotation.csv` for the validation split) with columns
  `ImageID, Subset, OriginalURL, OriginalLandingURL, License, AuthorProfileURL, Author,
  Title, OriginalSize, OriginalMD5, Thumbnail300KURL, Rotation`. `ImageID` in that CSV
  is exactly the filename stem fiftyone uses locally (e.g. `9bd423a48a11f8bb.jpg` ->
  `ImageID=9bd423a48a11f8bb`), so per-image Author/License/OriginalURL lookup IS
  possible by joining on that ID — but only by downloading and parsing that CSV
  separately; it is NOT something we have done.
- **What fiftyone actually exposes (verified empirically, not assumed)**: loading OIV7
  via `foz.load_zoo_dataset(..., label_types=["detections"])` produces samples with only
  `filepath`, `tags`, `metadata` (unpopulated), and `ground_truth` (the `Detections`
  object with `label`, `bounding_box`, `IsOccluded`, `IsTruncated`, `IsGroupOf`,
  `IsDepiction`, `IsInside`). **No Author/License/OriginalURL fields are populated.**
  Confirmed by inspecting `Sample.field_names` on a real loaded sample — see git history
  of this session for the exact probe command/output if needed.
- **Consequence for this benchmark**: since fiftyone does not expose per-image
  attribution, and since this benchmark never redistributes images (`data/raw/` is
  gitignored — images stay local-only, used purely for internal accuracy evaluation),
  each manifest record's `license` field carries the **dataset-level** terms (CC BY 2.0
  for the image, CC BY 4.0 for the annotation) plus an explicit note that per-image
  attribution has NOT been resolved and would require the CSV join above before any
  future redistribution. This is intentional, documented, and matches the Phase B spec's
  explicit fallback instruction — no per-image attribution is fabricated.
- **Redistribution policy for this repo**: never redistribute `data/raw/` images. They
  are gitignored and must stay that way. If a future need arises to publish/share any
  of these images outside this local evaluation, resolve per-image attribution via the
  CSV join first.

## 4. Classes and actual achieved counts

Class list and hazard/general split are defined in `benchmark/config.py`
(`HAZARD_CLASS_MAP`, `GENERAL_CLASSES_OIV7`, `ALL_TARGET_CLASSES_OIV7`).
Hazard classes are queried FIRST (see ordering note in `config.py`) so they are
guaranteed real coverage before the image budget is spent on general classes.

### Hazard classes (OmniSight's `hazardClasses` set, mapped to OIV7 names)

| OmniSight name | OIV7 name  | Images explicitly queried | GT boxes in final manifest |
|---|---|---|---|
| person     | Person     | 40 | 303 |
| car        | Car        | 38 | 148 |
| truck      | Truck      | 40 | 42  |
| bus        | Bus        | 27 | 49  |
| bicycle    | Bicycle    | 28 | 78  |
| motorcycle | Motorcycle | 36 | 49  |
| stairs     | Stairs     | 36 | 45  |
| dog        | Dog        | 38 | 52  |

**All 8 hazard classes have nonzero coverage.** Contrary to an initial (unverified)
assumption during planning that "Stairs" might have zero OIV7 examples, it does exist
as a real OIV7 class and achieved 45 ground-truth boxes across 36 images — this was
confirmed empirically by running the actual download, not assumed. `Truck` (42 boxes),
`Bus`/`Motorcycle` (49 boxes each), and especially `Stairs` (45 boxes) are the thinnest
hazard classes — treat their per-class metrics as materially lower-confidence than
`Person` (303) or `Car` (148); a handful of additional misses/hits swings a
recall/precision number computed on ~45-50 boxes far more than the same handful would
move a number computed on 303. **Do not present `Stairs`' recall with the same implied
statistical confidence as `Person`'s** in any report or dashboard derived from this
dataset — see `reports/baseline/BASELINE_SCORECARD.md` for the GT-count-inline
convention this project uses to keep that visible.

**This 380-image, single-pull benchmark is an initial baseline, not a definitive or
final measurement.** It is large enough to support real, actionable per-class findings
for the higher-count hazard classes (Person, Car, Bicycle) but should be treated as a
first snapshot to validate the harness and surface obvious weak spots — not as a
statistically saturated evaluation. Expanding coverage (Section 5) and eventually adding
the human-collected OmniSight-specific dataset (Section 8) are both expected next steps,
not optional polish.

### General classes (broader precision/recall spread, common indoor/outdoor objects)

Queried: Chair, Table, Couch, Door, Backpack, Bottle, Laptop, Cabinetry, Traffic sign,
Bench, Umbrella, Handbag, Trash can, Houseplant, Book, Cat, Bicycle wheel, Window,
Wheelchair (plus "Stairs", shared with the hazard set).

The 380-image budget (`TARGET_TOTAL_IMAGES` in `benchmark/config.py`) was exhausted
after **Chair (38), Table (28), Couch (31)** — the remaining general classes (Door,
Backpack, Bottle, Laptop, Cabinetry, Traffic sign, Bench, Umbrella, Handbag, Trash can,
Houseplant, Book, Cat, Bicycle wheel, Window, Wheelchair) were **not explicitly
queried** in this run, though several still appear incidentally in the final manifest
(e.g. Book: 72 boxes, Window: 211 boxes, Bottle: 1 box) because Open Images' exhaustive
per-image labeling surfaced them in photos pulled for other classes. See Section 5 to
expand coverage of the un-queried classes.

### Full observed class list

Because Open Images labels every annotated object in a photo (not just the class it was
queried for), the final manifest actually contains **>100 distinct class names** far
beyond the ~28 explicitly targeted — including OIV7 hierarchy "ancestor" classes like
`Mammal`, `Land vehicle`, `Human body`, `Human head`, `Vehicle`, `Furniture`. These are
real ground truth (Open Images' own hierarchical ontology), not fabricated — but note in
`reports/baseline/Baseline_Report.md` that the shipped model, despite having these exact
601 classes in its output vocabulary (confirmed via `model.names`), predicts essentially
none of these coarse/ancestor classes at the conf=0.4 operating point — a genuine,
observed model behavior, not a benchmark bug. Exact per-class GT/prediction counts are
in `benchmark/results/baseline/per_class.json`.

## 5. How to expand this dataset later

- **More images per class**: raise `MAX_SAMPLES_PER_CLASS` in `benchmark/config.py`
  (currently 40) and/or `TARGET_TOTAL_IMAGES` (currently 380), then re-run
  `uv run python -m benchmark.build_dataset`. The script is idempotent — it skips
  re-copying images already present in `data/raw/eval/` and rebuilds the manifest from
  scratch each run (dedupes by `sample_id`).
- **More classes**: add class names (exact OIV7 Titlecase spelling) to
  `GENERAL_CLASSES_OIV7` in `benchmark/config.py`. To get the un-queried general classes
  from Section 4 real coverage, either raise `TARGET_TOTAL_IMAGES` enough to not exit
  early, or reorder `GENERAL_CLASSES_OIV7` to prioritize them.
- **A held-out slice for future training-time comparisons**: if a future need arises to
  compare fine-tuned vs. baseline models, do NOT silently reuse this eval set. Build a
  SEPARATE manifest (e.g. `data/manifests/heldout_manifest.jsonl`) sourced from
  DIFFERENT images (different `seed`, or Open Images' `test` split instead of
  `validation`), and explicitly document the decision to retire any portion of the
  current eval set, per the isolation requirement in `benchmark/dataset.py`
  (`assert_eval_only`).

## 6. Test/train isolation

This is an **eval-only** dataset. `benchmark/dataset.py`'s `Sample` dataclass hard-
rejects any `split` value other than `"eval"` at construction time (see
`Sample.__post_init__`), and `assert_eval_only()` is a defense-in-depth guard any future
code path must call before treating a manifest as usable. There is no `data/train/`
directory, and none is planned in this phase. If a fine-tuning effort ever begins, it
must use a newly built, separately-tracked dataset — not this one.

## 7. Manifest schema

One JSON object per line in `data/manifests/eval_manifest.jsonl`:

```jsonc
{
  "sample_id": "oiv7-9bd423a48a11f8bb",   // stable ID, "oiv7-" + Open Images ImageID
  "source": "open-images-v7-validation",
  "filename": "9bd423a48a11f8bb.jpg",      // relative to data/raw/eval/
  "split": "eval",                          // ALWAYS "eval" — see Section 6
  "labels": [
    {
      "class_name": "Dog",                  // exact OIV7 Titlecase name
      "bbox": [0.267, 0.150, 0.732, 0.761],  // [x, y, w, h], normalized, top-left origin
      "is_occluded": false,
      "is_truncated": true,
      "is_group_of": false
    }
  ],
  "scene_category": "indoor_room_heuristic", // see heuristic definition below — NOT real ground truth
  "lighting_category": "unknown",            // Open Images provides no lighting label — never guessed
  "difficulty": "medium",                    // deterministic formula, see below
  "license": {
    "type": "CC BY 2.0 (dataset-level; per-image not individually resolved)",
    "attribution": "... (see Section 3) ...",
    "source_url": "https://storage.googleapis.com/openimages/web/factsfigures_v7.html"
  }
}
```

### `scene_category` heuristic (documented, not fabricated)

Computed in `benchmark/build_dataset.py::_scene_category_heuristic`, from the SET of
real ground-truth class names present in that image, against two fixed keyword sets:
- outdoor-associated: `{Car, Bus, Truck, Bicycle, Motorcycle, Traffic sign, Bench}`
- indoor-associated: `{Chair, Table, Couch, Cabinetry, Door, Book, Laptop, Window}`

Result: `outdoor_street_heuristic` (only outdoor keywords present), `indoor_room_
heuristic` (only indoor keywords present), `mixed_or_ambiguous` (both), or
`unclassified` (neither). This is a coarse proxy for scene type derived purely from
co-occurring object labels — it is NOT a human-verified scene label and should never be
read as ground truth about the actual physical environment.

### `difficulty` heuristic (documented formula)

Computed in `benchmark/build_dataset.py::_difficulty_heuristic` from real per-box
signals only:
- +1 if the image has more than 5 annotated boxes (clutter)
- +1 if any box covers less than 2% of image area (small/distant object)
- +1 if any box is `IsOccluded` or `IsTruncated`
- +1 if any box is `IsGroupOf`

Score 0 -> `"easy"`, 1-2 -> `"medium"`, 3+ -> `"hard"`.

## 8. Future: human-collected OmniSight-specific dataset (the real (B))

Open Images V7 can never substitute for real accessibility-scenario capture. When
resources allow, the concrete future pathway is:

1. **Staged capture sessions** covering the (B) list from Section 1: indoor rooms,
   hallways, kitchens, sidewalks, stores, classrooms, desks; deliberately cluttered
   scenes; low-light and backlit conditions; partially occluded objects; small/distant
   and very-close objects; unusual camera angles (low/high/tilted); ideally short video
   clips (not just stills) so temporal metrics (tracking stability, announcement
   latency) become measurable for the first time.
2. **Controlled variation**: multiple distances (0.5m/1m/2m/5m), multiple lighting
   conditions per scene (daylight, indoor artificial, dusk/backlit), multiple approach
   angles.
3. **No PII automation**: this is explicitly a human-in-the-loop step. Do NOT build any
   automated pipeline that uploads, distributes, or processes personally identifiable
   imagery (faces of bystanders, house numbers, license plates, etc.) without direct
   human review and consent at capture time. Capture should favor staged/consenting
   participants and controlled environments over incidental public capture.
4. **Drop-in process into the existing manifest schema** (Section 7 above was designed
   for exactly this extensibility):
   - Place new images under `data/raw/<new_source_name>/` (a new subdirectory, e.g.
     `data/raw/omnisight_captured/`), keeping filenames stable and unique.
   - Hand-annotate (or semi-automate with a human review pass) bounding boxes in the
     same `[x, y, w, h]` normalized top-left format used throughout this schema.
   - Append new records to a NEW manifest file, e.g.
     `data/manifests/omnisight_captured_manifest.jsonl`, using `source:
     "omnisight-human-captured"`, `split: "eval"` (still eval-only — see Section 6),
     real `lighting_category` values now that they're actually knowable (e.g.
     `"daylight_indoor"`, `"low_light"`, `"backlit"` — define an explicit enum when this
     work starts, rather than reusing `"unknown"`), and a `scene_category` that can now
     be a real human-assigned label instead of the OIV7 co-occurrence heuristic.
   - `benchmark/dataset.py::load_manifest` can load multiple manifest files
     independently (or they can be concatenated) — no schema change needed to combine
     Open Images and human-captured samples in one evaluation run; `evaluate.py` would
     just need to be pointed at (or extended to merge) both manifest paths.
5. This step is NOT started in Phase B and is out of scope per the "no autonomous
   research" stop condition — it requires direct human effort (capture + annotation)
   that cannot be automated by this benchmark tooling.
