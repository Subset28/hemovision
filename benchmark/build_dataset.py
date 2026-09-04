"""Build the small OIV7-derived eval dataset: pulls images+detections via
fiftyone's Open Images V7 zoo loader, copies images into data/raw/eval/,
computes scene_category/difficulty heuristics from REAL per-box signals, and
writes data/manifests/eval_manifest.jsonl.

Run with: uv run python -m benchmark.build_dataset

LICENSING (see docs/DATASETS.md for full detail):
  - Open Images V7 images: predominantly CC BY 2.0, individually licensed;
    Google explicitly disclaims warranting each image's license status.
  - Annotations (bounding boxes): CC BY 4.0, Google LLC.
  - fiftyone's zoo loader does NOT expose per-image Author/License/OriginalURL
    fields (verified empirically — see docs/DATASETS.md) — only `ground_truth`
    detections and `filepath` are populated. Per-image attribution, if ever
    needed for redistribution, must be looked up separately from Open Images'
    own `validation-images-with-rotation.csv` (columns: ImageID, OriginalURL,
    OriginalLandingURL, License, Author, AuthorProfileURL, Title), keyed by the
    image filename stem (which IS the Open Images ImageID). This benchmark
    does not redistribute images — they stay local under data/raw/ (gitignored)
    — so per-image attribution is recorded as "not resolved; dataset-level
    terms apply" rather than fabricated.

This dataset is EVAL-ONLY. split is hard-fixed to "eval" (see benchmark/dataset.py).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from benchmark.config import (
    ALL_TARGET_CLASSES_OIV7,
    HAZARD_CLASSES_OIV7,
    MANIFEST_DIR,
    MAX_SAMPLES_PER_CLASS,
    RANDOM_SEED,
    RAW_IMAGE_DIR,
    EVAL_MANIFEST_PATH,
    TARGET_TOTAL_IMAGES,
)
from benchmark.dataset import BoxLabel, Sample, save_manifest

OIV7_IMAGE_LICENSE = {
    "type": "CC BY 2.0 (dataset-level; per-image not individually resolved)",
    "attribution": (
        "Open Images V7 images are individually licensed by their original "
        "photographers, predominantly under CC BY 2.0. Google LLC explicitly "
        "disclaims warranting the license status of any individual image. "
        "This benchmark does not redistribute images (data/raw/ is gitignored, "
        "local-only). Per-image Author/OriginalURL attribution, if ever needed, "
        "must be looked up in Open Images' validation-images-with-rotation.csv "
        "keyed by ImageID (= image filename stem) — see docs/DATASETS.md."
    ),
    "source_url": "https://storage.googleapis.com/openimages/web/factsfigures_v7.html",
}

ANNOTATION_LICENSE_NOTE = "Annotations (bounding boxes) are CC BY 4.0, Google LLC."

# Heuristic scene-category keyword sets, derived only from real ground-truth
# class labels present in the image (documented methodology — NOT fabricated
# scene ground truth; Open Images provides no scene/room label at all).
_OUTDOOR_STREET_CLASSES = {"Car", "Bus", "Truck", "Bicycle", "Motorcycle", "Traffic sign", "Bench"}
_INDOOR_ROOM_CLASSES = {"Chair", "Table", "Couch", "Cabinetry", "Door", "Book", "Laptop", "Window"}


def _scene_category_heuristic(class_names: set) -> str:
    """Heuristic ONLY: derived from which of a fixed keyword set of OIV7 class
    names appear as ground truth in the image. Not real scene ground truth —
    Open Images V7 provides no room/scene label. An image with both outdoor-
    and indoor-associated classes is tagged 'mixed_or_ambiguous'; an image with
    neither is 'unclassified' (not "unknown" so it's distinguishable from the
    lighting_category, which really is unknown for a different reason)."""
    has_outdoor = bool(class_names & _OUTDOOR_STREET_CLASSES)
    has_indoor = bool(class_names & _INDOOR_ROOM_CLASSES)
    if has_outdoor and has_indoor:
        return "mixed_or_ambiguous"
    if has_outdoor:
        return "outdoor_street_heuristic"
    if has_indoor:
        return "indoor_room_heuristic"
    return "unclassified"


def _difficulty_heuristic(labels: list) -> str:
    """Deterministic difficulty score from real per-box signals:
      +1 if image has > 5 annotated boxes (clutter)
      +1 if any box covers < 2% of image area (small/distant object)
      +1 if any box is IsOccluded or IsTruncated
      +1 if any box is IsGroupOf (ambiguous multi-instance box)
    Score 0 -> 'easy', 1-2 -> 'medium', 3+ -> 'hard'."""
    score = 0
    if len(labels) > 5:
        score += 1
    if any((l.bbox[2] * l.bbox[3]) < 0.02 for l in labels):
        score += 1
    if any(l.is_occluded or l.is_truncated for l in labels):
        score += 1
    if any(l.is_group_of for l in labels):
        score += 1
    if score == 0:
        return "easy"
    if score <= 2:
        return "medium"
    return "hard"


def build() -> None:
    import fiftyone as fo
    import fiftyone.zoo as foz

    RAW_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    class_counts: dict = {}
    samples: list = []
    seen_ids: set = set()

    print(f"Target classes ({len(ALL_TARGET_CLASSES_OIV7)}): {ALL_TARGET_CLASSES_OIV7}")

    for class_name in ALL_TARGET_CLASSES_OIV7:
        dataset_name = f"omnisight_eval_probe_{class_name.replace(' ', '_')}"
        try:
            fo.delete_dataset(dataset_name)
        except Exception:
            pass
        try:
            d = foz.load_zoo_dataset(
                "open-images-v7",
                split="validation",
                label_types=["detections"],
                classes=[class_name],
                max_samples=MAX_SAMPLES_PER_CLASS,
                shuffle=True,
                seed=RANDOM_SEED,
                dataset_name=dataset_name,
            )
        except Exception as e:
            print(f"  [{class_name}] FAILED to load: {e}")
            class_counts[class_name] = 0
            continue

        n_added_for_class = 0
        for fo_sample in d:
            src_path = Path(fo_sample.filepath)
            image_id = src_path.stem
            sample_id = f"oiv7-{image_id}"

            gt = fo_sample.ground_truth
            if gt is None or not gt.detections:
                continue

            labels = []
            for det in gt.detections:
                x, y, w, h = det.bounding_box
                # clamp to [0,1] defensively (Open Images boxes are already
                # normalized top-left [x,y,w,h], but guard against float drift)
                x = max(0.0, min(1.0, x))
                y = max(0.0, min(1.0, y))
                w = max(1e-6, min(1.0 - x, w))
                h = max(1e-6, min(1.0 - y, h))
                labels.append(
                    BoxLabel(
                        class_name=det.label,
                        bbox=(x, y, w, h),
                        is_occluded=bool(det.get_field("IsOccluded") or False),
                        is_truncated=bool(det.get_field("IsTruncated") or False),
                        is_group_of=bool(det.get_field("IsGroupOf") or False),
                    )
                )

            if sample_id in seen_ids:
                # already added while pulling a different class (images can
                # carry multiple target classes) — skip re-adding
                continue

            dest_filename = f"{image_id}.jpg"
            dest_path = RAW_IMAGE_DIR / dest_filename
            if not dest_path.exists():
                shutil.copy2(src_path, dest_path)

            class_names_in_image = {l.class_name for l in labels}
            sample = Sample(
                sample_id=sample_id,
                source="open-images-v7-validation",
                filename=dest_filename,
                split="eval",
                labels=tuple(labels),
                scene_category=_scene_category_heuristic(class_names_in_image),
                lighting_category="unknown",
                difficulty=_difficulty_heuristic(labels),
                license=OIV7_IMAGE_LICENSE,
            )
            samples.append(sample)
            seen_ids.add(sample_id)
            n_added_for_class += 1

            if len(samples) >= TARGET_TOTAL_IMAGES:
                break

        class_counts[class_name] = n_added_for_class
        print(f"  [{class_name}] +{n_added_for_class} new images (total so far: {len(samples)})")

        try:
            fo.delete_dataset(dataset_name)
        except Exception:
            pass

        if len(samples) >= TARGET_TOTAL_IMAGES:
            print(f"Reached target of {TARGET_TOTAL_IMAGES} images, stopping early.")
            break

    save_manifest(samples, EVAL_MANIFEST_PATH)
    print(f"\nWrote {len(samples)} samples to {EVAL_MANIFEST_PATH}")
    print("\nPer-class image counts (images newly contributed while pulling that class):")
    for cname in ALL_TARGET_CLASSES_OIV7:
        marker = " (HAZARD)" if cname in HAZARD_CLASSES_OIV7 else ""
        print(f"  {cname:20s}{marker:10s}: {class_counts.get(cname, 0)}")

    # ground-truth box counts per class across the final manifest (more useful
    # for eval than "images contributed", since one image can hold many boxes
    # of many classes)
    box_counts: dict = {}
    for s in samples:
        for l in s.labels:
            box_counts[l.class_name] = box_counts.get(l.class_name, 0) + 1
    print("\nGround-truth BOX counts per class in final manifest:")
    for cname in sorted(box_counts, key=lambda c: -box_counts[c]):
        marker = " (HAZARD)" if cname in HAZARD_CLASSES_OIV7 else ""
        print(f"  {cname:20s}{marker:10s}: {box_counts[cname]}")
    for hz in HAZARD_CLASSES_OIV7:
        if hz not in box_counts:
            print(f"  {hz:20s} (HAZARD)  : 0  <-- NO EXAMPLES ACHIEVED")


if __name__ == "__main__":
    build()
