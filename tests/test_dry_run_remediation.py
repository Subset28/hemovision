"""Narrow remediation build — pipeline-level tests: capability/free-model
pre-flight gating (zero network, zero budget), native structured-output
request-body construction, the one-logical-step=one-HTTP-request invariant
with the new response_format parameter, empty-content vs JSON-parse failure
category distinction, LFM/Nemotron regression fixtures at full-pipeline
level, and deterministic-validator-still-authoritative even over a
"perfect" native structured-output response. No network call anywhere in
this file."""

from __future__ import annotations

import json

import pytest

from research.dry_run.budget import DryRunCallBudget
from research.dry_run.pipeline import (
    FAILURE_EMPTY_CONTENT,
    _call_llm,
    run_dry_run_cycle,
)
from research.llm.base import LLMUnavailableError, UsageTracker
from research.llm.model_catalog import ModelCapabilityError, ModelNotFreeError
from research.llm.openrouter import OpenRouterProvider
from research.llm.router import LLMRouter
from research.llm.structured_output import build_response_format, proposal_response_json_schema

from tests.test_dry_run_pipeline import VALID_PROPOSAL, _proposal_json, _review_json, _router


def _openrouter_router(monkeypatch: pytest.MonkeyPatch, tmp_path) -> LLMRouter:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake-not-real-00000000")
    provider = OpenRouterProvider()
    roles_path = tmp_path / "roles.yaml"
    roles_path.write_text(
        "researcher:\n"
        "  preferred_model: nvidia/nemotron-3.5-lightning:free\n"
        "  max_tokens: 512\n"
        "  timeout: 30\n",
        encoding="utf-8",
    )
    tracker = UsageTracker(path=tmp_path / "usage.json", max_per_day=1000)
    return LLMRouter(provider=provider, roles_config_path=roles_path, usage_tracker=tracker)


class TestCapabilityGateBeforeNetwork:
    def test_unsupported_capability_model_rejected_before_network(self, monkeypatch, tmp_path):
        import requests

        spy = {"calls": 0}

        def fake_post(*a, **k):
            spy["calls"] += 1
            raise AssertionError("HTTP layer must never be invoked for a pre-flight rejection")

        monkeypatch.setattr(requests, "post", fake_post)

        router = _openrouter_router(monkeypatch, tmp_path)
        catalog = {
            "nvidia/nemotron-3.5-lightning:free": {
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["reasoning"],  # no response_format
            }
        }
        budget = DryRunCallBudget(max_calls=3)
        with pytest.raises(ModelCapabilityError):
            _call_llm(
                router, "researcher", "prompt text",
                authorized=True, run_budget=None, dry_run_budget=budget,
                step="initial_proposal", call_records=[],
                model_catalog=catalog, require_structured_output=True,
            )
        assert spy["calls"] == 0
        assert budget.calls_made == 0
        assert router.usage_tracker.calls_today() == 0


class TestFreeModelGateBeforeNetwork:
    def test_paid_model_rejected_before_network(self, monkeypatch, tmp_path):
        import requests

        spy = {"calls": 0}

        def fake_post(*a, **k):
            spy["calls"] += 1
            raise AssertionError("HTTP layer must never be invoked for a pre-flight rejection")

        monkeypatch.setattr(requests, "post", fake_post)

        router = _openrouter_router(monkeypatch, tmp_path)
        catalog = {
            "nvidia/nemotron-3.5-lightning:free": {
                "pricing": {"prompt": "0.0005", "completion": "0.001"},
                "supported_parameters": ["response_format"],
            }
        }
        budget = DryRunCallBudget(max_calls=3)
        with pytest.raises(ModelNotFreeError):
            _call_llm(
                router, "researcher", "prompt text",
                authorized=True, run_budget=None, dry_run_budget=budget,
                step="initial_proposal", call_records=[],
                model_catalog=catalog,
            )
        assert spy["calls"] == 0
        assert budget.calls_made == 0

    def test_free_model_accepted_and_reaches_network(self, monkeypatch, tmp_path):
        import requests

        class FakeResp:
            status_code = 200
            headers = {}

            def json(self):
                return {"choices": [{"message": {"content": "hello"}}]}

        calls = {"count": 0}

        def fake_post(*a, **k):
            calls["count"] += 1
            return FakeResp()

        monkeypatch.setattr(requests, "post", fake_post)

        router = _openrouter_router(monkeypatch, tmp_path)
        catalog = {
            "nvidia/nemotron-3.5-lightning:free": {
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["reasoning"],
            }
        }
        budget = DryRunCallBudget(max_calls=3)
        response = _call_llm(
            router, "researcher", "prompt text",
            authorized=True, run_budget=None, dry_run_budget=budget,
            step="initial_proposal", call_records=[],
            model_catalog=catalog,  # no require_structured_output -> free check only
        )
        assert response.text == "hello"
        assert calls["count"] == 1


class TestNativeStructuredOutputRequestShape:
    def test_response_format_flows_into_request_body_single_request(self, monkeypatch, tmp_path):
        import requests

        captured_bodies = []

        class FakeResp:
            status_code = 200
            headers = {}

            def json(self):
                return {"choices": [{"message": {"content": json.dumps(VALID_PROPOSAL)}}]}

        def fake_post(url, headers=None, json=None, timeout=None, **k):
            captured_bodies.append(json)
            return FakeResp()

        monkeypatch.setattr(requests, "post", fake_post)

        router = _openrouter_router(monkeypatch, tmp_path)
        schema = proposal_response_json_schema()
        response_format = build_response_format(schema, name="proposal_response")
        budget = DryRunCallBudget(max_calls=3)

        response = _call_llm(
            router, "researcher", "prompt text",
            authorized=True, run_budget=None, dry_run_budget=budget,
            step="initial_proposal", call_records=[],
            response_format=response_format,
        )
        assert len(captured_bodies) == 1  # exactly one HTTP request
        body = captured_bodies[0]
        assert body["model"] == "nvidia/nemotron-3.5-lightning:free"
        assert body["messages"] == [{"role": "user", "content": "prompt text"}]
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["name"] == "proposal_response"
        assert body["response_format"]["json_schema"]["schema"] == schema
        # provider.require_parameters (Phase H follow-up, section 6): every
        # structured-output request constrains routing to providers that
        # actually support every parameter sent -- still exactly one HTTP
        # request, a routing CONSTRAINT not a fallback chain.
        assert body["provider"] == {"require_parameters": True}
        # No model_catalog was explicitly passed to this call -- but per the
        # Phase-I-readiness free-model-only fix (CRITICAL #2), _call_llm now
        # ALWAYS resolves a catalog itself (here, the autouse permissive test
        # fixture in tests/conftest.py, which reports reasoning.mandatory:
        # False for any model), so reasoning negotiation now has real data
        # to act on and sends the DISABLED control -- never a guessed value,
        # exactly per the Phase H reasoning-capability-negotiation fix
        # (DRYRUN-0006 follow-up): a reasoning field is only ever sent when
        # the resolved catalog explicitly says it's valid for this model.
        assert body["reasoning"] == {"enabled": False}
        assert response.text == json.dumps(VALID_PROPOSAL)


class TestOneLogicalStepOneHttpRequestInvariant:
    """Regression: _call_llm must still make exactly one real HTTP attempt
    per logical step, never a second one, even with model_catalog/
    response_format wired in."""

    def test_preferred_model_only_never_iterates_fallbacks(self, monkeypatch, tmp_path):
        import requests

        calls = {"count": 0}

        def fake_post(*a, **k):
            calls["count"] += 1
            raise requests.exceptions.Timeout("simulated")

        monkeypatch.setattr(requests, "post", fake_post)

        router = _openrouter_router(monkeypatch, tmp_path)
        budget = DryRunCallBudget(max_calls=3)
        with pytest.raises(LLMUnavailableError):
            _call_llm(
                router, "researcher", "prompt text",
                authorized=True, run_budget=None, dry_run_budget=budget,
                step="initial_proposal", call_records=[], max_retries=0,
            )
        # max_retries=0 on top of _call_llm never retrying itself -> exactly 1 attempt.
        assert calls["count"] == 1
        assert budget.calls_made == 1


class TestEmptyContentDistinctFailureCategory:
    def test_lfm_style_empty_content_categorized_distinctly(self, monkeypatch, tmp_path):
        import requests

        class FakeResp:
            status_code = 200
            headers = {}

            def json(self):
                return {"choices": [{"message": {"content": ""}}]}

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())

        router = _openrouter_router(monkeypatch, tmp_path)
        budget = DryRunCallBudget(max_calls=3)
        call_records: list = []
        with pytest.raises(LLMUnavailableError):
            _call_llm(
                router, "researcher", "prompt text",
                authorized=True, run_budget=None, dry_run_budget=budget,
                step="initial_proposal", call_records=call_records,
            )
        assert len(call_records) == 1
        record = call_records[0]
        assert record.failure_category == FAILURE_EMPTY_CONTENT
        # distinct from a JSON-parse-layer failure category
        assert record.failure_category != "CONTENT_NOT_VALID_JSON"


class TestNemotronFencedRegressionFullPipeline:
    def test_fenced_proposal_and_review_succeed_end_to_end(self):
        fenced_proposal = "```json\n" + _proposal_json() + "\n```"
        fenced_review = "```json\n" + _review_json() + "\n```"
        router = _router([fenced_proposal, fenced_review])
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))
        assert result.stopped_reason == ""
        assert result.proposal is not None
        assert result.reviewer_critique is not None


class TestDeterministicValidatorStillAuthoritative:
    def test_perfect_looking_proposal_with_nonexistent_baseline_still_rejected(self):
        """Even a perfectly-well-formed ProposalResponse (would pass native
        structured-output json_schema validation) must still fail
        research/experiment_validator.py::validate() if it references a
        baseline_run_id that does not resolve to a real run directory."""
        router = _router([_proposal_json(), _review_json()])
        result = run_dry_run_cycle(
            router=router, authorized=True, dry_run_budget=DryRunCallBudget(3),
            baseline_run_id="RUN-DOES-NOT-EXIST-999",
        )
        assert result.proposal is not None
        assert result.proposal_validation is not None
        assert result.proposal_validation.is_valid is False
        error_codes = {e.code for e in result.proposal_validation.errors}
        assert "BAD_BASELINE_REF" in error_codes or "MISSING_BASELINE" in error_codes
