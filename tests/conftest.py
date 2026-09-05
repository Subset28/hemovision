"""Repo-wide pytest configuration.

Phase G section 14 requires an explicit, provable guarantee that the pytest
suite makes ZERO real network calls (research/llm/smoke_test.py, the one
authorized live OpenRouter call for this phase, is a standalone script NOT
collected by pytest — see that file's own docstring).

Approach taken (documented per the task spec's "state clearly which
approach you used"): a session-wide, autouse fixture that monkeypatches
`socket.socket.connect`/`connect_ex` to raise immediately for any outbound
connection attempt. This is a belt-and-suspenders backstop on top of every
individual Phase G test mocking the `requests` layer directly — even if a
test forgot to mock `requests.post`, the attempt would fail here instead of
silently reaching the network. Loopback connections (127.0.0.1/::1) are left
alone since nothing in this suite talks to a local server and blocking
loopback too would risk breaking unrelated local-only test infrastructure
(e.g. a future local test server) for no safety benefit.
"""

from __future__ import annotations

import socket

import pytest

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class UnexpectedNetworkCallError(RuntimeError):
    """Raised when test code attempts a real outbound network connection.
    The entire Phase G unit test suite is designed to mock the HTTP layer —
    if this fires, a test is missing a mock, not exercising real behavior."""


def _guarded_connect(self, address, *a, **k):
    host = address[0] if isinstance(address, tuple) else address
    if host not in _LOOPBACK:
        raise UnexpectedNetworkCallError(
            f"blocked outbound network connection attempt to {address!r} during "
            "the pytest suite — every test must mock the HTTP layer; no real "
            "network call is permitted here. (research/llm/smoke_test.py is the "
            "one deliberate exception and is not collected by pytest.)"
        )
    return _real_connect(self, address, *a, **k)


def _guarded_connect_ex(self, address, *a, **k):
    host = address[0] if isinstance(address, tuple) else address
    if host not in _LOOPBACK:
        raise UnexpectedNetworkCallError(
            f"blocked outbound network connection attempt to {address!r} during the pytest suite."
        )
    return _real_connect_ex(self, address, *a, **k)


@pytest.fixture(autouse=True, scope="session")
def _block_real_network_calls():
    socket.socket.connect = _guarded_connect
    socket.socket.connect_ex = _guarded_connect_ex
    try:
        yield
    finally:
        socket.socket.connect = _real_connect
        socket.socket.connect_ex = _real_connect_ex


class _PermissiveTestCatalog(dict):
    """Phase-I-readiness CRITICAL fix #2 made research/dry_run/pipeline.py's
    free-model-only pre-flight UNCONDITIONAL: a caller (including every test
    in this suite) that doesn't pass an explicit `model_catalog` now
    triggers `_default_fetch_model_catalog()` -- a real network GET, which
    `_block_real_network_calls` above would correctly refuse.

    This autouse fixture replaces that fetch with a fake, always-permissive
    "catalog" (free pricing + full structured-output capability + non-
    mandatory reasoning for ANY model id looked up) so the pre-existing
    dry-run tests that never cared about catalog/free-model mechanics keep
    passing without a real network call. It deliberately does NOT hardcode
    a specific model id (e.g. research/llm/roles.yaml's current
    `preferred_model`) — that would silently break every time roles.yaml is
    edited. A test that specifically wants to exercise catalog
    rejection/eligibility passes its own explicit `model_catalog=...` kwarg,
    which always takes precedence over this fixture (see
    research/dry_run/pipeline.py::_resolve_model_catalog — the real fetch is
    only ever called when the caller passed None)."""

    def get(self, key, default=None):  # noqa: D102 - dict.get override, deliberate
        return {
            "pricing": {"prompt": "0", "completion": "0"},
            "supported_parameters": ["response_format", "structured_outputs"],
            "reasoning": {"mandatory": False},
        }

    def __contains__(self, key) -> bool:
        return True


@pytest.fixture(autouse=True)
def _default_permissive_model_catalog(monkeypatch):
    import research.dry_run.pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "_default_fetch_model_catalog", lambda: _PermissiveTestCatalog())


@pytest.fixture(autouse=True)
def _isolated_operational_state(tmp_path, monkeypatch):
    """research/operational_state.py::STATE_PATH points at a real,
    persistent, gitignored file (research/orchestrator_state.json) shared
    across the whole repo -- including any real `omnilab pause`/`stop` a
    human operator has actually issued outside this test run. Without this
    fixture, (a) a test calling pause()/stop() would leak PAUSED/STOPPED
    into every other test and even into the user's real session, and (b) if
    the real file ever legitimately holds paused/stopped=true, every dry-run
    test in this suite would spuriously fail their operational_state.check_gate()
    call. Every test gets its own fresh, per-test temp state file instead."""
    import research.operational_state as operational_state_mod

    monkeypatch.setattr(operational_state_mod, "STATE_PATH", tmp_path / "orchestrator_state.json")
