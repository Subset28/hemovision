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
