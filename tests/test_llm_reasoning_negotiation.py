"""Phase H reasoning-capability-negotiation tests (post-DRYRUN-0006).

DRYRUN-0006's HTTP 400 root cause: OmniLab unconditionally sent
`reasoning: {"enabled": False}` on every structured-output call, but
liquid/lfm-2.5-2.6b:free's real catalog entry is
`"reasoning": {"mandatory": true}` -- disabling reasoning isn't a valid
control for that model at all, and the provider/OpenRouter rejected the
request outright.

research/llm/model_catalog.py::build_reasoning_decision() replaces the
blanket assumption with a decision built ONLY from a model's own catalog
`reasoning` sub-object -- never inferred from a model's name/description
containing the word "reasoning", and never guessing an unadvertised
control. No network call anywhere in this file.
"""

from __future__ import annotations

from research.dry_run.budget import DryRunCallBudget
from research.dry_run.pipeline import _call_llm
from research.llm.base import LLMProvider, LLMResponse
from research.llm.model_catalog import (
    REASONING_DISABLED,
    REASONING_EFFORT,
    REASONING_MANDATORY_UNBOUNDED,
    REASONING_MAX_TOKENS,
    REASONING_NONE,
    REASONING_UNKNOWN,
    build_reasoning_decision,
)
from research.llm.router import LLMRouter


class TestBuildReasoningDecision:
    def test_mandatory_reasoning_cannot_be_disabled(self):
        """The exact liquid/lfm-2.5-2.6b:free shape that caused DRYRUN-0006's
        HTTP 400 -- mandatory=true, nothing else advertised. Must send
        nothing, never a guessed field."""
        decision = build_reasoning_decision("some/model", {"reasoning": {"mandatory": True}})
        assert decision.category == REASONING_MANDATORY_UNBOUNDED
        assert decision.request_field is None

    def test_optional_reasoning_disabled_when_officially_supported(self):
        """inclusionai/ling-3.0-flash-sante:free's real shape --
        mandatory=false, default_enabled=true. Disabling is valid here."""
        decision = build_reasoning_decision(
            "some/model", {"reasoning": {"mandatory": False, "default_enabled": True}}
        )
        assert decision.category == REASONING_DISABLED
        assert decision.request_field == {"enabled": False}

    def test_effort_control_used_only_when_advertised(self):
        decision = build_reasoning_decision(
            "some/model", {"reasoning": {"mandatory": True, "supported_efforts": ["high", "medium", "minimal"]}}
        )
        assert decision.category == REASONING_EFFORT
        assert decision.request_field == {"effort": "minimal"}

    def test_effort_control_prefers_minimal_over_low(self):
        decision = build_reasoning_decision(
            "some/model", {"reasoning": {"mandatory": True, "supported_efforts": ["low", "minimal"]}}
        )
        assert decision.request_field == {"effort": "minimal"}

    def test_effort_control_falls_back_to_low_if_minimal_absent(self):
        decision = build_reasoning_decision(
            "some/model", {"reasoning": {"mandatory": True, "supported_efforts": ["high", "low"]}}
        )
        assert decision.category == REASONING_EFFORT
        assert decision.request_field == {"effort": "low"}

    def test_max_tokens_control_used_only_when_advertised(self):
        decision = build_reasoning_decision(
            "some/model", {"reasoning": {"mandatory": True, "supports_max_tokens": True}},
            max_reasoning_tokens_headroom=256,
        )
        assert decision.category == REASONING_MAX_TOKENS
        assert decision.request_field == {"max_tokens": 256}

    def test_no_reasoning_metadata_sends_no_field(self):
        """A non-reasoning model (no 'reasoning' key at all) -- category A."""
        decision = build_reasoning_decision("some/model", {"supported_parameters": ["response_format"]})
        assert decision.category == REASONING_NONE
        assert decision.request_field is None

    def test_unknown_ambiguous_reasoning_shape_fails_closed(self):
        decision = build_reasoning_decision("some/model", {"reasoning": "yes please"})
        assert decision.category == REASONING_UNKNOWN
        assert decision.request_field is None

    def test_missing_catalog_entry_fails_closed(self):
        decision = build_reasoning_decision("some/model", None)
        assert decision.request_field is None

    def test_never_infers_from_model_name_or_description(self):
        """A catalog entry whose description says "reasoning model" but has
        NO structured 'reasoning' field at all must be treated as category A
        (no metadata), never as if reasoning were mandatory/present."""
        decision = build_reasoning_decision(
            "some/model",
            {"description": "a compact reasoning model from Liquid AI", "supported_parameters": ["response_format"]},
        )
        assert decision.category == REASONING_NONE
        assert decision.request_field is None


class _RecordingProvider(LLMProvider):
    def __init__(self, text: str):
        self.text = text
        self.received_kwargs: list[dict] = []

    def complete(self, prompt, role, model="", **kwargs):
        self.received_kwargs.append(kwargs)
        return LLMResponse(text=self.text, tokens_used=10, cost_usd=0.0, model_used=model)


def _isolated_router(provider: LLMProvider) -> LLMRouter:
    import tempfile
    from pathlib import Path

    from research.llm.base import UsageTracker

    tracker_path = Path(tempfile.mkstemp(suffix=".json")[1])
    return LLMRouter(provider=provider, usage_tracker=UsageTracker(path=tracker_path, max_per_day=1000))


class TestCallLlmReasoningWiring:
    """Prove _call_llm actually uses build_reasoning_decision() rather than
    a hard-coded field, end to end through the real choke point."""

    def test_mandatory_model_gets_no_reasoning_field_via_call_llm(self):
        provider = _RecordingProvider('{"ok": true}')
        router = _isolated_router(provider)
        for role_cfg in router._roles.values():
            role_cfg["preferred_model"] = "test/mandatory-model"
        catalog = {
            "test/mandatory-model": {
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["response_format", "structured_outputs"],
                "reasoning": {"mandatory": True},
            },
        }
        _call_llm(
            router, "researcher", "prompt", authorized=True, run_budget=None,
            dry_run_budget=DryRunCallBudget(3), step="s", call_records=[],
            model_catalog=catalog, require_structured_output=True,
            response_format={"type": "json_schema", "json_schema": {"name": "x", "schema": {}}},
        )
        assert "reasoning" not in provider.received_kwargs[0]

    def test_optional_disable_model_gets_disabled_via_call_llm(self):
        provider = _RecordingProvider('{"ok": true}')
        router = _isolated_router(provider)
        for role_cfg in router._roles.values():
            role_cfg["preferred_model"] = "test/optional-model"
        catalog = {
            "test/optional-model": {
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["response_format", "structured_outputs"],
                "reasoning": {"mandatory": False, "default_enabled": True},
            },
        }
        _call_llm(
            router, "researcher", "prompt", authorized=True, run_budget=None,
            dry_run_budget=DryRunCallBudget(3), step="s", call_records=[],
            model_catalog=catalog, require_structured_output=True,
            response_format={"type": "json_schema", "json_schema": {"name": "x", "schema": {}}},
        )
        assert provider.received_kwargs[0]["reasoning"] == {"enabled": False}

    def test_provider_require_parameters_always_sent_with_structured_output(self):
        provider = _RecordingProvider('{"ok": true}')
        router = _isolated_router(provider)
        response_format = {"type": "json_schema", "json_schema": {"name": "x", "schema": {}}}
        _call_llm(
            router, "researcher", "prompt", authorized=True, run_budget=None,
            dry_run_budget=DryRunCallBudget(3), step="s", call_records=[],
            response_format=response_format,
        )
        assert provider.received_kwargs[0]["provider"] == {"require_parameters": True}

    def test_call_record_captures_reasoning_and_capability_diagnostics(self):
        provider = _RecordingProvider('{"ok": true}')
        router = _isolated_router(provider)
        for role_cfg in router._roles.values():
            role_cfg["preferred_model"] = "test/optional-model"
        catalog = {
            "test/optional-model": {
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["response_format", "structured_outputs"],
                "reasoning": {"mandatory": False},
            },
        }
        call_records: list = []
        _call_llm(
            router, "researcher", "prompt", authorized=True, run_budget=None,
            dry_run_budget=DryRunCallBudget(3), step="s", call_records=call_records,
            model_catalog=catalog, require_structured_output=True,
            response_format={"type": "json_schema", "json_schema": {"name": "x", "schema": {}}},
        )
        assert call_records[0].reasoning_configuration == REASONING_DISABLED
        assert call_records[0].structured_output_capability_state is True

    def test_http_400_records_full_sanitized_diagnostics(self, monkeypatch):
        """Section 8: an HTTP 400 (DRYRUN-0006's exact failure mode) must
        record HTTP status, provider error code, sanitized provider error
        message, request ID if available, requested model,
        structured-output capability state, and reasoning configuration
        attempted -- all without ever leaking the API key or an
        Authorization header value."""
        import requests

        from research.llm.openrouter import OpenRouterProvider

        class FakeResp:
            status_code = 400
            headers = {}

            def json(self):
                return {"error": {"code": 400, "message": "reasoning is not supported for this model"}}

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake-not-real-00000000")
        real_provider = OpenRouterProvider()
        router = _isolated_router(real_provider)
        for role_cfg in router._roles.values():
            role_cfg["preferred_model"] = "test/mandatory-model"
        catalog = {
            "test/mandatory-model": {
                "pricing": {"prompt": "0", "completion": "0"},
                "supported_parameters": ["response_format", "structured_outputs"],
                "reasoning": {"mandatory": True},
            },
        }
        call_records: list = []
        try:
            _call_llm(
                router, "researcher", "prompt", authorized=True, run_budget=None,
                dry_run_budget=DryRunCallBudget(3), step="s", call_records=call_records,
                model_catalog=catalog, require_structured_output=True,
                response_format={"type": "json_schema", "json_schema": {"name": "x", "schema": {}}},
                max_retries=0,
            )
        except Exception:
            pass

        cr = call_records[0]
        assert cr.http_status == 400
        assert cr.provider_error_code == 400
        assert cr.provider_error_message == "reasoning is not supported for this model"
        assert cr.requested_model == "test/mandatory-model"
        assert cr.structured_output_capability_state is True
        assert cr.reasoning_configuration == REASONING_MANDATORY_UNBOUNDED
        assert "sk-fake-not-real-00000000" not in str(cr)
        assert "Authorization" not in str(cr)
