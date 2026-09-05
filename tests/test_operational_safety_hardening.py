"""Phase-I-readiness hardening tests (CRITICAL #1, CRITICAL #2, MEDIUM #5,
MEDIUM #7): the centralized operational-state gate, the now-unconditional
free-model-only pre-flight, proof the router fallback loop is unreachable
from the canonical path, and the returned-model-provenance-mismatch check.
All LLM calls mocked -- no network (tests/conftest.py's socket guard would
refuse any real attempt anyway)."""

from __future__ import annotations

import json

import pytest

from research import operational_state
from research.dry_run.budget import DryRunCallBudget
from research.dry_run.pipeline import (
    ModelCatalogUnavailableError,
    ModelProvenanceMismatchError,
    _CALL_UNAVAILABLE,
    _call_llm,
)
from research.llm.base import LLMProvider, LLMResponse, LLMUnavailableError, UsageTracker
from research.llm.model_catalog import ModelNotFreeError
from research.llm.router import LLMRouter


class _SpyProvider(LLMProvider):
    """Fails the test outright if .complete() is ever called -- for
    asserting a gate/pre-flight blocked BEFORE any network attempt."""

    def __init__(self):
        self.calls = 0

    def complete(self, prompt, role, model="", **kwargs):
        self.calls += 1
        raise AssertionError("provider.complete() must never be called here")


class _FixedProvider(LLMProvider):
    def __init__(self, text: str, model_used: str | None = None):
        self.text = text
        self.model_used = model_used
        self.calls = 0

    def complete(self, prompt, role, model="", **kwargs):
        self.calls += 1
        return LLMResponse(
            text=self.text, tokens_used=10, cost_usd=0.0,
            model_used=self.model_used if self.model_used is not None else model,
        )


def _isolated_router(provider) -> LLMRouter:
    import tempfile
    from pathlib import Path

    tracker_path = Path(tempfile.mkstemp(suffix=".json")[1])
    return LLMRouter(provider=provider, usage_tracker=UsageTracker(path=tracker_path, max_per_day=1000))


def _call(router, provider_role="researcher", **overrides):
    kwargs = dict(
        router=router, role=provider_role, prompt="p",
        authorized=True, run_budget=None, dry_run_budget=DryRunCallBudget(3),
        step="initial_proposal", call_records=[],
    )
    kwargs.update(overrides)
    return _call_llm(**kwargs)


# ---------------------------------------------------------------------------
# CRITICAL #1 -- operational-state gate
# ---------------------------------------------------------------------------


class TestOperationalGateBlocksLlmCalls:
    @pytest.mark.parametrize("role", ["researcher", "reviewer"])
    def test_paused_blocks_call_before_any_http_request(self, role):
        operational_state.pause(reason="test")
        provider = _SpyProvider()
        router = _isolated_router(provider)
        budget = DryRunCallBudget(3)
        with pytest.raises(operational_state.OperationalPausedError):
            _call(router, provider_role=role, dry_run_budget=budget)
        assert provider.calls == 0
        assert budget.calls_made == 0  # no budget/network attempt consumed

    @pytest.mark.parametrize("role", ["researcher", "reviewer"])
    def test_stopped_blocks_call_before_any_http_request(self, role):
        operational_state.stop(reason="test")
        provider = _SpyProvider()
        router = _isolated_router(provider)
        budget = DryRunCallBudget(3)
        with pytest.raises(operational_state.OperationalStoppedError):
            _call(router, provider_role=role, dry_run_budget=budget)
        assert provider.calls == 0
        assert budget.calls_made == 0

    def test_revision_call_blocked_while_paused(self):
        """The revision step is also a `researcher`-role _call_llm invocation
        -- same choke point, same gate, no separate code path to miss."""
        operational_state.pause(reason="test")
        provider = _SpyProvider()
        router = _isolated_router(provider)
        budget = DryRunCallBudget(3)
        with pytest.raises(operational_state.OperationalPausedError):
            _call(router, provider_role="researcher", step="revision_only", dry_run_budget=budget)
        assert provider.calls == 0

    def test_gate_checked_before_dry_run_budget_recorded(self):
        """The gate raises before dry_run_budget.record() -- not merely
        before the network call -- proving no budget slot is silently
        consumed by a blocked attempt."""
        operational_state.stop(reason="test")
        budget = DryRunCallBudget(1)
        router = _isolated_router(_SpyProvider())
        with pytest.raises(operational_state.OperationalStoppedError):
            _call(router, dry_run_budget=budget)
        assert budget.remaining() == 1  # untouched

    def test_running_state_allows_call_through(self):
        """Sanity check: with no pause/stop issued, the gate is a no-op and
        the call proceeds normally."""
        router = _isolated_router(_FixedProvider(json.dumps({"ok": True})))
        response = _call(router)
        assert response.text == json.dumps({"ok": True})

    def test_resume_after_pause_allows_call_through(self):
        operational_state.pause(reason="test")
        operational_state.resume()
        router = _isolated_router(_FixedProvider(json.dumps({"ok": True})))
        response = _call(router)
        assert response.text == json.dumps({"ok": True})

    def test_plain_resume_does_not_clear_stopped(self):
        operational_state.stop(reason="test")
        operational_state.resume()  # should NOT clear stopped
        router = _isolated_router(_SpyProvider())
        with pytest.raises(operational_state.OperationalStoppedError):
            _call(router)

    def test_restart_from_stopped_requires_nonempty_reason(self):
        operational_state.stop(reason="test")
        with pytest.raises(ValueError):
            operational_state.restart_from_stopped("")

    def test_restart_from_stopped_clears_stopped_and_allows_call(self):
        operational_state.stop(reason="test")
        operational_state.restart_from_stopped(reason="human confirmed safe to resume")
        router = _isolated_router(_FixedProvider(json.dumps({"ok": True})))
        response = _call(router)
        assert response.text == json.dumps({"ok": True})


class TestReadOnlyOperationsUnaffectedByGate:
    def test_status_summary_works_while_paused(self):
        operational_state.pause(reason="test")
        from research import orchestrator

        # status_summary() is read-only -- must never call check_gate().
        summary = orchestrator.status_summary()
        assert "orchestrator_state" in summary
        assert summary["orchestrator_state"]["paused"] is True

    def test_status_summary_works_while_stopped(self):
        operational_state.stop(reason="test")
        from research import orchestrator

        summary = orchestrator.status_summary()
        assert summary["orchestrator_state"]["stopped"] is True

    def test_memory_query_works_while_stopped(self):
        operational_state.stop(reason="test")
        from research.memory_db import MemoryDB

        # Opening/querying the memory DB is read-only and must not consult
        # the operational-state gate at all.
        db = MemoryDB()
        try:
            db.list_records(tag="VERIFIED")
        finally:
            db.close()

    def test_deterministic_validation_works_while_stopped(self):
        operational_state.stop(reason="test")
        from research.experiment_spec import SCHEMA_VERSION, ExperimentProposal, ExperimentSpec
        from research.experiment_validator import validate

        proposal = ExperimentProposal(
            schema_version=SCHEMA_VERSION, experiment_id="EXP-9001", title="t",
            family="threshold_postprocessing", hypothesis="h", motivation="m",
            research_question="rq", baseline_run_id="RUN-20260904-002",
            independent_variables=("x",), dependent_variables=("person.recall",),
            control_condition="c", baseline_comparison="bc",
            success_criteria={"primary_metric": "person.recall", "min_meaningful_delta": 0.03},
        )
        # Must not raise an operational-gate error -- validate() is read-only.
        validate(ExperimentSpec(proposal=proposal))


class TestOperationalGateOnOrchestrator:
    def test_run_experiment_still_blocked_while_paused(self, tmp_path, monkeypatch):
        from research import orchestrator

        operational_state.pause(reason="test")
        with pytest.raises(operational_state.OperationalPausedError):
            orchestrator.run_experiment("EXP-9999")

    def test_queue_experiment_from_spec_blocked_while_stopped(self):
        from research import orchestrator
        from research.experiment_spec import SCHEMA_VERSION, ExperimentProposal, ExperimentSpec

        operational_state.stop(reason="test")
        proposal = ExperimentProposal(
            schema_version=SCHEMA_VERSION, experiment_id="EXP-9002", title="t",
            family="threshold_postprocessing", hypothesis="h", motivation="m",
            research_question="rq", baseline_run_id="RUN-20260904-002",
            independent_variables=("x",), dependent_variables=("person.recall",),
            control_condition="c", baseline_comparison="bc",
            success_criteria={"primary_metric": "person.recall", "min_meaningful_delta": 0.03},
        )
        with pytest.raises(operational_state.OperationalStoppedError):
            orchestrator.queue_experiment_from_spec(ExperimentSpec(proposal=proposal))


# ---------------------------------------------------------------------------
# CRITICAL #2 -- free-model-only is now an unconditional invariant
# ---------------------------------------------------------------------------


class TestFreeModelOnlyInvariant:
    def test_paid_model_rejected_zero_completion_requests(self, monkeypatch):
        paid_catalog = {"real/preferred-model-id": {
            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
            "supported_parameters": ["response_format", "structured_outputs"],
        }}
        provider = _SpyProvider()
        router = _isolated_router(provider)
        for role_cfg in router._roles.values():
            role_cfg["preferred_model"] = "real/preferred-model-id"

        with pytest.raises(ModelNotFreeError):
            _call(router, model_catalog=paid_catalog)
        assert provider.calls == 0

    def test_unknown_pricing_rejected_fail_closed(self):
        ambiguous_catalog = {"real/preferred-model-id": {
            "supported_parameters": ["response_format", "structured_outputs"],
            # no "pricing" key at all -- ambiguous, must fail closed
        }}
        provider = _SpyProvider()
        router = _isolated_router(provider)
        for role_cfg in router._roles.values():
            role_cfg["preferred_model"] = "real/preferred-model-id"

        with pytest.raises(ModelNotFreeError):
            _call(router, model_catalog=ambiguous_catalog)
        assert provider.calls == 0

    def test_missing_catalog_entirely_still_enforced_via_fallback_fetch(self, monkeypatch):
        """The core CRITICAL #2 regression: a caller that OMITS model_catalog
        entirely (the exact "forgot the flag" scenario) must still be
        blocked if the model turns out not to be free -- no caller can
        accidentally bypass the check by simply not supplying a catalog."""
        import research.dry_run.pipeline as pipeline_mod

        def _fake_fetch_returns_paid():
            return {"real/preferred-model-id": {
                "pricing": {"prompt": "0.000001", "completion": "0.0"},
                "supported_parameters": ["response_format", "structured_outputs"],
            }}

        monkeypatch.setattr(pipeline_mod, "_default_fetch_model_catalog", _fake_fetch_returns_paid)

        provider = _SpyProvider()
        router = _isolated_router(provider)
        for role_cfg in router._roles.values():
            role_cfg["preferred_model"] = "real/preferred-model-id"

        # No model_catalog kwarg passed at all.
        with pytest.raises(ModelNotFreeError):
            _call(router)
        assert provider.calls == 0

    def test_catalog_fetch_failure_fails_closed_not_open(self, monkeypatch):
        import research.dry_run.pipeline as pipeline_mod

        def _fake_fetch_raises():
            raise ConnectionError("simulated network failure")

        monkeypatch.setattr(pipeline_mod, "_default_fetch_model_catalog", _fake_fetch_raises)

        provider = _SpyProvider()
        router = _isolated_router(provider)
        with pytest.raises(ModelCatalogUnavailableError):
            _call(router)
        assert provider.calls == 0
        assert ModelCatalogUnavailableError in _CALL_UNAVAILABLE

    def test_free_and_capable_model_still_succeeds(self):
        free_catalog = {"real/preferred-model-id": {
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": ["response_format", "structured_outputs"],
            "reasoning": {"mandatory": False},
        }}
        provider = _FixedProvider(json.dumps({"ok": True}), model_used="real/preferred-model-id")
        router = _isolated_router(provider)
        for role_cfg in router._roles.values():
            role_cfg["preferred_model"] = "real/preferred-model-id"

        response = _call(router, model_catalog=free_catalog)
        assert response.text == json.dumps({"ok": True})
        assert provider.calls == 1


# ---------------------------------------------------------------------------
# MEDIUM #5 -- router fallback loop unreachable from the canonical path
# ---------------------------------------------------------------------------


class TestRouterFallbackUnreachable:
    def test_router_complete_never_invoked_by_call_llm(self, monkeypatch):
        """_call_llm must call router.provider.complete() directly, never
        router.complete() (which has the multi-model fallback loop that
        caused DRYRUN-0001's 3-requests-for-1-step bug)."""
        import research.llm.router as router_mod

        def _poisoned_complete(self, *a, **k):
            raise AssertionError(
                "LLMRouter.complete() (the multi-model fallback loop) must never be "
                "invoked by _call_llm's canonical path"
            )

        monkeypatch.setattr(router_mod.LLMRouter, "complete", _poisoned_complete)

        provider = _FixedProvider(json.dumps({"ok": True}))
        router = _isolated_router(provider)
        response = _call(router)
        assert response.text == json.dumps({"ok": True})  # succeeded without touching .complete()

    def test_full_dry_run_cycle_never_invokes_router_complete(self, monkeypatch):
        import research.llm.router as router_mod
        from research.dry_run.pipeline import run_dry_run_cycle

        def _poisoned_complete(self, *a, **k):
            raise AssertionError("run_dry_run_cycle must never reach LLMRouter.complete()")

        monkeypatch.setattr(router_mod.LLMRouter, "complete", _poisoned_complete)

        valid_proposal = {
            "selected_problem": "p", "selection_rationale": "r", "title": "t",
            "family": "threshold_postprocessing", "research_question": "rq", "hypothesis": "h",
            "motivation": "m", "independent_variables": ["x"], "dependent_variables": ["person.recall"],
            "control_condition": "c", "baseline_comparison": "RUN-20260904-002",
            "success_criteria": {"primary_metric": "person.recall", "min_meaningful_delta": 0.03},
            "supports_hypothesis_if": "s", "rejects_hypothesis_if": "r2", "inconclusive_if": "i",
            "evidence_references": [], "prior_experiment_ids": [], "controlled_variables": {},
            "procedure": "p", "production_impact": False, "production_impact_description": "",
            "data_privacy_classification": "NONE", "external_api_required": False,
            "mac_iphone_required": False, "acknowledges_rejected_hypothesis_ids": [],
            "materially_new_rationale": "",
        }
        review = {
            "novelty_assessment": "n", "scientific_validity_assessment": "s",
            "targets_verified_failure_mode": True, "success_criteria_deterministic": True,
            "confounding_notes": "n", "dataset_can_answer_question": True, "sample_size_adequate": True,
            "leakage_risk_notes": "n", "privacy_safety_ok": True, "feasibility_notes": "f",
            "worth_running": True, "recommends_revision": False, "revision_notes": "", "summary": "s",
        }

        class QueueProvider(LLMProvider):
            def __init__(self, items):
                self.items = list(items)

            def complete(self, prompt, role, model="", **kwargs):
                return LLMResponse(text=self.items.pop(0), tokens_used=10, cost_usd=0.0, model_used=model)

        router = _isolated_router(QueueProvider([json.dumps(valid_proposal), json.dumps(review)]))
        result = run_dry_run_cycle(router=router, authorized=True, dry_run_budget=DryRunCallBudget(3))
        assert result.calls_made == 2


# ---------------------------------------------------------------------------
# MEDIUM #7 -- returned-model provenance mismatch
# ---------------------------------------------------------------------------


class TestNoFallbackAfterRateLimit:
    def test_429_failure_does_not_trigger_a_second_request(self):
        """A 429 (rate limit) on the single preflighted model must fail that
        one call -- never silently retry against a fallback model. This is
        structurally guaranteed by _call_llm calling router.provider.complete()
        directly (never router.complete()'s fallback loop), proven here with
        a provider that raises on its first call and would fail the test if
        called a second time."""

        class RateLimitedProvider(LLMProvider):
            def __init__(self):
                self.calls = 0

            def complete(self, prompt, role, model="", **kwargs):
                self.calls += 1
                if self.calls > 1:
                    raise AssertionError("must never be called a second time (no fallback)")
                raise LLMUnavailableError("HTTP 429: rate limited", diagnostics={"http_status": 429, "network_attempted": True})

        provider = RateLimitedProvider()
        router = _isolated_router(provider)
        with pytest.raises(LLMUnavailableError):
            _call(router)
        assert provider.calls == 1


class TestModelProvenanceMismatch:
    def test_mismatched_returned_model_rejected(self):
        free_catalog = {"real/preferred-model-id": {
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": ["response_format", "structured_outputs"],
        }}
        provider = _FixedProvider(json.dumps({"ok": True}), model_used="some/other-model:free")
        router = _isolated_router(provider)
        for role_cfg in router._roles.values():
            role_cfg["preferred_model"] = "real/preferred-model-id"

        call_records: list = []
        with pytest.raises(ModelProvenanceMismatchError):
            _call(router, model_catalog=free_catalog, call_records=call_records)
        assert call_records[-1].succeeded is False
        assert call_records[-1].failure_category == "MODEL_PROVENANCE_MISMATCH"
        assert call_records[-1].network_attempted is True  # a real response WAS received

    def test_matching_returned_model_succeeds(self):
        free_catalog = {"real/preferred-model-id": {
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": ["response_format", "structured_outputs"],
        }}
        provider = _FixedProvider(json.dumps({"ok": True}), model_used="real/preferred-model-id")
        router = _isolated_router(provider)
        for role_cfg in router._roles.values():
            role_cfg["preferred_model"] = "real/preferred-model-id"

        response = _call(router, model_catalog=free_catalog)
        assert response.text == json.dumps({"ok": True})
