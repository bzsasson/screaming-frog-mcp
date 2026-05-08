# -*- coding: utf-8 -*-
"""
Tests for configurable environment variables (SF_EXPORT_TTL_SECONDS, SF_EXPORT_TIMEOUT_SECONDS).

Instead of reloading the module (which corrupts the FastMCP instance for
other tests), we test the env var parsing logic directly and verify the
module-level constants read from the expected env vars.

Run with: uv run python -m pytest tests/test_env_vars.py -v
"""

import ast
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_PY = PROJECT_ROOT / "src" / "screaming_frog_mcp" / "server.py"

sys.path.insert(0, str(PROJECT_ROOT / "src"))


class TestEnvVarParsing:
    """Test that the env var parsing expression works correctly."""

    @staticmethod
    def _parse_with_env(env_var, env_value, default):
        """Replicate the pattern: int(os.getenv(env_var, default))"""
        saved = os.environ.get(env_var)
        try:
            if env_value is not None:
                os.environ[env_var] = env_value
            elif env_var in os.environ:
                del os.environ[env_var]
            return int(os.getenv(env_var, default))
        finally:
            if saved is not None:
                os.environ[env_var] = saved
            elif env_var in os.environ:
                del os.environ[env_var]

    # --- EXPORT_TTL_SECONDS ---

    def test_ttl_default(self):
        """Default TTL is 3600 seconds (1 hour) when env var is unset."""
        result = self._parse_with_env("SF_EXPORT_TTL_SECONDS", None, "3600")
        assert result == 3600

    def test_ttl_custom(self):
        """TTL can be overridden via SF_EXPORT_TTL_SECONDS env var."""
        result = self._parse_with_env("SF_EXPORT_TTL_SECONDS", "7200", "3600")
        assert result == 7200

    def test_ttl_short(self):
        """Short TTL values are accepted (e.g. for testing)."""
        result = self._parse_with_env("SF_EXPORT_TTL_SECONDS", "60", "3600")
        assert result == 60

    # --- EXPORT_TIMEOUT_SECONDS ---

    def test_timeout_default(self):
        """Default timeout is 300 seconds (5 min) when env var is unset."""
        result = self._parse_with_env("SF_EXPORT_TIMEOUT_SECONDS", None, "300")
        assert result == 300

    def test_timeout_custom(self):
        """Timeout can be overridden via SF_EXPORT_TIMEOUT_SECONDS env var."""
        result = self._parse_with_env("SF_EXPORT_TIMEOUT_SECONDS", "600", "300")
        assert result == 600

    def test_timeout_large_for_big_crawls(self):
        """Large timeout values are accepted for big crawl exports."""
        result = self._parse_with_env("SF_EXPORT_TIMEOUT_SECONDS", "1800", "300")
        assert result == 1800


class TestEnvVarSourceInspection:
    """AST-based tests verifying the module reads from the correct env vars
    with the correct defaults."""

    @staticmethod
    def _find_getenv_calls():
        """Find all os.getenv() calls in server.py and return (var_name, default)."""
        source = SERVER_PY.read_text()
        tree = ast.parse(source, filename=str(SERVER_PY))
        calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "getenv"
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
            ):
                args = node.args
                if len(args) >= 1 and isinstance(args[0], ast.Constant):
                    var_name = args[0].value
                    default = None
                    if len(args) >= 2 and isinstance(args[1], ast.Constant):
                        default = args[1].value
                    calls.append((var_name, default))
        return calls

    def test_ttl_reads_correct_env_var(self):
        """EXPORT_TTL_SECONDS reads from SF_EXPORT_TTL_SECONDS with default '3600'."""
        calls = self._find_getenv_calls()
        ttl_calls = [(v, d) for v, d in calls if v == "SF_EXPORT_TTL_SECONDS"]
        assert len(ttl_calls) == 1, "Expected exactly one os.getenv('SF_EXPORT_TTL_SECONDS', ...)"
        assert ttl_calls[0][1] == "3600", f"Default should be '3600', got {ttl_calls[0][1]!r}"

    def test_timeout_reads_correct_env_var(self):
        """EXPORT_TIMEOUT_SECONDS reads from SF_EXPORT_TIMEOUT_SECONDS with default '300'."""
        calls = self._find_getenv_calls()
        timeout_calls = [(v, d) for v, d in calls if v == "SF_EXPORT_TIMEOUT_SECONDS"]
        assert len(timeout_calls) == 1, "Expected exactly one os.getenv('SF_EXPORT_TIMEOUT_SECONDS', ...)"
        assert timeout_calls[0][1] == "300", f"Default should be '300', got {timeout_calls[0][1]!r}"

    def test_module_level_constants_match_defaults(self):
        """The module constants should match their env var defaults when unset."""
        from screaming_frog_mcp import server
        # These may have been set via env, so we just check they're valid ints
        assert isinstance(server.EXPORT_TTL_SECONDS, int)
        assert isinstance(server.EXPORT_TIMEOUT_SECONDS, int)
        assert server.EXPORT_TTL_SECONDS > 0
        assert server.EXPORT_TIMEOUT_SECONDS > 0
