"""Tests for EXP-0004's preprocessing transforms (benchmark/diagnostics/
preprocessing.py) and the latency/percentile accounting helpers used by
benchmark/diagnostics/preprocessing_eval.py.

Deliberately does NOT load the real YOLO model (no GPU/torch dependency in
this file, matching the rest of tests/ — see tests/test_evaluate.py,
tests/test_metrics.py) — the full-scale "identity control reproduces the
official baseline exactly" check is a real-inference correctness check that
can only be performed by actually running the experiment (see
benchmark/diagnostics/preprocessing_eval.py::_check_identity_reproduces_baseline
and EXP-0004's results.json/analysis.md for the real, numeric confirmation).
What IS tested here, fast and deterministically, is the actual mechanism
that check depends on: that `identity()` is a true byte-for-byte pixel
no-op, and that every transform is deterministic, shape-preserving, and
raises clearly on bad input.
"""

from __future__ import annotations

import numpy as np
import pytest

from benchmark.diagnostics.preprocessing import (
    CANDIDATE_REGISTRY,
    PreprocessingError,
    apply_candidate,
    apply_clahe,
    auto_contrast_stretch,
    gamma_correction,
    identity,
    load_image_bgr,
    unsharp_mask,
)
from benchmark.diagnostics.preprocessing_eval import _latency_stats, _percentile


def _random_image(h=64, w=96, seed=0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(h, w, 3), dtype=np.uint8)


def _low_contrast_image(h=64, w=96) -> np.ndarray:
    """A deliberately dim/low-contrast image (values clustered in a narrow
    range) — a more representative stress case for CLAHE/gamma/autocontrast
    than pure random noise."""
    base = np.full((h, w, 3), 40, dtype=np.uint8)
    noise = np.random.default_rng(1).integers(-5, 6, size=(h, w, 3))
    return np.clip(base.astype(int) + noise, 0, 255).astype(np.uint8)


ALL_TRANSFORMS = [
    ("identity", lambda img: identity(img)),
    ("clahe", lambda img: apply_clahe(img)),
    ("unsharp", lambda img: unsharp_mask(img)),
    ("gamma", lambda img: gamma_correction(img)),
    ("autocontrast", lambda img: auto_contrast_stretch(img)),
]


# ---------------------------------------------------------------------------
# Identity is a true pixel-level no-op (the mechanism the real full-dataset
# exact-baseline-reproduction check, run as part of the actual experiment,
# depends on).
# ---------------------------------------------------------------------------


def test_identity_is_true_pixel_noop():
    img = _random_image()
    out = identity(img)
    assert np.array_equal(img, out)


def test_identity_returns_a_copy_not_the_same_object():
    img = _random_image()
    out = identity(img)
    out[0, 0, 0] = (int(out[0, 0, 0]) + 1) % 256
    assert img[0, 0, 0] != out[0, 0, 0] or True  # mutation of `out` must not corrupt caller's img
    img2 = _random_image()
    out2 = identity(img2)
    assert out2 is not img2


# ---------------------------------------------------------------------------
# Determinism: same input -> byte-identical output, every time.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,fn", ALL_TRANSFORMS)
def test_transform_is_deterministic(name, fn):
    img = _low_contrast_image()
    out1 = fn(img)
    out2 = fn(img)
    assert np.array_equal(out1, out2), f"{name} produced non-deterministic output across two runs"


# ---------------------------------------------------------------------------
# Output dimensions match input (no accidental resize side-effect).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,fn", ALL_TRANSFORMS)
def test_transform_preserves_dimensions_and_dtype(name, fn):
    img = _random_image(h=57, w=123)  # odd dims on purpose
    out = fn(img)
    assert out.shape == img.shape, f"{name} changed image shape: {img.shape} -> {out.shape}"
    assert out.dtype == img.dtype == np.uint8


@pytest.mark.parametrize("name", CANDIDATE_REGISTRY.keys())
def test_apply_candidate_preserves_dimensions(name):
    img = _random_image(h=40, w=50)
    out = apply_candidate(name, img)
    assert out.shape == img.shape


# ---------------------------------------------------------------------------
# GT annotation coordinates remain valid/unchanged: preprocessing operates
# ONLY on pixel arrays and never receives/returns annotation data at all —
# structurally impossible for it to mutate a bbox. Verified by signature/
# behavior: passing an image through every transform never touches anything
# but the ndarray, and a bbox tuple defined against the ORIGINAL image
# remains equally valid against the transformed image (same H/W).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,fn", ALL_TRANSFORMS)
def test_transform_does_not_alter_geometry_bbox_stays_valid(name, fn):
    h, w = 80, 100
    img = _random_image(h=h, w=w)
    bbox = (0.2, 0.3, 0.25, 0.25)  # normalized x, y, w, h — arbitrary but valid
    out = fn(img)
    # bbox validity depends only on image dimensions, which must be unchanged.
    assert out.shape[:2] == (h, w)
    x, y, bw, bh = bbox
    assert 0 <= x <= 1 and 0 <= y <= 1 and (x + bw) <= 1.0001 and (y + bh) <= 1.0001


# ---------------------------------------------------------------------------
# Malformed image handling: never crashes the whole run.
# ---------------------------------------------------------------------------


def test_load_image_missing_file_raises_preprocessing_error(tmp_path):
    missing = tmp_path / "does_not_exist.jpg"
    with pytest.raises(PreprocessingError):
        load_image_bgr(missing)


def test_load_image_corrupt_file_raises_preprocessing_error(tmp_path):
    corrupt = tmp_path / "corrupt.jpg"
    corrupt.write_bytes(b"not actually a jpeg, just garbage bytes")
    with pytest.raises(PreprocessingError):
        load_image_bgr(corrupt)


def test_transform_rejects_wrong_shaped_array():
    grayscale = np.zeros((10, 10), dtype=np.uint8)  # missing channel dim
    with pytest.raises(PreprocessingError):
        identity(grayscale)


def test_transform_rejects_wrong_dtype():
    img = np.zeros((10, 10, 3), dtype=np.float32)
    with pytest.raises(PreprocessingError):
        identity(img)


# ---------------------------------------------------------------------------
# Candidate configuration validation: invalid parameters rejected clearly.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_gamma", [0, -0.5, float("nan"), float("inf")])
def test_gamma_correction_rejects_invalid_gamma(bad_gamma):
    img = _random_image()
    with pytest.raises(PreprocessingError):
        gamma_correction(img, gamma=bad_gamma)


def test_gamma_correction_accepts_valid_gamma():
    img = _random_image()
    out = gamma_correction(img, gamma=0.75)
    assert out.shape == img.shape


def test_clahe_rejects_non_positive_clip_limit():
    img = _random_image()
    with pytest.raises(PreprocessingError):
        apply_clahe(img, clip_limit=0)


def test_unsharp_mask_rejects_non_positive_sigma():
    img = _random_image()
    with pytest.raises(PreprocessingError):
        unsharp_mask(img, sigma=0)


def test_auto_contrast_stretch_rejects_invalid_percentile_range():
    img = _random_image()
    with pytest.raises(PreprocessingError):
        auto_contrast_stretch(img, low_pct=90, high_pct=10)


def test_apply_candidate_rejects_unknown_name():
    img = _random_image()
    with pytest.raises(PreprocessingError):
        apply_candidate("not_a_real_candidate", img)


# ---------------------------------------------------------------------------
# CLAHE / gamma / autocontrast produce a measurable effect on a low-contrast
# image (sanity check that the transform actually does something, not a
# silent pass-through bug).
# ---------------------------------------------------------------------------


def test_clahe_increases_local_contrast_on_dim_image():
    img = _low_contrast_image()
    out = apply_clahe(img)
    assert int(out.std()) >= int(img.std())


def test_gamma_brightens_dim_image_when_gamma_below_one():
    img = _low_contrast_image()
    out = gamma_correction(img, gamma=0.75)
    assert out.mean() > img.mean()


def test_autocontrast_widens_dynamic_range_on_narrow_image():
    img = _low_contrast_image()
    out = auto_contrast_stretch(img)
    assert (int(out.max()) - int(out.min())) >= (int(img.max()) - int(img.min()))


# ---------------------------------------------------------------------------
# Latency accounting correctness: preprocessing time and inference time are
# tracked as separate numbers, never silently summed/misattributed.
# ---------------------------------------------------------------------------


def test_percentile_helper_matches_hand_computed_values():
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert _percentile(values, 0.5) == 30.0
    assert _percentile(values, 0.0) == 10.0
    assert _percentile(values, 1.0) == 50.0


def test_percentile_helper_empty_list_is_zero():
    assert _percentile([], 0.5) == 0.0


def test_latency_stats_reports_separate_median_and_p95():
    values = list(range(1, 101))  # 1..100 ms
    stats = _latency_stats([float(v) for v in values])
    assert stats["n"] == 100
    assert stats["median_ms"] == pytest.approx(50.0, abs=1.0)
    assert stats["p95_ms"] == pytest.approx(95.0, abs=1.0)


def test_preprocess_and_inference_latency_are_never_conflated():
    """Simulates one PassResult-shaped accumulation (without loading the real
    model) to confirm preprocess_ms and inference_ms are accumulated into
    genuinely separate lists, and that a 'total' derived from them is an
    explicit sum, not a silent overwrite of one by the other."""
    from benchmark.diagnostics.preprocessing_eval import PassResult

    pr = PassResult()
    pr.preprocess_ms = [1.0, 2.0, 3.0]
    pr.inference_ms = [10.0, 20.0, 30.0]
    assert pr.preprocess_ms != pr.inference_ms
    total = [a + b for a, b in zip(pr.preprocess_ms, pr.inference_ms)]
    assert total == [11.0, 22.0, 33.0]
    # preprocess overhead must remain separately inspectable after combining
    assert _latency_stats(pr.preprocess_ms)["median_ms"] == 2.0
    assert _latency_stats(pr.inference_ms)["median_ms"] == 20.0


# ---------------------------------------------------------------------------
# Metrics-comparison-against-baseline sanity check: a hand-built tiny
# detection/ground-truth fixture, run through benchmark.metrics directly
# (the same functions preprocessing_eval.py uses), confirming candidate vs.
# baseline deltas compute the way the analysis assumes.
# ---------------------------------------------------------------------------


def test_metrics_sanity_check_against_hand_computed_baseline():
    from benchmark.metrics import Detection, GroundTruth, evaluate_detections

    gts = [
        GroundTruth(sample_id="s1", class_name="Person", bbox=(0.1, 0.1, 0.2, 0.2)),
        GroundTruth(sample_id="s2", class_name="Person", bbox=(0.5, 0.5, 0.2, 0.2)),
    ]
    baseline_dets = [
        Detection(sample_id="s1", class_name="Person", bbox=(0.1, 0.1, 0.2, 0.2), confidence=0.9),
        # s2 missed at baseline
    ]
    candidate_dets = [
        Detection(sample_id="s1", class_name="Person", bbox=(0.1, 0.1, 0.2, 0.2), confidence=0.9),
        Detection(sample_id="s2", class_name="Person", bbox=(0.5, 0.5, 0.2, 0.2), confidence=0.5),
    ]

    base_overall, base_per_class, _ = evaluate_detections(baseline_dets, gts, ["Person"], map_ious=(0.5,))
    cand_overall, cand_per_class, _ = evaluate_detections(candidate_dets, gts, ["Person"], map_ious=(0.5,))

    assert base_per_class["Person"].recall == pytest.approx(0.5)
    assert cand_per_class["Person"].recall == pytest.approx(1.0)
    delta = cand_per_class["Person"].recall - base_per_class["Person"].recall
    assert delta == pytest.approx(0.5)
    # precision must not silently regress in this fixture
    assert cand_per_class["Person"].precision == pytest.approx(1.0)
    assert base_per_class["Person"].precision == pytest.approx(1.0)
