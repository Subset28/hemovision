"""Phase G — privacy / data-boundary guard.

`check_payload_safe(payload)` is a cheap, mechanical, pattern-based scan run
against every outgoing LLM request payload (system + user content combined)
BEFORE it is sent — including research/llm/smoke_test.py's tiny payload. Any
violation blocks the call; see research/llm/router.py / openrouter.py for
where this is wired in.

What this catches (best-effort):
  - A literal `OPENROUTER_API_KEY=<value>` assignment (or similarly named
    *_API_KEY/_SECRET/_TOKEN/_PASSWORD assignments) — the shape of an
    accidentally-pasted .env line or exception dump.
  - A raw multi-line `.env`-style dump (several `KEY=value` lines in a row).
  - A `Bearer <token>` header value, or an OpenRouter/OpenAI-style `sk-...`
    key literal.
  - An absolute Windows user-profile path (`C:\\Users\\<name>\\...`), which
    can leak the local username.

What this explicitly does NOT catch (documented limits, not overclaimed):
  - Obfuscated or encoded secrets (base64, split across lines, etc.).
  - Secrets that don't look like `KEY=value` or `Bearer ...` (e.g. a bare
    32-character token with no surrounding context).
  - Photographs, audio, or other binary/non-text identifying content — this
    guard only inspects text payloads; there is no code path in this phase
    that would attach binary media to an LLM request in the first place
    (research/llm/context_builder.py never pulls files automatically).
  - Novel PII formats (names, addresses, phone numbers) — no NLP/PII model
    is used here, only literal pattern matching.
  - Any secret embedded inside caller-supplied free text that happens not to
    match these specific patterns.

This is a best-effort heuristic layer, not a security boundary. The primary
defenses against key leakage are structural (the key is read from `os.environ`
only inside research/llm/openrouter.py, is never interpolated into an
exception message or log line, and this guard is a second, independent
check on top of that discipline) — not this pattern list alone.
"""

from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("openrouter_api_key_literal", re.compile(r"OPENROUTER_API_KEY\s*[:=]\s*\S+")),
    (
        "generic_secret_assignment",
        re.compile(r"\b[A-Z][A-Z0-9_]*(?:_API_KEY|_SECRET|_TOKEN|_PASSWORD)\s*[:=]\s*['\"]?[A-Za-z0-9._\-]{6,}"),
    ),
    (
        "dotenv_style_dump",
        re.compile(r"(?m)^[A-Z_][A-Z0-9_]*=.*\r?\n[A-Z_][A-Z0-9_]*=.*"),
    ),
    ("bearer_token_header", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{16,}")),
    ("sk_style_key_literal", re.compile(r"\bsk-[A-Za-z0-9]{10,}\b")),
    ("windows_user_profile_path", re.compile(r"[A-Za-z]:\\+Users\\+[^\\\s]+")),
]


def check_payload_safe(payload: str) -> list[str]:
    """Return a list of violation names found in `payload` (empty if clean).
    Never raises — callers decide whether a non-empty list should block the
    call (it should, per Phase G section 7 — see research/llm/router.py)."""
    if not payload:
        return []
    violations = []
    for name, pattern in _PATTERNS:
        if pattern.search(payload):
            violations.append(name)
    return violations


class PrivacyViolationError(RuntimeError):
    """Raised by call sites that choose to hard-block on a non-empty
    check_payload_safe() result, rather than merely inspecting the list."""
