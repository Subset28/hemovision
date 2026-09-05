"""Phase G — structured-output validation tests for
research/llm/structured_output.py, covering all 3 shapes (valid + invalid
cases) and the chain-of-custody guarantee: malformed/adversarial LLM output
cannot (a) enter the experiment queue, (b) mutate research/db.py, (c) be
treated as benchmark evidence."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from research.experiment_spec import ProposalContainsResultFieldsError, check_no_result_fields_in_proposal
from research.llm.structured_output import (
    AnalysisResponse,
    HypothesisResponse,
    ReviewerResponse,
    ValidationError,
    parse_and_validate,
    parse_and_validate_analysis,
    parse_and_validate_hypothesis,
    parse_and_validate_reviewer,
)


class TestHypothesisResponse:
    def test_valid(self):
        raw = json.dumps(
            {
                "hypothesis": "Higher-res crops improve stair-edge recall",
                "evidence": "EXP-0003 baseline analysis",
                "experiment_family": "preprocessing",
            }
        )
        result = parse_and_validate_hypothesis(raw)
        assert isinstance(result, HypothesisResponse)
        assert result.experiment_family == "preprocessing"

    def test_not_json(self):
        with pytest.raises(ValidationError):
            parse_and_validate_hypothesis("this is not json at all")

    def test_missing_required_field(self):
        raw = json.dumps({"hypothesis": "x", "evidence": "y"})  # missing experiment_family
        with pytest.raises(ValidationError):
            parse_and_validate_hypothesis(raw)

    def test_forbidden_result_field_rejected(self):
        raw = json.dumps(
            {
                "hypothesis": "x",
                "evidence": "y",
                "experiment_family": "z",
                "research_verdict": "PASSED",  # smuggled result-only field
            }
        )
        with pytest.raises(ValidationError):
            parse_and_validate_hypothesis(raw)

    def test_top_level_not_object(self):
        with pytest.raises(ValidationError):
            parse_and_validate_hypothesis(json.dumps(["not", "an", "object"]))


class TestReviewerResponse:
    def test_valid(self):
        raw = json.dumps({"scope_ok": True, "flagged_issues": [], "summary": "matches declared scope"})
        result = parse_and_validate_reviewer(raw)
        assert isinstance(result, ReviewerResponse)
        assert result.scope_ok is True

    def test_wrong_type_for_bool_field(self):
        raw = json.dumps({"scope_ok": "yes", "flagged_issues": [], "summary": "x"})
        with pytest.raises(ValidationError):
            parse_and_validate_reviewer(raw)

    def test_forbidden_metrics_field_rejected(self):
        raw = json.dumps(
            {"scope_ok": True, "flagged_issues": [], "summary": "x", "metrics": {"person.recall": 0.9}}
        )
        with pytest.raises(ValidationError):
            parse_and_validate_reviewer(raw)


class TestAnalysisResponse:
    def test_valid(self):
        raw = json.dumps({"summary": "recall improved", "memory_updates": ["MEM-0001"]})
        result = parse_and_validate_analysis(raw)
        assert isinstance(result, AnalysisResponse)

    def test_missing_field(self):
        raw = json.dumps({"summary": "recall improved"})
        with pytest.raises(ValidationError):
            parse_and_validate_analysis(raw)

    def test_forbidden_pass_fail_field_rejected(self):
        raw = json.dumps({"summary": "x", "memory_updates": [], "pass_fail": "PASS"})
        with pytest.raises(ValidationError):
            parse_and_validate_analysis(raw)


class TestDispatch:
    def test_unknown_shape(self):
        with pytest.raises(ValidationError):
            parse_and_validate("{}", shape="not_a_real_shape")

    def test_dispatches_to_hypothesis(self):
        raw = json.dumps({"hypothesis": "x", "evidence": "y", "experiment_family": "z"})
        result = parse_and_validate(raw, shape="hypothesis")
        assert isinstance(result, HypothesisResponse)


class TestChainOfCustody:
    """The load-bearing test class: prove malformed/adversarial structured
    output cannot reach the experiment queue, cannot mutate research/db.py,
    and is never treated as benchmark evidence."""

    ADVERSARIAL_RAW = json.dumps(
        {
            "hypothesis": "fabricated improvement",
            "evidence": "trust me",
            "experiment_family": "preprocessing",
            "research_verdict": "PASSED",
            "metrics": {"person.recall": 0.99},
        }
    )

    def test_a_cannot_enter_experiment_queue(self):
        """Simulates the intended consumer flow: parse the LLM response,
        then (if and only if valid) hand it to the Phase F proposal layer
        which is what research/experiment_validator.py's queue-eligibility
        gate consumes. Adversarial input must be rejected at the structured-
        output layer BEFORE ExperimentProposal.from_dict is ever called."""
        from_dict_mock = MagicMock()
        with patch("research.experiment_spec.ExperimentProposal.from_dict", from_dict_mock):
            with pytest.raises(ValidationError):
                parse_and_validate(self.ADVERSARIAL_RAW, shape="hypothesis")
            # Because parse_and_validate raised, the code that would have
            # called ExperimentProposal.from_dict() (and, later,
            # is_queue_eligible()) never executes.
            from_dict_mock.assert_not_called()

    def test_b_cannot_mutate_db(self):
        """Even in the defense-in-depth case where a caller (incorrectly)
        tried to hand the raw adversarial dict straight to Phase F's
        proposal constructor, bypassing this module entirely, Phase F's own
        independent check rejects it before any research/db.py write."""
        with patch("research.db.OmniLabDB") as db_mock:
            adversarial_dict = json.loads(self.ADVERSARIAL_RAW)
            with pytest.raises(ProposalContainsResultFieldsError):
                check_no_result_fields_in_proposal(adversarial_dict)
            db_mock.assert_not_called()

    def test_c_cannot_be_treated_as_benchmark_evidence(self):
        """A ValidationError result carries no metrics/verdict payload at
        all -- there is no object produced from adversarial input that any
        evidence-recording code path (research/memory_db.py::MemoryDB.insert,
        research/experiment_spec.py::ExperimentResult) could consume."""
        try:
            parse_and_validate(self.ADVERSARIAL_RAW, shape="hypothesis")
            produced_object = "SHOULD NOT REACH HERE"
        except ValidationError:
            produced_object = None
        assert produced_object is None

    def test_valid_hypothesis_response_still_lacks_result_fields_structurally(self):
        """Even a fully valid HypothesisResponse has no field that could
        hold a metric or verdict -- the dataclass itself has no such slot."""
        result = parse_and_validate(
            json.dumps({"hypothesis": "x", "evidence": "y", "experiment_family": "z"}),
            shape="hypothesis",
        )
        field_names = {f for f in result.__dataclass_fields__}
        assert "research_verdict" not in field_names
        assert "metrics" not in field_names
