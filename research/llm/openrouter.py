"""Concrete OpenRouter provider. Reads OPENROUTER_API_KEY from env — never
hardcoded, never assumed present. There is almost certainly no real key in
this environment; this class is built to fail with a clear, caught,
LLMUnavailableError rather than crash anything that calls it.
"""

from __future__ import annotations

import os

from research.llm.base import LLMProvider, LLMResponse, LLMUnavailableError

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, timeout_sec: int = 60):
        # Explicit param wins for testability; otherwise read from env at
        # call time (not at import time) so tests can monkeypatch env vars.
        self._api_key_override = api_key
        self.timeout_sec = timeout_sec

    def _api_key(self) -> str:
        key = self._api_key_override or os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise LLMUnavailableError(
                "no OPENROUTER_API_KEY configured — LLM role unavailable. "
                "Set it in your environment or .env (see .env.example) to enable live "
                "OpenRouter calls. The pipeline continues without it."
            )
        return key

    def complete(self, prompt: str, role: str, model: str = "openrouter/auto", **kwargs) -> LLMResponse:
        api_key = self._api_key()  # raises LLMUnavailableError if missing

        try:
            import requests  # deferred import: only needed for a real call
        except ImportError as e:  # pragma: no cover - requests is a declared dep
            raise LLMUnavailableError(f"requests library unavailable: {e}") from e

        try:
            resp = requests.post(
                OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    **kwargs,
                },
                timeout=self.timeout_sec,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            raise LLMUnavailableError(f"OpenRouter request failed: {e}") from e

        try:
            text = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            tokens_used = usage.get("total_tokens")
            model_used = data.get("model", model)
        except (KeyError, IndexError, TypeError) as e:
            raise LLMUnavailableError(f"unexpected OpenRouter response shape: {e}") from e

        return LLMResponse(text=text, tokens_used=tokens_used, cost_usd=None, model_used=model_used)
