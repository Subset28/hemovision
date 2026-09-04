"""Eval manifest schema + JSONL load/save/validation.

This is an EVAL-ONLY dataset. `split` is hard-fixed to "eval" everywhere in this
module — there is deliberately no "train" split concept anywhere in this package.
Per BENCHMARK_PLAN.md Phase B instructions: this data must never be used for
training or threshold-tuning without a separate, deliberate, documented decision
to retire it as an eval set (at which point it would need to be replaced, not
silently repurposed).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator

EVAL_SPLIT = "eval"  # the only split value this module will ever accept


class DatasetError(ValueError):
    """Raised for malformed manifest records: bad schema, duplicate annotations,
    wrong split, etc. Malformed records are never silently dropped."""


@dataclass(frozen=True)
class BoxLabel:
    class_name: str
    bbox: tuple  # (x, y, w, h) normalized, top-left origin
    is_occluded: bool
    is_truncated: bool
    is_group_of: bool

    def __post_init__(self):
        if len(self.bbox) != 4:
            raise DatasetError(f"bbox must have 4 elements, got {self.bbox!r}")
        x, y, w, h = self.bbox
        for name, v in (("x", x), ("y", y), ("w", w), ("h", h)):
            if not isinstance(v, (int, float)):
                raise DatasetError(f"bbox.{name} must be numeric, got {v!r}")
        if w <= 0 or h <= 0:
            raise DatasetError(f"bbox width/height must be > 0, got {self.bbox!r}")
        if x < 0 or y < 0 or (x + w) > 1.0001 or (y + h) > 1.0001:
            raise DatasetError(f"bbox must be normalized within [0,1], got {self.bbox!r}")
        if not self.class_name or not self.class_name.strip():
            raise DatasetError("class_name must be a non-empty string")


@dataclass(frozen=True)
class Sample:
    sample_id: str
    source: str
    filename: str  # path relative to data/raw/eval/
    split: str
    labels: tuple  # tuple[BoxLabel, ...]
    scene_category: str
    lighting_category: str
    difficulty: str
    license: dict  # {"type": str, "attribution": str | None, "source_url": str | None}

    def __post_init__(self):
        if self.split != EVAL_SPLIT:
            raise DatasetError(
                f"sample {self.sample_id!r}: split must be {EVAL_SPLIT!r}, got {self.split!r} "
                "— this manifest format only supports an eval-only dataset."
            )
        if not self.sample_id or not self.sample_id.strip():
            raise DatasetError("sample_id must be a non-empty string")
        if not self.filename:
            raise DatasetError(f"sample {self.sample_id!r}: filename must be non-empty")
        seen = set()
        for lbl in self.labels:
            key = (lbl.class_name, tuple(round(v, 6) for v in lbl.bbox))
            if key in seen:
                raise DatasetError(
                    f"sample {self.sample_id!r}: duplicate annotation for class "
                    f"{lbl.class_name!r} at bbox {lbl.bbox!r}"
                )
            seen.add(key)


def sample_to_dict(sample: Sample) -> dict:
    d = asdict(sample)
    d["labels"] = [dict(l) for l in [asdict(lbl) for lbl in sample.labels]]
    return d


def sample_from_dict(d: dict) -> Sample:
    required = {"sample_id", "source", "filename", "split", "labels", "scene_category",
                "lighting_category", "difficulty", "license"}
    missing = required - set(d.keys())
    if missing:
        raise DatasetError(f"manifest record missing required fields: {sorted(missing)}")

    labels = []
    for raw_lbl in d["labels"]:
        lbl_required = {"class_name", "bbox", "is_occluded", "is_truncated", "is_group_of"}
        lbl_missing = lbl_required - set(raw_lbl.keys())
        if lbl_missing:
            raise DatasetError(
                f"sample {d.get('sample_id')!r}: label missing required fields: {sorted(lbl_missing)}"
            )
        labels.append(
            BoxLabel(
                class_name=raw_lbl["class_name"],
                bbox=tuple(raw_lbl["bbox"]),
                is_occluded=bool(raw_lbl["is_occluded"]),
                is_truncated=bool(raw_lbl["is_truncated"]),
                is_group_of=bool(raw_lbl["is_group_of"]),
            )
        )

    return Sample(
        sample_id=d["sample_id"],
        source=d["source"],
        filename=d["filename"],
        split=d["split"],
        labels=tuple(labels),
        scene_category=d["scene_category"],
        lighting_category=d["lighting_category"],
        difficulty=d["difficulty"],
        license=d["license"],
    )


def load_manifest(path: Path) -> list:
    """Load and validate a JSONL manifest. Raises DatasetError on the first
    malformed record (with the line number) rather than silently skipping it."""
    samples = []
    seen_ids = set()
    with open(path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as e:
                raise DatasetError(f"{path}:{lineno}: invalid JSON: {e}") from e
            try:
                sample = sample_from_dict(raw)
            except DatasetError as e:
                raise DatasetError(f"{path}:{lineno}: {e}") from e
            if sample.sample_id in seen_ids:
                raise DatasetError(f"{path}:{lineno}: duplicate sample_id {sample.sample_id!r}")
            seen_ids.add(sample.sample_id)
            samples.append(sample)
    return samples


def save_manifest(samples: list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample_to_dict(sample), ensure_ascii=False) + "\n")


def iter_manifest(path: Path) -> Iterator[Sample]:
    for sample in load_manifest(path):
        yield sample


def assert_eval_only(samples: list) -> None:
    """Isolation guard: refuses to proceed if any sample claims a non-'eval'
    split. This is the check other code (e.g. a hypothetical future training
    script) MUST call before treating this manifest as usable — it exists so
    that eval data can never silently leak into a training reference."""
    for s in samples:
        if s.split != EVAL_SPLIT:
            raise DatasetError(
                f"isolation violation: sample {s.sample_id!r} has split={s.split!r}, "
                f"expected {EVAL_SPLIT!r}. This manifest must never be used as a "
                "training source under any split value other than 'eval'."
            )
