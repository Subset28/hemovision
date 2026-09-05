"""Narrow remediation build — defensive-parser tests (section 4) and JSON
Schema / native structured-output builder tests (section 3) for
research/llm/structured_output.py. No network call in this file."""

from __future__ import annotations

import json

import pytest

from research.llm.structured_output import (
    ProposalResponse,
    ReviewerCritique,
    ValidationError,
    _parse_json_object,
    build_response_format,
    parse_and_validate_proposal,
    parse_and_validate_reviewer_critique,
    proposal_response_json_schema,
    reviewer_critique_json_schema,
)

VALID_PROPOSAL_DICT = {
    "selected_problem": "small-person misses",
    "selection_rationale": "baseline shows a recall gap",
    "title": "Temporal aggregation",
    "family": "temporal_pipeline",
    "research_question": "Does aggregation help?",
    "hypothesis": "Yes because motion cues help.",
    "motivation": "Prior knobs exhausted.",
    "independent_variables": ["temporal_window_frames"],
    "dependent_variables": ["person.recall"],
    "control_condition": "single-frame baseline eval",
    "baseline_comparison": "RUN-20260904-002",
    "success_criteria": {"primary_metric": "person.recall", "min_meaningful_delta": 0.03},
    "supports_hypothesis_if": "recall improves >=0.03",
    "rejects_hypothesis_if": "recall improves <0.03",
    "inconclusive_if": "mixed guardrail results",
}


class TestPlainJsonRegression:
    def test_plain_json_still_works(self):
        data = _parse_json_object(json.dumps({"a": 1, "b": "two"}))
        assert data == {"a": 1, "b": "two"}

    def test_not_json_at_all_fails_cleanly(self):
        with pytest.raises(ValidationError):
            _parse_json_object("this is not json at all")


class TestFencedJsonParsing:
    def test_json_language_tagged_fence(self):
        raw = "```json\n" + json.dumps({"a": 1}) + "\n```"
        assert _parse_json_object(raw) == {"a": 1}

    def test_generic_fence_no_language_tag(self):
        raw = "```\n" + json.dumps({"a": 1}) + "\n```"
        assert _parse_json_object(raw) == {"a": 1}

    def test_fence_with_surrounding_whitespace(self):
        raw = "\n\n   ```json\n" + json.dumps({"a": 1}) + "\n```   \n\n"
        assert _parse_json_object(raw) == {"a": 1}


class TestAmbiguousAndMalformed:
    def test_multiple_json_object_candidates_rejected(self):
        raw = 'Here is one: {"a": 1} and here is another: {"b": 2}'
        with pytest.raises(ValidationError, match="ambiguous"):
            _parse_json_object(raw)

    def test_malformed_json_fails_cleanly(self):
        with pytest.raises(ValidationError):
            _parse_json_object('{"a": 1,}')  # trailing comma -- invalid JSON

    def test_brief_unambiguous_surrounding_prose_extracted(self):
        raw = 'Sure, here is my proposal:\n' + json.dumps({"a": 1}) + "\nLet me know what you think."
        assert _parse_json_object(raw) == {"a": 1}

    def test_no_json_object_found(self):
        with pytest.raises(ValidationError, match="no JSON object"):
            _parse_json_object("no braces here whatsoever")


class TestNemotronRegressionFenced:
    """Nemotron-style (DRYRUN-0003) regression: valid envelope, model
    content wrapped in ```json fences containing an otherwise-valid
    ExperimentProposal-shaped JSON object -- parser must extract it and the
    local validator (parse_and_validate_proposal) must accept it."""

    def test_nemotron_style_fenced_proposal_parses_and_validates(self):
        fenced = "```json\n" + json.dumps(VALID_PROPOSAL_DICT) + "\n```"
        result = parse_and_validate_proposal(fenced)
        assert isinstance(result, ProposalResponse)
        assert result.family == "temporal_pipeline"


class TestSchemaInvalidJson:
    def test_valid_json_wrong_shape_fails_local_validator(self):
        raw = json.dumps({"unexpected": "shape", "nothing": "matches ProposalResponse"})
        with pytest.raises(ValidationError):
            parse_and_validate_proposal(raw)


class TestJsonSchemaBuilders:
    def test_proposal_schema_has_required_fields(self):
        schema = proposal_response_json_schema()
        assert schema["type"] == "object"
        for f in (
            "title", "family", "research_question", "hypothesis", "motivation",
            "evidence_references", "prior_experiment_ids", "independent_variables",
            "dependent_variables", "success_criteria", "supports_hypothesis_if",
            "rejects_hypothesis_if", "inconclusive_if",
        ):
            assert f in schema["properties"], f"missing property {f}"
            assert f in schema["required"], f"not required: {f}"

    def test_proposal_schema_excludes_approval_flags(self):
        schema = proposal_response_json_schema()
        for forbidden in (
            "production_swift_modification_approved",
            "coreml_model_replacement_approved",
            "new_training_approved",
            "private_user_data_use_approved",
            "external_upload_approved",
            "mac_iphone_deployment_approved",
            "signing_distribution_change_approved",
        ):
            assert forbidden not in schema["properties"]

    def test_reviewer_schema_distinct_from_proposal_schema(self):
        proposal_schema = proposal_response_json_schema()
        reviewer_schema = reviewer_critique_json_schema()
        assert set(proposal_schema["properties"]) != set(reviewer_schema["properties"])
        for f in ("worth_running", "recommends_revision", "novelty_assessment", "summary"):
            assert f in reviewer_schema["properties"]

    def test_reviewer_schema_excludes_verdict_and_approval_fields(self):
        schema = reviewer_critique_json_schema()
        for forbidden in ("research_verdict", "verdict", "metrics", "coreml_model_replacement_approved"):
            assert forbidden not in schema["properties"]

    def test_build_response_format_shape(self):
        schema = proposal_response_json_schema()
        rf = build_response_format(schema, name="proposal_response")
        assert rf["type"] == "json_schema"
        assert rf["json_schema"]["name"] == "proposal_response"
        assert rf["json_schema"]["strict"] is True
        assert rf["json_schema"]["schema"] is schema
