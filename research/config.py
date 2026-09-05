"""Phase C research/experiment-infrastructure config.

Single source of truth for orchestration-layer constants (NOT the benchmark's
model operating point — that stays in benchmark/config.py and must never be
changed by anything in this package). Everything here is additive tooling
around the existing, approved benchmark harness.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_DIR = REPO_ROOT / "research"
EXPERIMENTS_DIR = REPO_ROOT / "experiments"
DB_PATH = RESEARCH_DIR / "omnilab.db"

# Phase E — structured research memory. Sibling database, not new tables in
# DB_PATH's schema — see research/memory_db.py's module docstring ("Design
# choice") for why.
MEMORY_DB_PATH = RESEARCH_DIR / "memory.db"
CONTEXT_PACKET_PATH = RESEARCH_DIR / "memory" / "CONTEXT_PACKET.md"

# Keyed by EXECUTION_STATUS only (research/db.py) — directory placement
# reflects "did the pipeline run", never the research verdict. An experiment
# that ran successfully but got a FAIL/INCONCLUSIVE/REJECTED verdict still
# lives in completed/; the verdict is recorded explicitly in that
# experiment's results.json/conclusion.md and the DB, never implied by which
# folder it's in. See research/README.md "Execution status vs. research
# verdict".
EXPERIMENT_STATUS_DIRS = {
    "QUEUED": EXPERIMENTS_DIR / "queued",
    "RUNNING": EXPERIMENTS_DIR / "running",
    "COMPLETED": EXPERIMENTS_DIR / "completed",
    "BLOCKED": EXPERIMENTS_DIR / "blocked",
    "ABORTED": EXPERIMENTS_DIR / "aborted",
}

MEMORY_DIR = RESEARCH_DIR / "memory"
LITERATURE_DIR = RESEARCH_DIR / "literature"
LLM_DIR = RESEARCH_DIR / "llm"
LLM_ROLES_CONFIG = LLM_DIR / "roles.yaml"
LLM_USAGE_LOG = RESEARCH_DIR / "llm_usage.json"

# ---------------------------------------------------------------------------
# Resource / safety limits (Phase C — "manually-triggered pipeline", not
# unrestricted autonomous operation; see research/README.md).
# ---------------------------------------------------------------------------

MAX_CONCURRENT_EXPERIMENTS = 1
MAX_EXPERIMENTS_PER_RUN = 3
MAX_LLM_CALLS = 10  # per orchestrator run, distinct from the daily cap below
MAX_LLM_CALLS_PER_DAY = 40
MAX_EXPERIMENT_RUNTIME_SEC = 60 * 60  # 60 minutes

# Resource-check thresholds (research/resources.py). Conservative defaults —
# refuse to start rather than risk OOM. Tunable per machine.
MIN_AVAILABLE_RAM_GB = 2.0
MIN_AVAILABLE_VRAM_GB = 1.0
MIN_AVAILABLE_DISK_GB = 5.0

# The canonical, immutable baseline run this whole lab compares against.
# NEVER overwrite or delete benchmark/results/baseline/ — see
# benchmark/results/baseline/run_metadata.json for its run_id.
CANONICAL_BASELINE_RUN_ID = "RUN-20260904-002"
CANONICAL_BASELINE_RESULTS_DIR = REPO_ROOT / "benchmark" / "results" / "baseline"

EVAL_MANIFEST_PATH = REPO_ROOT / "data" / "manifests" / "eval_manifest.jsonl"

# Protected branches an experiment must never target as a merge destination
# and must never be checked out FROM other than as the starting point.
PROTECTED_BRANCHES = ("master", "main", "production", "release")
