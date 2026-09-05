"""Narrow remediation build — tests for research/llm/model_catalog.py:
free-model enforcement (fail-closed), capability-aware model selection
(fail-closed, no substitution), and the offline/advisory discovery helper.
No network call anywhere in this file — every catalog entry is a synthetic
local dict."""

from __future__ import annotations

import pytest

from research.llm.model_catalog import (
    CAPABILITY_STRUCTURED_OUTPUT,
    ModelCapabilityError,
    ModelNotFreeError,
    evaluate_model_for_role,
    find_eligible_free_models,
    is_free_model,
    supports_structured_output,
)


class TestIsFreeModel:
    def test_zero_pricing_accepted(self):
        entry = {"pricing": {"prompt": "0", "completion": "0"}}
        assert is_free_model("some/model:free", entry) is True

    def test_nonzero_prompt_rejected(self):
        entry = {"pricing": {"prompt": "0.001", "completion": "0"}}
        assert is_free_model("some/model", entry) is False

    def test_nonzero_completion_rejected(self):
        entry = {"pricing": {"prompt": "0", "completion": "0.002"}}
        assert is_free_model("some/model", entry) is False

    def test_missing_pricing_field_rejected_ambiguous(self):
        entry = {"id": "some/model"}
        assert is_free_model("some/model", entry) is False

    def test_missing_prompt_key_rejected(self):
        entry = {"pricing": {"completion": "0"}}
        assert is_free_model("some/model", entry) is False

    def test_malformed_pricing_value_rejected(self):
        entry = {"pricing": {"prompt": "not-a-number", "completion": "0"}}
        assert is_free_model("some/model", entry) is False

    def test_no_catalog_entry_rejected(self):
        assert is_free_model("some/model", None) is False

    def test_float_zero_pricing_accepted(self):
        entry = {"pricing": {"prompt": 0, "completion": 0.0}}
        assert is_free_model("some/model", entry) is True


class TestSupportsStructuredOutput:
    def test_response_format_present_accepted(self):
        entry = {"supported_parameters": ["max_tokens", "response_format", "structured_outputs"]}
        assert supports_structured_output("liquid/lfm-2.5-2.6b:free", entry) is True

    def test_response_format_absent_rejected(self):
        entry = {"supported_parameters": ["max_tokens", "reasoning", "tool_choice"]}
        assert supports_structured_output("nvidia/nemotron-3.5-lightning:free", entry) is False

    def test_missing_supported_parameters_rejected(self):
        entry = {"id": "some/model"}
        assert supports_structured_output("some/model", entry) is False

    def test_malformed_supported_parameters_rejected(self):
        entry = {"supported_parameters": "response_format"}  # str, not list
        assert supports_structured_output("some/model", entry) is False

    def test_no_catalog_entry_rejected(self):
        assert supports_structured_output("some/model", None) is False


class TestEvaluateModelForRole:
    FREE_STRUCTURED_ENTRY = {
        "pricing": {"prompt": "0", "completion": "0"},
        "supported_parameters": ["response_format", "structured_outputs"],
    }
    FREE_UNSTRUCTURED_ENTRY = {
        "pricing": {"prompt": "0", "completion": "0"},
        "supported_parameters": ["reasoning"],
    }
    PAID_ENTRY = {
        "pricing": {"prompt": "0.001", "completion": "0.002"},
        "supported_parameters": ["response_format"],
    }

    def test_free_model_without_structured_requirement_passes(self):
        record = evaluate_model_for_role(
            "researcher", "liquid/lfm-2.5-2.6b:free", self.FREE_UNSTRUCTURED_ENTRY,
            require_structured_output=False,
        )
        assert record.passed is True
        assert record.selected_model == "liquid/lfm-2.5-2.6b:free"
        assert record.requested_model == "liquid/lfm-2.5-2.6b:free"

    def test_free_and_structured_capable_passes(self):
        record = evaluate_model_for_role(
            "researcher", "liquid/lfm-2.5-2.6b:free", self.FREE_STRUCTURED_ENTRY,
            require_structured_output=True,
        )
        assert record.passed is True
        assert record.capability_evidence.supports_structured_output is True

    def test_paid_model_rejected_before_network(self):
        with pytest.raises(ModelNotFreeError) as exc_info:
            evaluate_model_for_role("researcher", "some/paid-model", self.PAID_ENTRY)
        assert exc_info.value.record.passed is False
        assert exc_info.value.record.selected_model == "some/paid-model"  # no substitution

    def test_free_but_capability_missing_rejected_before_network(self):
        with pytest.raises(ModelCapabilityError) as exc_info:
            evaluate_model_for_role(
                "researcher", "nvidia/nemotron-3.5-lightning:free", self.FREE_UNSTRUCTURED_ENTRY,
                require_structured_output=True,
            )
        record = exc_info.value.record
        assert record.passed is False
        assert record.structured_output_required is True
        assert record.selected_model == "nvidia/nemotron-3.5-lightning:free"  # no substitution

    def test_missing_catalog_entry_rejected_as_not_free(self):
        with pytest.raises(ModelNotFreeError):
            evaluate_model_for_role("researcher", "unknown/model", None)


class TestFindEligibleFreeModels:
    """Offline/advisory discovery -- never wired into a live-call path (see
    research/dry_run/pipeline.py, which never imports this function)."""

    CATALOG = {
        "data": [
            {
                "id": "liquid/lfm-2.5-2.6b:free",
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["response_format", "structured_outputs"],
            },
            {
                "id": "nvidia/nemotron-3.5-lightning:free",
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["reasoning"],
            },
            {
                "id": "openai/gpt-4o-mini",
                "pricing": {"prompt": "0.00015", "completion": "0.0006"},
                "supported_parameters": ["response_format", "structured_outputs"],
            },
        ]
    }

    def test_finds_free_and_structured_capable_only(self):
        candidates = find_eligible_free_models(
            self.CATALOG, required_capabilities={CAPABILITY_STRUCTURED_OUTPUT}
        )
        ids = {c.model_id for c in candidates}
        assert ids == {"liquid/lfm-2.5-2.6b:free"}

    def test_finds_all_free_models_without_capability_requirement(self):
        candidates = find_eligible_free_models(self.CATALOG)
        ids = {c.model_id for c in candidates}
        assert ids == {"liquid/lfm-2.5-2.6b:free", "nvidia/nemotron-3.5-lightning:free"}

    def test_candidates_carry_provenance(self):
        candidates = find_eligible_free_models(self.CATALOG)
        for c in candidates:
            assert c.free_evidence.is_free is True
            assert c.catalog_fetch_timestamp
            assert c.catalog_source

    def test_not_wired_into_dry_run_pipeline(self):
        """Documents the explicit boundary: research/dry_run/pipeline.py
        (the only live-call path) never imports find_eligible_free_models."""
        import research.dry_run.pipeline as pipeline_module

        assert "find_eligible_free_models" not in dir(pipeline_module)
