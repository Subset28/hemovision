"""Render PNG precision-recall curves for Person, Dog, Stairs (and the other
hazard classes) from benchmark/results/diagnostics/pr_curves.json (produced by
threshold_sweep.py). Diagnostic-only tooling — does not touch the baseline.

Run with: uv run python -m benchmark.diagnostics.render_pr_curves
Writes reports/baseline/figures/pr_curve_<class>.png
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from benchmark.config import REPO_ROOT

PR_CURVE_PATH = REPO_ROOT / "benchmark" / "results" / "diagnostics" / "pr_curves.json"
FIG_DIR = REPO_ROOT / "reports" / "baseline" / "figures"

# render for these at minimum, per task step 4
FEATURED = ["Person", "Dog", "Stairs"]


def main() -> None:
    data = json.loads(PR_CURVE_PATH.read_text(encoding="utf-8"))
    curves = data["curves"]
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    for cname, curve in curves.items():
        points = curve["points"]
        if not points:
            continue
        recalls = [p["recall"] for p in points]
        precisions = [p["precision"] for p in points]
        num_gt = curve["num_gt"]

        fig, ax = plt.subplots(figsize=(5, 4))
        ax.plot(recalls, precisions, linewidth=1.5)
        ax.set_xlabel("Recall")
        ax.set_ylabel("Precision")
        low_sample_tag = " (LOW SAMPLE — under 50 GT boxes)" if num_gt < 50 else ""
        ax.set_title(f"{cname} PR curve (n_gt={num_gt}){low_sample_tag}")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1.05)
        ax.grid(alpha=0.3)
        fig.tight_layout()
        out_path = FIG_DIR / f"pr_curve_{cname.lower()}.png"
        fig.savefig(out_path, dpi=120)
        plt.close(fig)
        print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
