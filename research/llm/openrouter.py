"""Concrete OpenRouter provider.

Secret-safety discipline (Phase G section 3 — read this before touching
anything below):
  - `OPENROUTER_API_KEY` is read from `os.environ` INSIDE `_api_key()`, at
    call time, never at import/module-load time — so tests can freely
    monkeypatch/clear the env var without any import-order tricks.
  - The key value is NEVER interpolated into a log statement, an exception
    message, a return value, or anything persisted to disk. Every message
    that needs to reference "is a key configured" uses a redacted
    representation (`_redact(key)` -> "sk-***(len=51)" or "unset") — grep
    this file for every `key` reference if you're auditing it; none of them
    format the raw value into text meant for a human/log/exception.
  - A 401/403 (or any other) HTTP response is caught and turned into a
    categorized, safe error. We never log raw response headers or bodies —
    OpenRouter does not echo the key back in a response, but this stays
    defensive regardless (a body could contain YOUR OWN request unexpectedly
    reflected by a misbehaving proxy, an edge case not worth the risk).

Authorization gate (Phase G section 6): `complete()` requires an explicit
`authorized` argument (bool or `LLMCallAuthorization`) with NO default that
silently authorizes a network call. This is checked FIRST, before the key
check, before the privacy guard, before any network code runs — see
research/llm/authorization.py::require_authorization().

Privacy guard (Phase G section 7): the assembled message payload is run
through research/llm/privacy_guard.py::check_payload_safe() before the
request is sent; a non-empty result blocks the call with
`PrivacyViolationError` (a subclass of LLMUnavailableError) rather than
overriding the guard.

Retry/fallback (Phase G section 11): bounded retries (default 2, so up to 3
total attempts) with a small exponential backoff, ONLY for categories in
`RETRYABLE_CATEGORIES` (TIMEOUT, NETWORK_ERROR) — auth errors and malformed
responses fail immediately, they cannot succeed differently on retry. Pass
`max_retries=0` to disable retries entirely for a single, provably-bounded
invocation (see research/llm/smoke_test.py, which does exactly this for the
one authorized live call this phase makes).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from research.llm.authorization import AuthorizationLike, require_authorization
from research.llm.base import (
    ErrorCategory,
    LLMProvider,
    LLMResponse,
    LLMUnavailableError,
    RETRYABLE_CATEGORIES,
)
from research.llm.privacy_guard import PrivacyViolationError, check_payload_safe

logger = logging.getLogger("research.llm.openrouter")

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterProviderError(LLMUnavailableError):
    """A categorized failure from a real (or attempted) OpenRouter call.
    Message text is always constructed from redacted/safe representations —
    never from the raw key, raw response headers, or raw response body."""


def _redact(key: Optional[str]) -> str:
    """Redacted representation of an API key for logs/exceptions. Never
    returns anything from which the real value could be reconstructed."""
    if not key:
        return "unset"
    return f"set(len={len(key)})"


# Response/rate-limit headers OpenRouter documents as safe, non-secret,
# diagnosis-relevant (https://openrouter.ai/docs/api-reference/limits) --
# `Authorization` (or any other secret-bearing header) is NEVER read here,
# NEVER placed in diagnostics, and NEVER logged, by construction: this list
# is the only set of header names `_safe_response_headers` ever consults.
_SAFE_DIAGNOSTIC_HEADERS = (
    "X-RateLimit-Limit",
    "X-RateLimit-Remaining",
    "X-RateLimit-Reset",
    "Retry-After",
)


def _safe_response_headers(resp) -> dict:
    """Extract ONLY the documented, non-secret rate-limit/retry headers from
    an HTTP response, case-insensitively. Never touches `Authorization` or
    any other header -- this function's own allowlist (`_SAFE_DIAGNOSTIC_HEADERS`)
    is the sole source of what it will ever return."""
    headers = getattr(resp, "headers", None) or {}
    out: dict = {}
    for name in _SAFE_DIAGNOSTIC_HEADERS:
        value = headers.get(name)
        if value is not None:
            out[name] = value
    return out


def _safe_error_body_fields(data: Any) -> dict:
    """Extract ONLY `error.code`/`error.message`/`error.metadata` from an
    OpenRouter error envelope, if present -- never the raw body verbatim,
    never anything else it might contain."""
    if not isinstance(data, dict):
        return {}
    err = data.get("error")
    if not isinstance(err, dict):
        return {}
    out: dict = {}
    if "code" in err:
        out["provider_error_code"] = err.get("code")
    if "message" in err:
        # OpenRouter's own error message text -- not model output, not a
        # secret, safe to retain (distinct from the prompt/completion body,
        # which is never retained).
        out["provider_error_message"] = err.get("message")
    if "metadata" in err:
        out["provider_error_metadata"] = err.get("metadata")
    return out


class OpenRouterProvider(LLMProvider):
    def __init__(self, api_key: str | None = None, timeout_sec: int = 60):
        # Explicit param wins for testability; otherwise read from env at
        # call time (not at import time) so tests can monkeypatch env vars.
        self._api_key_override = api_key
        self.timeout_sec = timeout_sec

    def _api_key(self) -> str:
        import os

        key = self._api_key_override or os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise LLMUnavailableError(
                "no OPENROUTER_API_KEY configured — LLM role unavailable. "
                "Set it in your environment or .env (see .env.example) to enable live "
                "OpenRouter calls. The pipeline continues without it.",
                category=ErrorCategory.AUTH_ERROR,
            )
        return key

    def complete(
        self,
        prompt: str,
        role: str,
        model: str = "openrouter/auto",
        *,
        authorized: AuthorizationLike = None,
        messages: Optional[list[dict]] = None,
        max_tokens: Optional[int] = None,
        timeout_sec: Optional[int] = None,
        max_retries: int = 2,
        retry_backoff_sec: float = 0.05,
        **kwargs,
    ) -> LLMResponse:
        # 1. Authorization gate — checked FIRST, before anything else. A
        #    key being present never implies authorization.
        require_authorization(authorized)

        # 2. Key check.
        api_key = self._api_key()  # raises LLMUnavailableError if missing

        # 3. Build the payload and run the privacy guard on it BEFORE any
        #    network code executes.
        payload_messages = messages if messages is not None else [{"role": "user", "content": prompt}]
        payload_text = "\n".join(str(m.get("content", "")) for m in payload_messages)
        violations = check_payload_safe(payload_text)
        if violations:
            raise PrivacyViolationError(
                f"OpenRouter call blocked by privacy guard — payload contains "
                f"disallowed pattern(s): {violations}. Call refused before any "
                "network request was made."
            )

        try:
            import requests
        except ImportError as e:  # pragma: no cover - requests is a declared dep
            raise LLMUnavailableError(
                f"requests library unavailable: {e}", category=ErrorCategory.UNKNOWN
            ) from e

        effective_timeout = timeout_sec if timeout_sec is not None else self.timeout_sec
        body: dict = {"model": model, "messages": payload_messages}
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        body.update(kwargs)

        attempts = max(1, max_retries + 1)
        last_error: Optional[OpenRouterProviderError] = None

        for attempt in range(attempts):
            start = time.monotonic()
            try:
                response = self._dispatch(api_key, body, effective_timeout)
                response = self._with_latency(response, start)
                return response
            except OpenRouterProviderError as e:
                last_error = e
                if e.category in RETRYABLE_CATEGORIES and attempt < attempts - 1:
                    logger.warning(
                        "OpenRouter call category=%s attempt=%d/%d — retrying (key: %s)",
                        e.category, attempt + 1, attempts, _redact(api_key),
                    )
                    time.sleep(retry_backoff_sec * (2**attempt))
                    continue
                raise

        # Unreachable in practice (loop always returns or raises), but keeps
        # type-checkers and defensive readers happy.
        assert last_error is not None
        raise last_error

    def _with_latency(self, response: LLMResponse, start: float) -> LLMResponse:
        from dataclasses import replace

        latency_ms = (time.monotonic() - start) * 1000.0
        return replace(response, latency_ms=latency_ms)

    def _dispatch(self, api_key: str, body: dict, timeout_sec: int) -> LLMResponse:
        """One HTTP attempt. Raises OpenRouterProviderError, categorized,
        for every failure mode — never lets a raw requests/JSON exception
        (which could theoretically echo request internals) propagate.

        Every raise point (and the success return) attaches a safe
        diagnostics dict (Phase-remediation section 5/6) — never the API
        key, the Authorization header, raw environment, private context, the
        full prompt, or the full response/completion text; only structural
        facts (status code, presence checks, lengths, safe headers/error
        fields) survive into `diagnostics`."""
        import requests

        requested_model = body.get("model")
        diag: dict = {"requested_model": requested_model}

        try:
            resp = requests.post(
                OPENROUTER_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=timeout_sec,
            )
        except requests.exceptions.Timeout as e:
            raise OpenRouterProviderError(
                f"OpenRouter request timed out (key: {_redact(api_key)})",
                category=ErrorCategory.TIMEOUT,
                diagnostics=diag,
            ) from e
        except requests.exceptions.ConnectionError as e:
            raise OpenRouterProviderError(
                f"OpenRouter request failed — network error (key: {_redact(api_key)})",
                category=ErrorCategory.NETWORK_ERROR,
                diagnostics=diag,
            ) from e
        except requests.exceptions.RequestException as e:
            raise OpenRouterProviderError(
                f"OpenRouter request failed (key: {_redact(api_key)})",
                category=ErrorCategory.UNKNOWN,
                diagnostics=diag,
            ) from e

        diag["http_status"] = getattr(resp, "status_code", None)

        if resp.status_code == 401 or resp.status_code == 403:
            raise OpenRouterProviderError(
                f"OpenRouter auth failed, HTTP {resp.status_code} (key: {_redact(api_key)})",
                category=ErrorCategory.AUTH_ERROR,
                diagnostics=diag,
            )
        if resp.status_code == 429:
            # 429 diagnostics (Phase-remediation section 6): capture the
            # documented rate-limit headers and error-body fields that
            # distinguish account-quota vs. model/provider-level throttling
            # (https://openrouter.ai/docs/api-reference/limits) -- never a
            # secret-bearing header, never the Authorization header.
            diag.update(_safe_response_headers(resp))
            try:
                err_body = resp.json()
            except ValueError:
                err_body = None
            diag.update(_safe_error_body_fields(err_body))
            raise OpenRouterProviderError(
                "OpenRouter rate limit hit, HTTP 429",
                category=ErrorCategory.RATE_LIMIT,
                diagnostics=diag,
            )
        if resp.status_code == 404:
            raise OpenRouterProviderError(
                f"OpenRouter model not found/unavailable, HTTP 404 (model={body.get('model')!r})",
                category=ErrorCategory.MODEL_UNAVAILABLE,
                diagnostics=diag,
            )
        if resp.status_code >= 400:
            diag.update(_safe_response_headers(resp))
            try:
                err_body = resp.json()
            except ValueError:
                err_body = None
            diag.update(_safe_error_body_fields(err_body))
            raise OpenRouterProviderError(
                f"OpenRouter HTTP error {resp.status_code}",
                category=ErrorCategory.HTTP_ERROR,
                diagnostics=diag,
            )

        try:
            data = resp.json()
        except ValueError as e:
            diag["envelope_parsed"] = False
            raise OpenRouterProviderError(
                f"OpenRouter returned non-JSON response body: {e}",
                category=ErrorCategory.MALFORMED_RESPONSE,
                diagnostics=diag,
            ) from e
        diag["envelope_parsed"] = True

        choices = data.get("choices") if isinstance(data, dict) else None
        diag["choices_present"] = isinstance(choices, list) and len(choices) > 0
        message = None
        if diag["choices_present"]:
            first_choice = choices[0]
            if isinstance(first_choice, dict):
                message = first_choice.get("message")
                diag["finish_reason"] = first_choice.get("finish_reason")
        diag["message_present"] = isinstance(message, dict)

        try:
            choices = data["choices"]
            text = choices[0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            diag["content_present"] = False
            raise OpenRouterProviderError(
                f"unexpected OpenRouter response shape: {e}",
                category=ErrorCategory.MALFORMED_RESPONSE,
                diagnostics=diag,
            ) from e

        diag["content_present"] = text is not None
        diag["content_length"] = len(str(text)) if text is not None else 0

        # Extract usage/request_id/model_used BEFORE the empty-content check
        # below, not after: a bug found during the Phase H token/reasoning
        # audit (DRYRUN-0005) discarded this data entirely on the empty-
        # completion path, since the raise happened first — meaning the
        # question "did OpenRouter report reasoning-token usage that
        # exhausted the budget?" could never even be ANSWERED for a failed
        # call, only guessed at. `usage` (including provider-specific
        # fields like `reasoning_tokens` inside `completion_tokens_details`,
        # when a model returns them) is now captured unconditionally.
        usage = data.get("usage") or {}
        completion_tokens_details = usage.get("completion_tokens_details") or {}
        tokens_used = usage.get("total_tokens")
        model_used = data.get("model", body.get("model"))
        request_id = data.get("id")

        diag["request_id"] = request_id
        diag["model_used"] = model_used
        diag["usage"] = {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
            "reasoning_tokens": completion_tokens_details.get("reasoning_tokens"),
            "cached_tokens": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
        }

        if not text or not str(text).strip():
            raise OpenRouterProviderError(
                "OpenRouter returned an empty completion",
                category=ErrorCategory.EMPTY_RESPONSE,
                diagnostics=diag,
            )

        return LLMResponse(
            text=text,
            tokens_used=tokens_used,
            cost_usd=None,
            model_used=model_used,
            provider="openrouter",
            request_id=request_id,
            error_category=None,
            diagnostics=diag,
        )
