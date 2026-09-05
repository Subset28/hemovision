"""Phase G — proves (a) the global network guard (tests/conftest.py) is
actually active and catches a real attempt, and (b) `.env` is gitignored so
the real key can never be accidentally committed."""

from __future__ import annotations

import subprocess

import pytest

from research.config import REPO_ROOT
from tests.conftest import UnexpectedNetworkCallError


class TestNetworkGuardIsActive:
    def test_direct_socket_connection_is_blocked(self):
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            with pytest.raises(UnexpectedNetworkCallError):
                s.connect(("openrouter.ai", 443))
        finally:
            s.close()

    def test_loopback_is_not_blocked_by_the_guard(self):
        # Sanity check that the guard is scoped to non-loopback hosts, not a
        # blanket "no sockets ever" (which would be a much blunter, less
        # honest claim about what's being tested).
        import socket

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Connecting to a closed local port raises ConnectionRefusedError
            # (a real, expected OS-level error) rather than our guard's
            # UnexpectedNetworkCallError -- proving loopback passes through.
            with pytest.raises(ConnectionRefusedError):
                s.connect(("127.0.0.1", 1))
        finally:
            s.close()


class TestEnvIsGitignored:
    def test_env_file_matches_gitignore_pattern(self):
        result = subprocess.run(
            ["git", "check-ignore", "-q", ".env"],
            cwd=REPO_ROOT,
            capture_output=True,
        )
        assert result.returncode == 0, (
            ".env must be gitignored (research/llm reads the real key from it); "
            f"git check-ignore exited {result.returncode}"
        )

    def test_env_example_has_no_real_value(self):
        example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
        for line in example.splitlines():
            if line.strip().startswith("OPENROUTER_API_KEY="):
                value = line.split("=", 1)[1].strip()
                assert value == "", ".env.example must contain only a placeholder, never a real key"
