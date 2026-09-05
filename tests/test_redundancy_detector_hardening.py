"""Phase-I-readiness MEDIUM finding #8: research/experiment_validator.py::
find_rejected_hypothesis_conflicts()'s broadened deterministic keyword pool
(dependent_variables, control_condition, baseline_comparison, in addition
to independent_variables) -- plus an explicit, documented demonstration of
the residual "keyword-only, not semantic" limitation this remains subject
to. Uses the REAL research/memory.db (read-only queries), same pattern as
tests/test_experiment_spec.py's existing rejected-hypothesis tests."""

from __future__ import annotations

from research.experiment_spec import SCHEMA_VERSION, ExperimentProposal
from research.experiment_validator import find_rejected_hypothesis_conflicts
from research.memory_db import MemoryDB


def _proposal(**overrides) -> ExperimentProposal:
    defaults = dict(
        schema_version=SCHEMA_VERSION,
        experiment_id="EXP-9010",
        title="t",
        family="model_variant",
        hypothesis="h",
        motivation="m",
        research_question="rq",
        baseline_run_id="RUN-20260904-002",
        independent_variables=("totally novel unrelated wording xyz",),
        dependent_variables=("person.recall",),
        control_condition="c",
        baseline_comparison="RUN-20260904-002",
        success_criteria={"primary_metric": "person.recall", "min_meaningful_delta": 0.03},
    )
    defaults.update(overrides)
    return ExperimentProposal(**defaults)


class TestBroadenedKeywordPool:
    def test_control_condition_overlap_now_caught(self):
        """EXP-0005's REJECTED_HYPOTHESIS record has independent_variable
        'model checkpoint/architecture'. A proposal whose independent_variables
        text shares NOTHING with that, but whose control_condition text does,
        must now be caught -- this is exactly the broadened signal added."""
        proposal = _proposal(
            independent_variables=("totally novel unrelated wording xyz",),
            control_condition="uses a different model checkpoint/architecture as the control condition",
        )
        with MemoryDB() as mdb:
            conflicts = find_rejected_hypothesis_conflicts(proposal, mdb)
        assert any(exp_id == "EXP-0005" for exp_id, _ in conflicts)

    def test_dependent_variables_overlap_now_caught(self):
        proposal = _proposal(
            family="threshold_postprocessing",
            independent_variables=("totally novel unrelated wording xyz",),
            dependent_variables=("confidence_threshold",),
        )
        with MemoryDB() as mdb:
            conflicts = find_rejected_hypothesis_conflicts(proposal, mdb)
        assert any(exp_id == "EXP-0001" for exp_id, _ in conflicts)

    def test_still_requires_family_match(self):
        """Broadening the keyword pool never bypasses the exact family match
        -- overlapping vocabulary in an unrelated family must not conflict."""
        proposal = _proposal(
            family="preprocessing",  # NOT threshold_postprocessing
            independent_variables=("totally novel unrelated wording xyz",),
            dependent_variables=("confidence_threshold",),
        )
        with MemoryDB() as mdb:
            conflicts = find_rejected_hypothesis_conflicts(proposal, mdb)
        assert not any(exp_id == "EXP-0001" for exp_id, _ in conflicts)


class TestDocumentedResidualLimitation:
    def test_fully_reworded_proposal_with_zero_shared_keywords_slips_through(self):
        """This is the documented, accepted residual risk (see the
        function's own docstring): a genuinely-rejected direction reworded
        with NO shared keywords anywhere in independent_variables/
        dependent_variables/control_condition/baseline_comparison is NOT
        caught by this deterministic guardrail. Proven here, not hidden --
        deeper novelty assessment is the reviewer role's job, never an
        unrestricted LLM call bolted onto this deterministic function."""
        proposal = _proposal(
            family="threshold_postprocessing",
            independent_variables=("reduce the minimum acceptance bar for detections",),
            dependent_variables=("person.recall",),
            control_condition="unchanged inference pipeline",
            baseline_comparison="RUN-20260904-002",
        )
        with MemoryDB() as mdb:
            conflicts = find_rejected_hypothesis_conflicts(proposal, mdb)
        assert not any(exp_id == "EXP-0001" for exp_id, _ in conflicts)
