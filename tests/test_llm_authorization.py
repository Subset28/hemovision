"""Phase G — authorization gate tests (research/llm/authorization.py).

Proves the decoupling required by section 6: a configured API key alone
never authorizes a real network call. Every test here mocks the HTTP layer
(via monkeypatching `requests.post`) and asserts it either was or was not
invoked — never makes a real network call.
"""

from __future__ import annotations

import pytest

from research.llm.authorization import (
    LLMCallAuthorization,
    LLMCallNotAuthorizedError,
    require_authorization,
)
from research.llm.base import LLMUnavailableError
from research.llm.openrouter import OpenRouterProvider


class TestRequireAuthorization:
    def test_none_refused(self):
        with pytest.raises(LLMCallNotAuthorizedError):
            require_authorization(None)

    def test_false_refused(self):
        with pytest.raises(LLMCallNotAuthorizedError):
            require_authorization(False)

    def test_true_allowed(self):
        require_authorization(True)  # must not raise

    def test_authorization_object_false_refused(self):
        with pytest.raises(LLMCallNotAuthorizedError):
            require_authorization(LLMCallAuthorization.none())

    def test_authorization_object_granted_allowed(self):
        auth = LLMCallAuthorization.grant(reason="unit test")
        require_authorization(auth)  # must not raise

    def test_grant_requires_nonempty_reason(self):
        with pytest.raises(ValueError):
            LLMCallAuthorization.grant(reason="")


class TestKeyPresentButNotAuthorized:
    """The core decoupling test: key present + authorized=False (or
    omitted) -> refused, and the HTTP layer is never invoked. Key present +
    authorized=True -> proceeds (against a mocked HTTP layer)."""

    def test_key_present_authorized_false_refuses_no_network(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        called = {"count": 0}

        def fake_post(*args, **kwargs):
            called["count"] += 1
            raise AssertionError("requests.post must never be called when unauthorized")

        monkeypatch.setattr(requests, "post", fake_post)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-real-looking-key-1234567890")

        provider = OpenRouterProvider()
        with pytest.raises(LLMCallNotAuthorizedError):
            provider.complete("hello", role="researcher", authorized=False)

        assert called["count"] == 0

    def test_key_present_authorized_omitted_refuses_no_network(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        called = {"count": 0}

        def fake_post(*args, **kwargs):
            called["count"] += 1
            raise AssertionError("requests.post must never be called when unauthorized")

        monkeypatch.setattr(requests, "post", fake_post)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-real-looking-key-1234567890")

        provider = OpenRouterProvider()
        with pytest.raises(LLMCallNotAuthorizedError):
            provider.complete("hello", role="researcher")

        assert called["count"] == 0

    def test_key_present_authorized_true_proceeds_mocked(self, monkeypatch: pytest.MonkeyPatch):
        import requests

        called = {"count": 0}

        class FakeResponse:
            status_code = 200

            def json(self):
                return {
                    "id": "gen-fake-1",
                    "model": "fake/model",
                    "choices": [{"message": {"content": "OK"}}],
                    "usage": {"total_tokens": 5},
                }

        def fake_post(*args, **kwargs):
            called["count"] += 1
            return FakeResponse()

        monkeypatch.setattr(requests, "post", fake_post)
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-real-looking-key-1234567890")

        provider = OpenRouterProvider()
        resp = provider.complete("hello", role="researcher", authorized=True)

        assert called["count"] == 1
        assert resp.text == "OK"

    def test_no_key_and_authorized_true_still_refuses_missing_key(self, monkeypatch: pytest.MonkeyPatch):
        # Authorization alone doesn't manufacture a key either — both
        # conditions are independently required.
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        provider = OpenRouterProvider(api_key=None)
        with pytest.raises(LLMUnavailableError, match="no OPENROUTER_API_KEY"):
            provider.complete("hello", role="researcher", authorized=True)
