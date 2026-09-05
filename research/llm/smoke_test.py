"""Phase G — the ONE authorized live OpenRouter smoke test for this entire
phase.

This is a standalone, manually-run script — NOT part of the pytest suite
(it lives outside tests/ and is named smoke_test.py, not test_*.py/*_test.py,
so pytest's default collection never picks it up; tests/conftest.py's
network guard would also refuse this call if it somehow ran under pytest).

Run it manually:  python -m research.llm.smoke_test

What it does, in order, matching the Phase G task spec's section 12 exactly:
  1. Loads OPENROUTER_API_KEY from `.env` (manual parsing — no dotenv
     dependency exists in this project's pyproject.toml, and the key is
     already exported by whatever mechanism populated `.env`; we do not add
     a new dependency for this one script).
  2. Explicitly grants authorization via LLMCallAuthorization.grant(reason=...)
     — the ONE place in this entire codebase where a real call is
     deliberately authorized. This is the human-delegated operator (running
     this script) explicitly authorizing exactly this one documented smoke
     test, per research/llm/authorization.py's design: a configured key
     never authorizes anything by itself.
  3. Checks the daily budget (UsageTracker) BEFORE proceeding and reports
     the before-state.
  4. Builds an absolutely minimal, non-sensitive payload (a harmless system
     message + a user message asking for a fixed literal reply). No
     repository content, benchmark data, research memory dump, code, or key
     value is ever included in the payload.
  5. Runs research/llm/privacy_guard.py's check_payload_safe() against that
     payload FIRST. If it is somehow flagged, this script stops and reports
     rather than overriding the guard.
  6. Picks ONE specific OpenRouter model id and does not try a second one
     live if the first fails (see MODEL_ID and the comment below for the
     reasoning).
  7. Makes exactly ONE HTTP request, with max_retries=0 so the provider's
     own bounded-retry logic (research/llm/openrouter.py, normally up to 2
     retries for transient errors) is disabled for this one call — the total
     external request count for this entire task is provably exactly one,
     regardless of outcome.
  8. Records the result via UsageTracker.record_call() (Phase G's documented
     policy: both success and failure count against budget) and reports the
     after-state.
  9. Prints a safe, key-redacted summary matching section 13's report
     requirements.

Model choice history (Phase G completion round)
-------------------------------------------------
First Phase G attempt picked `meta-llama/llama-3.1-8b-instruct:free` from
prior knowledge (not verified live) and made the one authorized call for
that round: it returned **HTTP 404 / MODEL_UNAVAILABLE** — that slug is
confirmed stale/no longer served by OpenRouter. Per the task spec at the
time, that single clean failure was an acceptable stopping point; no second
model was tried live in that round.

For this completion round, an explicitly-approved discovery step queried
OpenRouter's public, unauthenticated `/api/v1/models` catalog endpoint (a
plain GET requiring no API key, no `Authorization` header, and no
chat-completion request — it does not touch `OPENROUTER_API_KEY`, is not
routed through research/llm/openrouter.py's provider abstraction, and does
not increment UsageTracker; it is not "a call" in the sense this phase's
one-authorized-live-call budget governs) and confirmed several currently
free, text-capable model ids, including `poolside/laguna-s-2.1:free` —
notably one of the exact models named in the project's original master
plan ("Poolside Laguna S 2.1 Free"). MODEL_ID below is updated to this
freshly-verified slug for the one additional authorized live chat-completion
call this completion round permits. The stale slug is deliberately left
untouched (not deleted from history) above/in git log as the documented
record of what failed and why.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from research.config import REPO_ROOT
from research.llm.authorization import LLMCallAuthorization
from research.llm.base import LLMUnavailableError
from research.llm.openrouter import OpenRouterProvider
from research.llm.privacy_guard import check_payload_safe

MODEL_ID = "poolside/laguna-s-2.1:free"  # verified live via OpenRouter's public /models catalog, see docstring above
STALE_MODEL_ID_DO_NOT_REUSE = "meta-llama/llama-3.1-8b-instruct:free"  # confirmed 404/MODEL_UNAVAILABLE, kept for record

SYSTEM_MESSAGE = (
    "This is a harmless, one-time connectivity smoke test for the OmniSight "
    "research lab's LLM abstraction layer (Phase G). No action is required "
    "beyond replying exactly as instructed."
)
USER_MESSAGE = "Reply with exactly this text and nothing else: OMNILAB_OPENROUTER_OK"


def _load_dotenv(env_path: Path) -> None:
    """Minimal, dependency-free .env loader — sets os.environ for any
    KEY=value line not already present in the environment. No dotenv
    dependency exists in pyproject.toml/uv.lock, so this avoids adding one
    for a single manual script. Never prints the file's contents."""
    import os

    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


def _redact_key(key: str | None) -> str:
    if not key:
        return "unset"
    return f"set(len={len(key)})"


def main() -> int:
    import os

    _load_dotenv(REPO_ROOT / ".env")

    key_present = bool(os.environ.get("OPENROUTER_API_KEY", "").strip())
    print(f"[smoke_test] OPENROUTER_API_KEY: {_redact_key(os.environ.get('OPENROUTER_API_KEY'))}")

    if not key_present:
        print("[smoke_test] No API key configured — stopping before any network attempt.")
        return 1

    from research.llm.base import UsageTracker

    tracker = UsageTracker()
    before = tracker.calls_today()
    remaining_before = tracker.remaining_today()
    print(f"[smoke_test] Budget BEFORE: {before}/{tracker.max_per_day} used, {remaining_before} remaining")

    try:
        tracker.check_budget()
    except LLMUnavailableError as e:
        print(f"[smoke_test] Budget exhausted, refusing to proceed: {e}")
        return 1

    # 2. The ONE explicit authorization grant in this entire codebase for a
    #    real network call. This is a clearly-commented, deliberate act by
    #    the human operator running this script for this one documented
    #    purpose — not a default, not implicit from the key being present.
    authorization = LLMCallAuthorization.grant(
        reason="Phase G section 12 — single authorized live OpenRouter smoke test, "
        "manually run by the human operator to prove the abstraction layer works end-to-end."
    )

    messages = [
        {"role": "system", "content": SYSTEM_MESSAGE},
        {"role": "user", "content": USER_MESSAGE},
    ]
    payload_text = "\n".join(m["content"] for m in messages)

    violations = check_payload_safe(payload_text)
    if violations:
        print(f"[smoke_test] Privacy guard flagged the payload: {violations} — STOPPING, not overriding it.")
        return 1
    print("[smoke_test] Privacy guard: payload clean, proceeding.")

    provider = OpenRouterProvider()

    print(f"[smoke_test] Model: {MODEL_ID}")
    print("[smoke_test] Making the ONE authorized live HTTP request (max_retries=0)...")

    start = time.monotonic()
    outcome_ok = False
    try:
        response = provider.complete(
            prompt=USER_MESSAGE,
            role="researcher",
            model=MODEL_ID,
            authorized=authorization,
            messages=messages,
            max_retries=0,  # provably exactly one HTTP request, regardless of outcome
            timeout_sec=30,
        )
        outcome_ok = True
    except LLMUnavailableError as e:
        elapsed_ms = (time.monotonic() - start) * 1000.0
        # Record the attempt regardless of outcome (Phase G section 5's
        # explicit policy: a failed call still counts).
        after = tracker.record_call()
        remaining_after = tracker.remaining_today()
        print(f"[smoke_test] Call FAILED. category={e.category} message={e}")
        print(f"[smoke_test] Latency: {elapsed_ms:.1f} ms")
        print(f"[smoke_test] Budget AFTER: {after}/{tracker.max_per_day} used, {remaining_after} remaining")
        print("[smoke_test] Key was never logged above — only a redacted 'set(len=N)'/'unset' marker was printed.")
        return 0  # a clean, informative failure is still a valid smoke-test outcome

    after = tracker.record_call()
    remaining_after = tracker.remaining_today()

    print(f"[smoke_test] Call SUCCEEDED.")
    print(f"[smoke_test] Provider: {response.provider}  Model used: {response.model_used}")
    print(f"[smoke_test] Response text: {response.text!r}")
    print(f"[smoke_test] Expected text received: {response.text.strip() == 'OMNILAB_OPENROUTER_OK'}")
    print(f"[smoke_test] Tokens used: {response.tokens_used}")
    print(f"[smoke_test] Latency: {response.latency_ms:.1f} ms" if response.latency_ms else "[smoke_test] Latency: unknown")
    print(f"[smoke_test] Request ID: {response.request_id}")
    print(f"[smoke_test] Budget AFTER: {after}/{tracker.max_per_day} used, {remaining_after} remaining")
    print("[smoke_test] Key was never logged above — only a redacted 'set(len=N)'/'unset' marker was printed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
