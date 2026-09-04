"""Tests for the LLM abstraction plumbing (research/llm/). Uses a fake
provider — never makes a live OpenRouter call (there is no real API key in
this environment, and these tests must not depend on network access)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research.llm.base import LLMProvider, LLMResponse, LLMUnavailableError, UsageTracker
from research.llm.openrouter import OpenRouterProvider
from research.llm.router import LLMRouter


class FakeProvider(LLMProvider):
    """Test double: succeeds for allowed models, raises LLMUnavailableError
    for everything else — simulates "model unavailable" without a network."""

    def __init__(self, working_models: set[str]):
        self.working_models = working_models
        self.calls: list[str] = []

    def complete(self, prompt: str, role: str, model: str = "", **kwargs) -> LLMResponse:
        self.calls.append(model)
        if model not in self.working_models:
            raise LLMUnavailableError(f"fake: {model} unavailable")
        return LLMResponse(text=f"response for {role}", tokens_used=42, cost_usd=0.001, model_used=model)


@pytest.fixture()
def roles_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "roles.yaml"
    p.write_text(
        "researcher:\n  primary: model-a\n  fallback: model-b\n"
        "reviewer:\n  primary: model-c\n  fallback: null\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture()
def usage_tracker(tmp_path: Path) -> UsageTracker:
    return UsageTracker(path=tmp_path / "usage.json", max_per_day=5)


class TestRouterFallback:
    def test_primary_success(self, roles_yaml: Path, usage_tracker: UsageTracker):
        provider = FakeProvider(working_models={"model-a"})
        router = LLMRouter(provider, roles_config_path=roles_yaml, usage_tracker=usage_tracker)
        resp = router.complete("hello", role="researcher")
        assert resp.model_used == "model-a"
        assert provider.calls == ["model-a"]

    def test_falls_back_when_primary_fails(self, roles_yaml: Path, usage_tracker: UsageTracker):
        provider = FakeProvider(working_models={"model-b"})
        router = LLMRouter(provider, roles_config_path=roles_yaml, usage_tracker=usage_tracker)
        resp = router.complete("hello", role="researcher")
        assert resp.model_used == "model-b"
        assert provider.calls == ["model-a", "model-b"]

    def test_raises_when_both_fail(self, roles_yaml: Path, usage_tracker: UsageTracker):
        provider = FakeProvider(working_models=set())
        router = LLMRouter(provider, roles_config_path=roles_yaml, usage_tracker=usage_tracker)
        with pytest.raises(LLMUnavailableError):
            router.complete("hello", role="researcher")

    def test_raises_for_unknown_role(self, roles_yaml: Path, usage_tracker: UsageTracker):
        provider = FakeProvider(working_models={"model-a"})
        router = LLMRouter(provider, roles_config_path=roles_yaml, usage_tracker=usage_tracker)
        with pytest.raises(LLMUnavailableError):
            router.complete("hello", role="nonexistent_role")

    def test_no_fallback_configured_raises_cleanly(self, roles_yaml: Path, usage_tracker: UsageTracker):
        provider = FakeProvider(working_models=set())
        router = LLMRouter(provider, roles_config_path=roles_yaml, usage_tracker=usage_tracker)
        with pytest.raises(LLMUnavailableError):
            router.complete("hello", role="reviewer")


class TestUsageTracker:
    def test_records_and_counts_calls(self, usage_tracker: UsageTracker):
        assert usage_tracker.calls_today() == 0
        usage_tracker.record_call()
        usage_tracker.record_call()
        assert usage_tracker.calls_today() == 2

    def test_check_budget_raises_when_exceeded(self, tmp_path: Path):
        tracker = UsageTracker(path=tmp_path / "usage.json", max_per_day=2)
        tracker.record_call()
        tracker.record_call()
        with pytest.raises(LLMUnavailableError):
            tracker.check_budget()

    def test_router_refuses_when_daily_cap_hit(self, roles_yaml: Path, tmp_path: Path):
        tracker = UsageTracker(path=tmp_path / "usage.json", max_per_day=1)
        provider = FakeProvider(working_models={"model-a"})
        router = LLMRouter(provider, roles_config_path=roles_yaml, usage_tracker=tracker)
        router.complete("hello", role="researcher")  # uses up the 1 allowed call
        with pytest.raises(LLMUnavailableError):
            router.complete("hello again", role="researcher")


class TestOpenRouterGracefulFailure:
    def test_no_api_key_raises_llm_unavailable_not_crash(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        provider = OpenRouterProvider(api_key=None)
        with pytest.raises(LLMUnavailableError, match="no OPENROUTER_API_KEY"):
            provider.complete("hello", role="researcher")

    def test_explicit_key_bypasses_env_check(self):
        # Providing a (fake) key means _api_key() succeeds; the actual HTTP
        # call would fail (no real endpoint reachable/valid key), and that
        # failure must ALSO surface as LLMUnavailableError, not a raw
        # requests exception — proving the graceful-failure contract holds
        # even past the missing-key check.
        provider = OpenRouterProvider(api_key="fake-key-not-real")
        with pytest.raises(LLMUnavailableError):
            provider.complete("hello", role="researcher", model="nonexistent/model-xyz")
