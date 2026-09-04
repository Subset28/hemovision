"""Tests for benchmark/dataset.py: manifest schema, JSONL round-trip,
malformed-annotation rejection, duplicate detection, and eval/train isolation."""

import json
from pathlib import Path

import pytest

from benchmark.dataset import (
    BoxLabel,
    DatasetError,
    Sample,
    assert_eval_only,
    load_manifest,
    sample_from_dict,
    save_manifest,
)


def _valid_record(sample_id="s1", split="eval") -> dict:
    return {
        "sample_id": sample_id,
        "source": "open-images-v7",
        "filename": "s1.jpg",
        "split": split,
        "labels": [
            {
                "class_name": "Person",
                "bbox": [0.1, 0.1, 0.2, 0.3],
                "is_occluded": False,
                "is_truncated": False,
                "is_group_of": False,
            }
        ],
        "scene_category": "unknown",
        "lighting_category": "unknown",
        "difficulty": "easy",
        "license": {"type": "CC-BY 2.0", "attribution": None, "source_url": None},
    }


def test_valid_record_round_trips():
    sample = sample_from_dict(_valid_record())
    assert sample.sample_id == "s1"
    assert sample.split == "eval"
    assert len(sample.labels) == 1
    assert sample.labels[0].class_name == "Person"


def test_split_other_than_eval_is_rejected():
    with pytest.raises(DatasetError):
        sample_from_dict(_valid_record(split="train"))


def test_missing_required_field_is_rejected():
    bad = _valid_record()
    del bad["scene_category"]
    with pytest.raises(DatasetError):
        sample_from_dict(bad)


def test_malformed_bbox_wrong_length_is_rejected():
    bad = _valid_record()
    bad["labels"][0]["bbox"] = [0.1, 0.1, 0.2]  # only 3 elements
    with pytest.raises(DatasetError):
        sample_from_dict(bad)


def test_malformed_bbox_negative_size_is_rejected():
    bad = _valid_record()
    bad["labels"][0]["bbox"] = [0.1, 0.1, -0.2, 0.3]
    with pytest.raises(DatasetError):
        sample_from_dict(bad)


def test_malformed_bbox_out_of_range_is_rejected():
    bad = _valid_record()
    bad["labels"][0]["bbox"] = [0.9, 0.9, 0.5, 0.5]  # extends past 1.0
    with pytest.raises(DatasetError):
        sample_from_dict(bad)


def test_empty_class_name_is_rejected():
    bad = _valid_record()
    bad["labels"][0]["class_name"] = "  "
    with pytest.raises(DatasetError):
        sample_from_dict(bad)


def test_duplicate_annotation_within_sample_is_rejected():
    bad = _valid_record()
    bad["labels"] = [bad["labels"][0], dict(bad["labels"][0])]  # exact duplicate box+class
    with pytest.raises(DatasetError):
        sample_from_dict(bad)


def test_label_missing_field_is_rejected():
    bad = _valid_record()
    del bad["labels"][0]["is_group_of"]
    with pytest.raises(DatasetError):
        sample_from_dict(bad)


def test_manifest_round_trip_via_jsonl(tmp_path: Path):
    samples = [sample_from_dict(_valid_record("s1")), sample_from_dict(_valid_record("s2"))]
    manifest_path = tmp_path / "eval_manifest.jsonl"
    save_manifest(samples, manifest_path)
    loaded = load_manifest(manifest_path)
    assert len(loaded) == 2
    assert {s.sample_id for s in loaded} == {"s1", "s2"}


def test_manifest_load_rejects_duplicate_sample_ids(tmp_path: Path):
    manifest_path = tmp_path / "dup.jsonl"
    rec = _valid_record("dup1")
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
        f.write(json.dumps(rec) + "\n")
    with pytest.raises(DatasetError):
        load_manifest(manifest_path)


def test_manifest_load_rejects_invalid_json_line(tmp_path: Path):
    manifest_path = tmp_path / "bad.jsonl"
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write("{not valid json\n")
    with pytest.raises(DatasetError):
        load_manifest(manifest_path)


def test_manifest_load_reports_line_number_on_error(tmp_path: Path):
    manifest_path = tmp_path / "bad_line.jsonl"
    with open(manifest_path, "w", encoding="utf-8") as f:
        f.write(json.dumps(_valid_record("s1")) + "\n")
        bad = _valid_record("s2")
        del bad["scene_category"]
        f.write(json.dumps(bad) + "\n")
    with pytest.raises(DatasetError, match=r":2:"):
        load_manifest(manifest_path)


def test_assert_eval_only_passes_for_valid_manifest():
    samples = [sample_from_dict(_valid_record("s1"))]
    assert_eval_only(samples)  # should not raise


def test_assert_eval_only_rejects_any_non_eval_split_construct():
    # Since Sample.__post_init__ already blocks split != "eval" at construction
    # time, the isolation guard is exercised here by constructing a Sample the
    # only way a non-eval split value could arise: bypassing the dataclass
    # validation via object.__new__ + object.__setattr__ (simulating a future
    # code path that might construct Sample without going through
    # sample_from_dict). assert_eval_only must still catch it.
    valid = sample_from_dict(_valid_record("s1"))
    tampered = object.__new__(Sample)
    for k, v in valid.__dict__.items():
        object.__setattr__(tampered, k, v)
    object.__setattr__(tampered, "split", "train")
    with pytest.raises(DatasetError):
        assert_eval_only([tampered])
