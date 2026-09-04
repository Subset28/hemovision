"""Moves an experiment's directory between experiments/{queued,active,
completed,rejected,failed}/ as its DB status changes.

Deletion is structurally discouraged: this module only ever MOVES a
directory, never deletes one. `experiments/failed/` and
`experiments/rejected/` are never auto-emptied — see research/README.md.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from research.config import EXPERIMENT_STATUS_DIRS, EXPERIMENTS_DIR


def status_dir_for(status: str) -> Path:
    if status not in EXPERIMENT_STATUS_DIRS:
        raise ValueError(f"unknown status: {status!r}")
    return EXPERIMENT_STATUS_DIRS[status]


def experiment_dir_for(experiment_id: str, status: str) -> Path:
    return status_dir_for(status) / experiment_id


def find_current_dir(experiment_id: str) -> Path | None:
    """Search all status directories for an existing EXP-XXXX directory
    (there should only ever be one, since move_to_status relocates it)."""
    seen = set()
    for status_dir in EXPERIMENT_STATUS_DIRS.values():
        if status_dir in seen:
            continue
        seen.add(status_dir)
        candidate = status_dir / experiment_id
        if candidate.exists():
            return candidate
    return None


def ensure_dirs() -> None:
    seen = set()
    for d in EXPERIMENT_STATUS_DIRS.values():
        if d not in seen:
            d.mkdir(parents=True, exist_ok=True)
            seen.add(d)


def move_to_status(experiment_id: str, new_status: str) -> Path:
    """Move (never delete/copy-and-leave-original) an experiment's directory
    to the directory matching new_status. Idempotent if already there."""
    ensure_dirs()
    target = experiment_dir_for(experiment_id, new_status)
    current = find_current_dir(experiment_id)

    if current is None:
        target.mkdir(parents=True, exist_ok=True)
        return target

    if current == target:
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise FileExistsError(
            f"refusing to overwrite existing directory at destination: {target}"
        )
    shutil.move(str(current), str(target))
    return target
