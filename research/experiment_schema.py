"""Per-experiment file template generator.

Every experiment gets a directory `experiments/<status_dir>/EXP-XXXX/`
containing: hypothesis.md, methodology.md, config.yaml, results.json,
analysis.md, conclusion.md, patch.diff, benchmark.log, and a plots/ dir.
At QUEUED time only hypothesis.md/methodology.md/config.yaml are populated
with real content; the rest are created as placeholders and filled in as the
experiment progresses (see research/experiment_lifecycle.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from research.db import Experiment


def hypothesis_md(exp: Experiment) -> str:
    return f"""# {exp.experiment_id} — Hypothesis

**Family**: {exp.experiment_family}
**Validation requirement**: {exp.validation_requirement}
**Parent experiment**: {exp.parent_experiment_id or "(none)"}

## Hypothesis

{exp.hypothesis}

## Motivation

{exp.motivation}

## Rationale

{exp.rationale}

## Expected outcome

{exp.expected_outcome}

## Risks

{exp.risks}
"""


def methodology_md(exp: Experiment) -> str:
    controls_lines = "\n".join(f"- `{k}`: {v}" for k, v in exp.controls.items()) or "(none declared)"
    criteria_lines = "\n".join(
        f"- `{k}`: {v}" for k, v in exp.success_criteria.items()
    ) or "(none declared)"
    return f"""# {exp.experiment_id} — Methodology

## Independent variable

{exp.independent_variable}

## Controls (held constant)

{controls_lines}

## Evaluation method

{exp.evaluation_method}

## Success criteria (checked by research/evaluation_policy.py)

{criteria_lines}

## Baseline compared against

`{exp.baseline_run_id}` (see `benchmark/results/baseline/run_metadata.json`
if this is the canonical baseline, or `benchmark/results/diagnostics/` for a
diagnostic-derived baseline).
"""


def config_yaml(exp: Experiment) -> str:
    return yaml.safe_dump(
        {
            "experiment_id": exp.experiment_id,
            "experiment_family": exp.experiment_family,
            "independent_variable": exp.independent_variable,
            "controls": exp.controls,
            "configuration": exp.configuration,
            "baseline_run_id": exp.baseline_run_id,
            "validation_requirement": exp.validation_requirement,
            "estimated_cost": exp.estimated_cost,
        },
        sort_keys=False,
    )


def write_queued_artifacts(exp: Experiment, exp_dir: Path) -> None:
    """Write the artifacts expected to exist at QUEUED time. Placeholder
    files for the rest are created too, so the directory shape is always
    complete/predictable regardless of status."""
    exp_dir.mkdir(parents=True, exist_ok=True)
    (exp_dir / "plots").mkdir(exist_ok=True)
    (exp_dir / "hypothesis.md").write_text(hypothesis_md(exp), encoding="utf-8")
    (exp_dir / "methodology.md").write_text(methodology_md(exp), encoding="utf-8")
    (exp_dir / "config.yaml").write_text(config_yaml(exp), encoding="utf-8")
    for placeholder, content in (
        ("results.json", "{}\n"),
        ("analysis.md", f"# {exp.experiment_id} — Analysis\n\n(not yet run)\n"),
        ("conclusion.md", f"# {exp.experiment_id} — Conclusion\n\n(not yet run)\n"),
        ("patch.diff", ""),
        ("benchmark.log", ""),
    ):
        p = exp_dir / placeholder
        if not p.exists():
            p.write_text(content, encoding="utf-8")


def write_results_json(exp_dir: Path, results: dict) -> None:
    (exp_dir / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


def write_analysis_md(exp_dir: Path, content: str) -> None:
    (exp_dir / "analysis.md").write_text(content, encoding="utf-8")


def write_conclusion_md(exp_dir: Path, content: str) -> None:
    (exp_dir / "conclusion.md").write_text(content, encoding="utf-8")


def append_benchmark_log(exp_dir: Path, text: str) -> None:
    with open(exp_dir / "benchmark.log", "a", encoding="utf-8") as f:
        f.write(text)
        if not text.endswith("\n"):
            f.write("\n")
