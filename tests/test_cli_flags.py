# -*- coding: utf-8 -*-
"""
Tests for command-line flags on the server entry point.

The binary speaks MCP on stdin by default, which makes "what version is
this?" needlessly hard to answer (TROUBLESHOOTING.md documents the
workaround). --version and --help should answer without starting the server.

Run with: uv run python -m pytest tests/test_cli_flags.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import screaming_frog_mcp.server as server


@pytest.fixture
def no_server_start(monkeypatch):
    """Fail the test if main() falls through to starting the MCP server."""
    def boom():
        raise AssertionError("mcp.run() must not be called for informational flags")
    monkeypatch.setattr(server.mcp, "run", boom)


class TestVersionFlag:
    def test_version_prints_package_version(self, no_server_start, capsys):
        server.main(["--version"])
        out = capsys.readouterr().out
        assert "screaming-frog-mcp" in out
        # A semantic version like 0.4.0 appears
        import re
        assert re.search(r"\d+\.\d+\.\d+", out)

    def test_short_version_flag(self, no_server_start, capsys):
        server.main(["-V"])
        out = capsys.readouterr().out
        assert "screaming-frog-mcp" in out


class TestHelpFlag:
    def test_help_describes_server_and_flags(self, no_server_start, capsys):
        server.main(["--help"])
        out = capsys.readouterr().out
        assert "MCP server" in out
        assert "--version" in out

    def test_short_help_flag(self, no_server_start, capsys):
        server.main(["-h"])
        out = capsys.readouterr().out
        assert "--version" in out


class TestDefaultBehavior:
    def test_no_args_starts_server(self, monkeypatch):
        called = {}
        monkeypatch.setattr(server.mcp, "run", lambda: called.setdefault("run", True))
        server.main([])
        assert called.get("run") is True

    def test_unknown_flag_errors_without_starting(self, no_server_start, capsys):
        with pytest.raises(SystemExit):
            server.main(["--bogus"])
        err = capsys.readouterr().err
        assert "bogus" in err
