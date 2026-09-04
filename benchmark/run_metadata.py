"""Reproducibility capture: everything needed to know exactly what produced a
given benchmark/results/<run>/ output directory.

Run ID scheme: RUN-YYYYMMDD-NNN. NNN increments per calendar day by scanning
existing benchmark/results/*/run_metadata.json files for today's date prefix
and taking (max existing NNN) + 1; the first run of a day is RUN-YYYYMMDD-001.
This is intentionally simple (no locking/concurrency handling) — this benchmark
is run interactively by one person at a time, not as a concurrent CI matrix.
"""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from benchmark.config import (
    BENCHMARK_VERSION,
    CONF_THRESHOLD,
    IMGSZ,
    IOU_THRESHOLD,
    MODEL_PATH,
    RANDOM_SEED,
    REPO_ROOT,
    RESULTS_DIR,
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
        )
        return out.stdout.strip()
    except Exception as e:  # pragma: no cover - defensive only
        return f"unknown ({e})"


def _next_run_id() -> str:
    today = datetime.now().strftime("%Y%m%d")
    prefix = f"RUN-{today}-"
    max_n = 0
    if RESULTS_DIR.exists():
        for meta_path in RESULTS_DIR.glob("*/run_metadata.json"):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                run_id = data.get("run_id", "")
            except Exception:
                continue
            if run_id.startswith(prefix):
                try:
                    n = int(run_id[len(prefix):])
                    max_n = max(max_n, n)
                except ValueError:
                    continue
    return f"{prefix}{max_n + 1:03d}"


def _gpu_info() -> dict:
    try:
        import torch

        if torch.cuda.is_available():
            return {
                "gpu_name": torch.cuda.get_device_name(0),
                "cuda_version": torch.version.cuda,
                "torch_version": torch.__version__,
            }
    except Exception:
        pass
    return {"gpu_name": None, "cuda_version": None, "torch_version": None}


def build_run_metadata(manifest_path: Path, manifest_hash: str, extra: dict | None = None) -> dict:
    gpu = _gpu_info()
    meta = {
        "run_id": _next_run_id(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "benchmark_version": BENCHMARK_VERSION,
        "git_commit": _git_commit(),
        "model_path": str(MODEL_PATH.relative_to(REPO_ROOT)),
        "model_sha256": _sha256_file(MODEL_PATH) if MODEL_PATH.exists() else None,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_hash,
        "config": {
            "imgsz": IMGSZ,
            "conf_threshold": CONF_THRESHOLD,
            "iou_threshold": IOU_THRESHOLD,
            "random_seed": RANDOM_SEED,
        },
        "python_version": sys.version,
        "platform": platform.platform(),
        **gpu,
    }
    if extra:
        meta.update(extra)
    return meta


def manifest_sha256(path: Path) -> str:
    return _sha256_file(path)
