"""Phase H — thin entry point for the dry-run research agent.

The implementation lives in research/dry_run/ (pipeline.py, budget.py,
prompts/). This module exists so `python -m research.dry_run_agent` and
`from research.dry_run_agent import ...` both work, matching the task
spec's "research/dry_run_agent.py (or a small package research/dry_run/)"
phrasing — this project does both: a real package for the implementation,
plus this thin re-export module as the named top-level entry point.

Structurally incapable of executing anything — see
research/dry_run/pipeline.py's module docstring for the exhaustive list of
things this never does (no git branch, no queue insertion, no runner call,
no ios/ or benchmark/config.py write).
"""

from __future__ import annotations

import sys

from research.dry_run.budget import DryRunBudgetExceededError, DryRunCallBudget
from research.dry_run.pipeline import (
    DryRunResult,
    render_report,
    run_dry_run_cycle,
    write_artifacts,
)

__all__ = [
    "DryRunBudgetExceededError",
    "DryRunCallBudget",
    "DryRunResult",
    "render_report",
    "run_dry_run_cycle",
    "write_artifacts",
]


def main() -> int:
    """Manual entry point — NOT used by the pytest suite (which mocks the
    LLM layer entirely). See research/cli.py's `omnilab dry-run` for the
    normal invocation path, and research/llm/smoke_test.py-style discipline
    for how a real, authorized, budget-capped live run should be driven."""
    print(
        "research.dry_run_agent.main() is a placeholder — run "
        "`uv run python -m research.cli dry-run` for the real dry-run "
        "pipeline invocation (it wires up the router/authorization/budget "
        "the same way research/llm/smoke_test.py does for its one "
        "authorized live call)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
