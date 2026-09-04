"""Hypothesis prioritization: score = (impact * evidence_strength * feasibility) / cost.

A soft heuristic used to ORDER the queue, not gate it — no experiment is
blocked from running solely because of a low score (that's what
status/BLOCKED is for). Each factor is scored 1-5 by whoever proposes the
experiment (a human or, eventually, the experiment_designer LLM role),
against the documented rubric below. This is explicitly false-precision-
avoidant: it is a ranking aid, not a validated formula.
"""

from __future__ import annotations

from dataclasses import dataclass

RUBRIC = """
expected_impact (1-5): how much would this move a metric that matters
  (primarily Person/hazard recall, secondarily other hazard classes) if the
  hypothesis is confirmed?
    5 = would meaningfully move the primary metric this lab most cares about (Person recall)
    3 = would meaningfully move a secondary hazard class or a guardrail metric (latency, precision)
    1 = would only move a thin-sample class (Stairs/Truck/Bus/Motorcycle) or a diagnostic-only metric

evidence_strength (1-5): how well-grounded is the hypothesis in existing data?
    5 = directly derived from a large-sample (Person/Car, GT>=100) baseline finding
    3 = derived from a thin-sample finding or a documented-but-unverified production issue
    1 = speculative, no direct supporting data yet

feasibility (1-5): how easy/safe is this to actually run in Phase C?
    5 = OFFLINE_SIMULATABLE, reuses existing evidence/scripts, no new inference run needed
    3 = OFFLINE_SIMULATABLE but requires a new inference run (imgsz sweep, preprocessing)
    1 = REQUIRES_MAC or REQUIRES_IPHONE, or requires new tooling not yet built

experiment_cost (1-5, higher = more expensive -> divides the score down):
    1 = near-zero (re-analysis of existing outputs)
    3 = one full re-run of benchmark.evaluate over the 380-image manifest
    5 = multiple re-runs, new dataset construction, or a device round-trip
"""


@dataclass(frozen=True)
class ScoreInputs:
    experiment_id: str
    expected_impact: int  # 1-5
    evidence_strength: int  # 1-5
    feasibility: int  # 1-5
    experiment_cost: int  # 1-5, minimum 1 to avoid division by zero
    rationale: str = ""

    def __post_init__(self):
        for name in ("expected_impact", "evidence_strength", "feasibility", "experiment_cost"):
            v = getattr(self, name)
            if not (1 <= v <= 5):
                raise ValueError(f"{name} must be 1-5, got {v}")


@dataclass(frozen=True)
class ScoredExperiment:
    experiment_id: str
    score: float
    inputs: ScoreInputs


def score(inputs: ScoreInputs) -> float:
    return (inputs.expected_impact * inputs.evidence_strength * inputs.feasibility) / inputs.experiment_cost


def prioritize(candidates: list[ScoreInputs]) -> list[ScoredExperiment]:
    """Score and sort candidates highest-first. Ties broken by experiment_id
    for determinism."""
    scored = [ScoredExperiment(c.experiment_id, score(c), c) for c in candidates]
    return sorted(scored, key=lambda s: (-s.score, s.experiment_id))
