"""Narrow remediation build — diagnostics tests (sections 5/6) for
research/llm/openrouter.py: safe diagnostic capture on success and every
failure mode, 429 rate-limit header/body capture, and secret-safety
(never captures the Authorization header or API key). No network call —
`requests.post` is monkeypatched throughout."""

from __future__ import annotations

import pytest

from research.llm.base import ErrorCategory, LLMUnavailableError
from research.llm.openrouter import OpenRouterProvider


def _provider_with_key(monkeypatch: pytest.MonkeyPatch) -> OpenRouterProvider:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake-not-real-00000000")
    return OpenRouterProvider()


class TestSuccessDiagnostics:
    def test_success_diagnostics_populated(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        class FakeResp:
            status_code = 200
            headers = {}

            def json(self):
                return {
                    "id": "gen-abc123",
                    "model": "fake/model",
                    "choices": [{"message": {"content": "hello back"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
                }

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
        provider = _provider_with_key(monkeypatch)
        resp = provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        diag = resp.diagnostics
        assert diag["http_status"] == 200
        assert diag["envelope_parsed"] is True
        assert diag["choices_present"] is True
        assert diag["message_present"] is True
        assert diag["content_present"] is True
        assert diag["content_length"] == len("hello back")
        assert diag["finish_reason"] == "stop"
        assert diag["usage"]["total_tokens"] == 8
        assert diag["request_id"] == "gen-abc123"
        # never anything secret
        assert "sk-fake-not-real-00000000" not in str(diag)
        assert "Authorization" not in diag


class TestFailureDiagnostics:
    def test_empty_content_diagnostics_distinct_category(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        class FakeResp:
            status_code = 200
            headers = {}

            def json(self):
                return {"choices": [{"message": {"content": ""}}]}

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError) as exc_info:
            provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        e = exc_info.value
        assert e.category == ErrorCategory.EMPTY_RESPONSE
        assert e.diagnostics["envelope_parsed"] is True
        assert e.diagnostics["choices_present"] is True
        assert e.diagnostics["message_present"] is True
        assert e.diagnostics["content_present"] is False or e.diagnostics.get("content_length") == 0

    def test_empty_content_still_captures_usage_and_reasoning_tokens(self, monkeypatch: pytest.MonkeyPatch):
        """Regression test for a real bug found during the Phase H token/
        reasoning audit (DRYRUN-0005): usage/request_id/model_used
        extraction happened AFTER the empty-content raise, so this data was
        silently discarded on exactly the failure path where it's most
        needed (distinguishing reasoning-token exhaustion from other empty-
        completion causes). Reproduces DRYRUN-0005's exact observed shape:
        HTTP 200, finish_reason="length", empty content, usage present."""
        import requests

        class FakeResp:
            status_code = 200
            headers = {}

            def json(self):
                return {
                    "id": "gen-dryrun0005-repro",
                    "model": "liquid/lfm-2.5-2.6b:free",
                    "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
                    "usage": {
                        "prompt_tokens": 1200,
                        "completion_tokens": 2048,
                        "total_tokens": 3248,
                        "completion_tokens_details": {"reasoning_tokens": 2048},
                    },
                }

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError) as exc_info:
            provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        diag = exc_info.value.diagnostics
        assert diag["finish_reason"] == "length"
        assert diag["request_id"] == "gen-dryrun0005-repro"
        assert diag["model_used"] == "liquid/lfm-2.5-2.6b:free"
        assert diag["usage"]["completion_tokens"] == 2048
        assert diag["usage"]["reasoning_tokens"] == 2048
        assert diag["usage"]["total_tokens"] == 3248

    def test_null_content_diagnostics(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        class FakeResp:
            status_code = 200
            headers = {}

            def json(self):
                return {"choices": [{"message": {"content": None}}]}

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError) as exc_info:
            provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        assert exc_info.value.category == ErrorCategory.EMPTY_RESPONSE
        assert exc_info.value.diagnostics["content_present"] is False

    def test_malformed_envelope_diagnostics(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        class FakeResp:
            status_code = 200
            headers = {}

            def json(self):
                raise ValueError("not json")

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError) as exc_info:
            provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        e = exc_info.value
        assert e.category == ErrorCategory.MALFORMED_RESPONSE
        assert e.diagnostics["envelope_parsed"] is False

    def test_missing_choices_diagnostics(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        class FakeResp:
            status_code = 200
            headers = {}

            def json(self):
                return {"unexpected": "shape"}

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError) as exc_info:
            provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        e = exc_info.value
        assert e.category == ErrorCategory.MALFORMED_RESPONSE
        assert e.diagnostics["envelope_parsed"] is True
        assert e.diagnostics["choices_present"] is False


class TestRateLimitDiagnostics:
    def test_429_headers_captured_without_secrets(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        class FakeResp:
            status_code = 429
            headers = {
                "X-RateLimit-Limit": "20",
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": "1735689600",
                "Authorization": "Bearer should-never-be-read",
            }

            def json(self):
                return {"error": {"code": 429, "message": "rate limited", "metadata": {"provider": "poolside"}}}

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError) as exc_info:
            provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        e = exc_info.value
        assert e.category == ErrorCategory.RATE_LIMIT
        diag = e.diagnostics
        assert diag["X-RateLimit-Limit"] == "20"
        assert diag["X-RateLimit-Remaining"] == "0"
        assert diag["X-RateLimit-Reset"] == "1735689600"
        assert diag["provider_error_code"] == 429
        assert diag["provider_error_metadata"] == {"provider": "poolside"}
        # The Authorization header must never be captured, anywhere.
        assert "Authorization" not in diag
        assert "should-never-be-read" not in str(diag)
        assert "sk-fake-not-real-00000000" not in str(diag)

    def test_429_without_headers_still_categorizes(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        class FakeResp:
            status_code = 429
            headers = {}

            def json(self):
                return {}

        monkeypatch.setattr(requests, "post", lambda *a, **k: FakeResp())
        provider = _provider_with_key(monkeypatch)
        with pytest.raises(LLMUnavailableError) as exc_info:
            provider.complete("hi", role="researcher", authorized=True, max_retries=0)
        assert exc_info.value.category == ErrorCategory.RATE_LIMIT
        assert "Authorization" not in exc_info.value.diagnostics
