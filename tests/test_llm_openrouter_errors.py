"""Phase G — error-category and retry/fallback tests for
research/llm/openrouter.py + research/llm/router.py. Every HTTP interaction
here is mocked via monkeypatching `requests.post`/`requests.exceptions` —
no real network call is ever made in this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from research.llm.base import ErrorCategory, LLMProvider, LLMResponse, LLMUnavailableError, UsageTracker
from research.llm.openrouter import OpenRouterProvider
from research.llm.router import LLMRouter


def _provider_with_key(monkeypatch: pytest.MonkeyPatch) -> OpenRouterProvider:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake-not-real-00000000")
    return OpenRouterProvider()


class TestErrorCategories:
    def test_timeout(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        def fake_post(*a, **k):
            raise requests.exceptions.Timeout("simulated timeout")

        monkeypatch.setattr(requests, "post", fake_post)
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError) as exc_info:
            provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        assert exc_info.value.category == ErrorCategory.TIMEOUT

    def test_network_error(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        def fake_post(*a, **k):
            raise requests.exceptions.ConnectionError("simulated connection error")

        monkeypatch.setattr(requests, "post", fake_post)
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError) as exc_info:
            provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        assert exc_info.value.category == ErrorCategory.NETWORK_ERROR

    def test_http_error_generic(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        class FakeResp:
            status_code = 500

            def json(self):
                return {}

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError) as exc_info:
            provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        assert exc_info.value.category == ErrorCategory.HTTP_ERROR

    def test_rate_limit(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        class FakeResp:
            status_code = 429

            def json(self):
                return {}

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError) as exc_info:
            provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        assert exc_info.value.category == ErrorCategory.RATE_LIMIT

    def test_invalid_key_401(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        class FakeResp:
            status_code = 401

            def json(self):
                return {}

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError) as exc_info:
            provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        assert exc_info.value.category == ErrorCategory.AUTH_ERROR
        # The (fake) key value must never appear in the exception text.
        assert "sk-fake-not-real-00000000" not in str(exc_info.value)

    def test_model_unavailable_404(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        class FakeResp:
            status_code = 404

            def json(self):
                return {}

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError) as exc_info:
            provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        assert exc_info.value.category == ErrorCategory.MODEL_UNAVAILABLE

    def test_malformed_response_bad_json(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        class FakeResp:
            status_code = 200

            def json(self):
                raise ValueError("not json")

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError) as exc_info:
            provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        assert exc_info.value.category == ErrorCategory.MALFORMED_RESPONSE

    def test_malformed_response_bad_shape(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        class FakeResp:
            status_code = 200

            def json(self):
                return {"unexpected": "shape"}

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError) as exc_info:
            provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        assert exc_info.value.category == ErrorCategory.MALFORMED_RESPONSE

    def test_empty_response(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        class FakeResp:
            status_code = 200

            def json(self):
                return {"choices": [{"message": {"content": ""}}]}

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError) as exc_info:
            provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        assert exc_info.value.category == ErrorCategory.EMPTY_RESPONSE

    def test_success_captures_request_id_and_usage(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        class FakeResp:
            status_code = 200

            def json(self):
                return {
                    "id": "gen-abc123",
                    "model": "fake/model",
                    "choices": [{"message": {"content": "hello back"}}],
                    "usage": {"total_tokens": 17},
                }

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
        provider = _provider_with_key(monkeypatch)
        resp = provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        assert resp.text == "hello back"
        assert resp.tokens_used == 17
        assert resp.request_id == "gen-abc123"
        assert resp.error_category is None
        assert resp.latency_ms is not None


class TestBoundedRetry:
    def test_retry_count_is_capped_for_timeout(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        calls = {"count": 0}

        def fake_post(*a, **k):
            calls["count"] += 1
            raise requests.exceptions.Timeout("always times out")

        monkeypatch.setattr(requests, "post", fake_post)
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError):
            provider.complete("hi", role="researcher", authorized=True, max_retries=2, retry_backoff_sec=0.0)
        # max_retries=2 -> up to 3 total attempts, never more.
        assert calls["count"] == 3

    def test_no_retry_for_auth_error(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        calls = {"count": 0}

        class FakeResp:
            status_code = 401

            def json(self):
                return {}

        def fake_post(*a, **k):
            calls["count"] += 1
            return FakeResp()

        monkeypatch.setattr(requests, "post", fake_post)
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError):
            provider.complete("hi", role="researcher", authorized=True, max_retries=2, retry_backoff_sec=0.0)
        # Auth errors are not transient -- must fail on the first attempt.
        assert calls["count"] == 1

    def test_no_retry_for_malformed_response(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        calls = {"count": 0}

        class FakeResp:
            status_code = 200

            def json(self):
                return {"bad": "shape"}

        def fake_post(*a, **k):
            calls["count"] += 1
            return FakeResp()

        monkeypatch.setattr(requests, "post", fake_post)
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError):
            provider.complete("hi", role="researcher", authorized=True, max_retries=2, retry_backoff_sec=0.0)
        assert calls["count"] == 1

    def test_max_retries_zero_makes_exactly_one_attempt(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        calls = {"count": 0}

        def fake_post(*a, **k):
            calls["count"] += 1
            raise requests.exceptions.Timeout("times out")

        monkeypatch.setattr(requests, "post", fake_post)
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError):
            provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        assert calls["count"] == 1


class TestRouterFallbackRoutingWithNewSchema:
    """Fallback routing over the new roles.yaml schema (fallback_models as a
    list, not a single value) via a fake, non-network provider."""

    class FakeProvider(LLMProvider):
        def __init__(self, working_models: set[str]):
            self.working_models = working_models
            self.calls: list[str] = []

        def complete(self, prompt: str, role: str, model: str = "", **kwargs) -> LLMResponse:
            self.calls.append(model)
            if model not in self.working_models:
                raise LLMUnavailableError(f"fake: {model} unavailable")
            return LLMResponse(text="ok", tokens_used=1, cost_usd=0.0, model_used=model)

    @pytest.fixture()
    def multi_fallback_roles_yaml(self, tmp_path: Path) -> Path:
        p = tmp_path / "roles.yaml"
        p.write_text(
            "researcher:\n"
            "  preferred_model: model-a\n"
            "  fallback_models: [model-b, model-c]\n",
            encoding="utf-8",
        )
        return p

    def test_falls_through_multiple_fallbacks(self, multi_fallback_roles_yaml: Path, tmp_path: Path):
        tracker = UsageTracker(path=tmp_path / "usage.json", max_per_day=10)
        provider = self.FakeProvider(working_models={"model-c"})
        router = LLMRouter(provider, roles_config_path=multi_fallback_roles_yaml, usage_tracker=tracker)
        resp = router.complete("hi", role="researcher", authorized=True)
        assert resp.model_used == "model-c"
        assert provider.calls == ["model-a", "model-b", "model-c"]
        # Policy: every attempt (2 failures + 1 success) counts against budget.
        assert tracker.calls_today() == 3

    def test_failed_attempts_still_count_against_budget(self, multi_fallback_roles_yaml: Path, tmp_path: Path):
        tracker = UsageTracker(path=tmp_path / "usage.json", max_per_day=10)
        provider = self.FakeProvider(working_models=set())
        router = LLMRouter(provider, roles_config_path=multi_fallback_roles_yaml, usage_tracker=tracker)
        with pytest.raises(LLMUnavailableError):
            router.complete("hi", role="researcher", authorized=True)
        assert tracker.calls_today() == 3  # model-a, model-b, model-c all attempted and counted
