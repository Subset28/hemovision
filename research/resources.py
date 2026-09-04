"""Resource awareness: refuse to start an experiment if CPU/RAM/VRAM/disk are
constrained, rather than launching and risking an OOM mid-run. Uses psutil
for CPU/RAM/disk and torch.cuda / nvidia-smi for GPU/VRAM (both already
available in this uv env from Phase B).
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass

from research.config import (
    MIN_AVAILABLE_DISK_GB,
    MIN_AVAILABLE_RAM_GB,
    MIN_AVAILABLE_VRAM_GB,
    REPO_ROOT,
)


@dataclass
class ResourceSnapshot:
    available_ram_gb: float
    available_disk_gb: float
    available_vram_gb: float | None  # None if no GPU / can't determine
    cpu_percent: float
    gpu_source: str  # "torch" | "nvidia-smi" | "unavailable"


class ResourceCheckFailed(RuntimeError):
    """Raised (and logged) when starting an experiment would risk exceeding
    resource limits. The orchestrator must refuse to start, not proceed and
    hope for the best."""


def _ram_gb() -> tuple[float, float]:
    import psutil

    vm = psutil.virtual_memory()
    return vm.available / (1024**3), psutil.cpu_percent(interval=0.1)


def _disk_gb(path=REPO_ROOT) -> float:
    usage = shutil.disk_usage(path)
    return usage.free / (1024**3)


def _vram_gb() -> tuple[float | None, str]:
    try:
        import torch

        if torch.cuda.is_available():
            free_bytes, _total = torch.cuda.mem_get_info(0)
            return free_bytes / (1024**3), "torch"
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            mb = float(out.stdout.strip().splitlines()[0])
            return mb / 1024.0, "nvidia-smi"
    except Exception:
        pass
    return None, "unavailable"


def snapshot() -> ResourceSnapshot:
    available_ram_gb, cpu_percent = _ram_gb()
    available_disk_gb = _disk_gb()
    available_vram_gb, gpu_source = _vram_gb()
    return ResourceSnapshot(
        available_ram_gb=available_ram_gb,
        available_disk_gb=available_disk_gb,
        available_vram_gb=available_vram_gb,
        cpu_percent=cpu_percent,
        gpu_source=gpu_source,
    )


def check_resources_or_raise(snap: ResourceSnapshot | None = None) -> ResourceSnapshot:
    """Refuse to start an experiment if resources are constrained. VRAM is
    only checked if a GPU was actually found (this benchmark can run on CPU;
    absence of a GPU is not itself a resource failure)."""
    snap = snap or snapshot()
    problems = []
    if snap.available_ram_gb < MIN_AVAILABLE_RAM_GB:
        problems.append(
            f"available RAM {snap.available_ram_gb:.2f}GB < required {MIN_AVAILABLE_RAM_GB}GB"
        )
    if snap.available_disk_gb < MIN_AVAILABLE_DISK_GB:
        problems.append(
            f"available disk {snap.available_disk_gb:.2f}GB < required {MIN_AVAILABLE_DISK_GB}GB"
        )
    if snap.available_vram_gb is not None and snap.available_vram_gb < MIN_AVAILABLE_VRAM_GB:
        problems.append(
            f"available VRAM {snap.available_vram_gb:.2f}GB < required {MIN_AVAILABLE_VRAM_GB}GB"
        )
    if problems:
        raise ResourceCheckFailed("refusing to start experiment: " + "; ".join(problems))
    return snap
