"""EXP-0004 (preprocessing): pure, deterministic image-preprocessing transforms
applied to a decoded image BEFORE it is handed to the model. Used ONLY by
benchmark/diagnostics/preprocessing_eval.py (a standalone diagnostic script) —
never imported by benchmark/evaluate.py or benchmark/model.py, and never
touches benchmark/config.py. No annotation/manifest data ever passes through
this module; it operates purely on pixel arrays.

All transforms:
  - take a BGR uint8 numpy array (cv2.imread's native format) and return a
    BGR uint8 numpy array of the SAME height/width/channel count (no resize,
    no letterboxing — that stays the model wrapper's job, applied identically
    for every candidate including the identity/no-op control).
  - are pure functions: same input array -> byte-identical output array,
    every time (no randomness, no hidden global state).
  - never mutate the input array in place (callers may reuse the source
    array for multiple candidates).

See experiments/*/EXP-0004/methodology.md (generated from the Experiment DB
record's evaluation_method field, research/seed_experiments.py) for the
pre-registered hypothesis/rationale/success-criteria for each candidate
below, written BEFORE this experiment's results were seen.
"""

from __future__ import annotations

import numpy as np

try:
    import cv2
except ImportError as e:  # pragma: no cover - environment guard
    raise ImportError(
        "opencv-python (cv2) is required for benchmark/diagnostics/preprocessing.py"
    ) from e


class PreprocessingError(ValueError):
    """Raised for invalid preprocessing parameters or malformed input images.
    Never silently swallowed — callers (preprocessing_eval.py) must catch
    this explicitly per-image and log/skip, not let it crash the whole run,
    and must reject bad *configuration* (e.g. an invalid gamma) immediately,
    not silently clamp it."""


def _validate_image(img: np.ndarray) -> None:
    if not isinstance(img, np.ndarray):
        raise PreprocessingError(f"expected a numpy ndarray, got {type(img)!r}")
    if img.ndim != 3 or img.shape[2] != 3:
        raise PreprocessingError(f"expected an HxWx3 BGR image, got shape {img.shape!r}")
    if img.dtype != np.uint8:
        raise PreprocessingError(f"expected dtype uint8, got {img.dtype!r}")


def load_image_bgr(path) -> np.ndarray:
    """Load an image file as a BGR uint8 array via cv2.imread — the SAME
    decode path ultralytics itself uses internally for a path source, so an
    identity transform fed back into the model is byte-for-byte equivalent
    to letting the model load the path directly (this is the mechanism the
    no-op/identity control run's exact-reproduction check in
    tests/test_preprocessing.py relies on).

    Raises PreprocessingError (never crashes the caller) for a missing or
    unreadable/corrupt file, so a single bad image cannot abort an entire
    380-image evaluation pass.
    """
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        raise PreprocessingError(f"image file does not exist: {p}")
    img = cv2.imread(str(p), cv2.IMREAD_COLOR)
    if img is None:
        raise PreprocessingError(f"cv2.imread could not decode image (corrupt/unreadable?): {p}")
    return img


# ---------------------------------------------------------------------------
# Candidate transforms
# ---------------------------------------------------------------------------


def identity(img: np.ndarray) -> np.ndarray:
    """No-op control: returns an unmodified copy. Feeding this back into the
    model must numerically reproduce the official baseline exactly — the
    correctness check required before trusting any other candidate's delta."""
    _validate_image(img)
    return img.copy()


def apply_clahe(img: np.ndarray, clip_limit: float = 2.0, tile_grid_size: int = 8) -> np.ndarray:
    """Contrast-limited adaptive histogram equalization, applied to the L
    (lightness) channel only in LAB color space (standard practice — CLAHE
    directly on BGR channels independently distorts hue/color balance).

    Hypothesis (pre-registered): improves LOCAL contrast in cluttered/dim
    regions, which may help LOW_CONFIDENCE_PERSON and LOCALIZATION_FAILURE
    cases where a person blends into a visually similar background.
    """
    _validate_image(img)
    if clip_limit <= 0:
        raise PreprocessingError(f"clip_limit must be > 0, got {clip_limit!r}")
    if tile_grid_size < 1:
        raise PreprocessingError(f"tile_grid_size must be >= 1, got {tile_grid_size!r}")
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=float(clip_limit), tileGridSize=(int(tile_grid_size), int(tile_grid_size)))
    l_eq = clahe.apply(l_channel)
    merged = cv2.merge((l_eq, a_channel, b_channel))
    out = cv2.cvtColor(merged, cv2.COLOR_LAB2BGR)
    return out


def unsharp_mask(img: np.ndarray, sigma: float = 1.0, amount: float = 0.5) -> np.ndarray:
    """Mild unsharp-mask sharpening: out = img + amount * (img - gaussian_blur(img, sigma)).

    Hypothesis (pre-registered): sharpens edges of small/distant people,
    potentially helping LOCALIZATION_FAILURE (tighter, higher-IoU boxes) and
    possibly a few small TRUE_DETECTOR_MISS cases where edge contrast is the
    limiting factor. Kept mild (amount=0.5) to avoid introducing halo
    artifacts/noise amplification that could hurt precision.
    """
    _validate_image(img)
    if sigma <= 0:
        raise PreprocessingError(f"sigma must be > 0, got {sigma!r}")
    if not (0.0 < amount <= 3.0):
        raise PreprocessingError(f"amount must be in (0, 3.0], got {amount!r}")
    blurred = cv2.GaussianBlur(img, ksize=(0, 0), sigmaX=float(sigma))
    sharpened = cv2.addWeighted(img, 1.0 + amount, blurred, -amount, 0)
    return sharpened


def gamma_correction(img: np.ndarray, gamma: float = 0.75) -> np.ndarray:
    """Power-law gamma correction: out = 255 * (in/255)^gamma. gamma < 1.0
    brightens (recovers shadow/underexposed detail); gamma > 1.0 darkens.

    Hypothesis (pre-registered): brightening (gamma in 0.7-0.8) recovers
    detail in underexposed regions, which may raise the model's confidence
    on Person detections currently sitting just under the 0.4 threshold in
    dark image areas (LOW_CONFIDENCE_PERSON).

    Rejects an invalid gamma clearly rather than silently clamping it —
    gamma must be a finite number > 0 (gamma <= 0 makes the power law
    undefined/degenerate).
    """
    _validate_image(img)
    if not isinstance(gamma, (int, float)) or isinstance(gamma, bool):
        raise PreprocessingError(f"gamma must be numeric, got {type(gamma)!r}")
    if not np.isfinite(gamma) or gamma <= 0:
        raise PreprocessingError(f"gamma must be a finite number > 0, got {gamma!r}")
    # out = 255 * (in/255)^gamma: for x in [0,1], gamma < 1 raises x towards 1
    # (brightens); gamma > 1 pushes x towards 0 (darkens). This is the direct
    # power-law convention (NOT the display-gamma "1/gamma" convention) —
    # chosen because the pre-registered hypothesis is stated in terms of
    # "gamma 0.7-0.8 brightens", which only holds under this convention.
    table = np.array([((i / 255.0) ** gamma) * 255.0 for i in range(256)], dtype=np.float64)
    table = np.clip(table, 0, 255).astype(np.uint8)
    return cv2.LUT(img, table)


def auto_contrast_stretch(img: np.ndarray, low_pct: float = 2.0, high_pct: float = 98.0) -> np.ndarray:
    """Per-image, per-channel percentile histogram stretch: clips the
    [low_pct, high_pct] percentile range of each BGR channel to [0, 255] and
    linearly rescales in between. Standardizes exposure across images with
    very different brightness/contrast ranges (a mild alternative to a hard
    min/max stretch, robust to a few outlier hot/dark pixels).

    Hypothesis (pre-registered): standardizes exposure variance across the
    dataset (mixed indoor/outdoor/lighting_category samples per
    data/manifests/eval_manifest.jsonl), which may reduce confidence
    variance for borderline Person detections without CLAHE's local
    (potentially noise-amplifying) behavior.
    """
    _validate_image(img)
    if not (0.0 <= low_pct < high_pct <= 100.0):
        raise PreprocessingError(f"require 0 <= low_pct < high_pct <= 100, got low={low_pct!r} high={high_pct!r}")
    out = np.empty_like(img)
    for c in range(3):
        channel = img[:, :, c].astype(np.float64)
        lo, hi = np.percentile(channel, [low_pct, high_pct])
        if hi <= lo:
            out[:, :, c] = img[:, :, c]
            continue
        stretched = (channel - lo) * (255.0 / (hi - lo))
        out[:, :, c] = np.clip(stretched, 0, 255).astype(np.uint8)
    return out


# ---------------------------------------------------------------------------
# Candidate registry — the pre-registered set (see module docstring). Order
# here is the reporting order used everywhere downstream.
# ---------------------------------------------------------------------------

CANDIDATE_REGISTRY: dict[str, dict] = {
    "identity": {
        "fn": identity,
        "params": {},
        "hypothesis": "No-op control — must reproduce the official baseline exactly.",
        "targets_buckets": [],
    },
    "clahe": {
        "fn": apply_clahe,
        "params": {"clip_limit": 2.0, "tile_grid_size": 8},
        "hypothesis": "Improves local contrast in cluttered/dim regions; may help "
                       "LOW_CONFIDENCE_PERSON and LOCALIZATION_FAILURE.",
        "targets_buckets": ["LOW_CONFIDENCE_PERSON", "LOCALIZATION_FAILURE"],
    },
    "unsharp": {
        "fn": unsharp_mask,
        "params": {"sigma": 1.0, "amount": 0.5},
        "hypothesis": "Sharpens edges of small/distant people; may help LOCALIZATION_FAILURE "
                       "(tighter boxes) and a few small TRUE_DETECTOR_MISS cases.",
        "targets_buckets": ["LOCALIZATION_FAILURE", "TRUE_DETECTOR_MISS"],
    },
    "gamma": {
        "fn": gamma_correction,
        "params": {"gamma": 0.75},
        "hypothesis": "Brightens underexposed regions; may raise confidence for "
                       "near-threshold Person detections in dark areas.",
        "targets_buckets": ["LOW_CONFIDENCE_PERSON"],
    },
    "autocontrast": {
        "fn": auto_contrast_stretch,
        "params": {"low_pct": 2.0, "high_pct": 98.0},
        "hypothesis": "Standardizes exposure variance across the dataset; may reduce "
                       "confidence variance for borderline Person detections.",
        "targets_buckets": ["LOW_CONFIDENCE_PERSON"],
    },
}


def apply_candidate(name: str, img: np.ndarray) -> np.ndarray:
    if name not in CANDIDATE_REGISTRY:
        raise PreprocessingError(f"unknown candidate {name!r}; known: {sorted(CANDIDATE_REGISTRY)}")
    spec = CANDIDATE_REGISTRY[name]
    return spec["fn"](img, **spec["params"])
