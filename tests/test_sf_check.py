# -*- coding: utf-8 -*-
"""
Tests for sf_check() -- version/license parsing from --list-crawls output.

Run with: uv run python -m pytest tests/test_sf_check.py -v
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from screaming_frog_mcp.server import sf_check, SF_CLI_PATH


# ---------------------------------------------------------------------------
# Version and license extraction from --list-crawls output
# ---------------------------------------------------------------------------

class TestSfCheckParsing:
    """Tests for sf_check parsing of --list-crawls startup logs."""

    TYPICAL_OUTPUT = (
        "INFO  - Running: Screaming Frog SEO Spider 23.2\n"
        "INFO  - Platform: macOS 15.5\n"
        "INFO  - Java Info: 21.0.6+7-LTS\n"
        "INFO  - Licence Status: Active, expires on 26 Jul 2026 GMT. (Username: testuser)\n"
        "INFO  - Checking Licence\n"
        "Database Id: abc-123 | Name: example | URL: https://example.com/ | Mode: Spider\n"
    )

    @patch("screaming_frog_mcp.server.os.path.exists", return_value=True)
    @patch("screaming_frog_mcp.server.subprocess.run")
    def test_extracts_version(self, mock_run, mock_exists):
        mock_run.return_value = MagicMock(stdout=self.TYPICAL_OUTPUT, stderr="")
        result = sf_check()
        assert "Version: Screaming Frog SEO Spider 23.2" in result

    @patch("screaming_frog_mcp.server.os.path.exists", return_value=True)
    @patch("screaming_frog_mcp.server.subprocess.run")
    def test_extracts_license(self, mock_run, mock_exists):
        mock_run.return_value = MagicMock(stdout=self.TYPICAL_OUTPUT, stderr="")
        result = sf_check()
        assert "License: Active, expires on 26 Jul 2026 GMT. (Username: testuser)" in result

    @patch("screaming_frog_mcp.server.os.path.exists", return_value=True)
    @patch("screaming_frog_mcp.server.subprocess.run")
    def test_success_message(self, mock_run, mock_exists):
        mock_run.return_value = MagicMock(stdout=self.TYPICAL_OUTPUT, stderr="")
        result = sf_check()
        assert "Screaming Frog is installed and accessible." in result

    @patch("screaming_frog_mcp.server.os.path.exists", return_value=True)
    @patch("screaming_frog_mcp.server.subprocess.run")
    def test_uses_list_crawls_not_help(self, mock_run, mock_exists):
        """Verify sf_check calls --list-crawls, not --help."""
        mock_run.return_value = MagicMock(stdout="", stderr="")
        sf_check()
        args = mock_run.call_args[0][0]
        assert "--list-crawls" in args
        assert "--help" not in args
        assert "--headless" in args

    @patch("screaming_frog_mcp.server.os.path.exists", return_value=True)
    @patch("screaming_frog_mcp.server.subprocess.run")
    def test_unknown_when_no_version_in_output(self, mock_run, mock_exists):
        """When SF output lacks version line, version should be 'unknown'."""
        mock_run.return_value = MagicMock(stdout="some other output\n", stderr="")
        result = sf_check()
        assert "Version: unknown" in result

    @patch("screaming_frog_mcp.server.os.path.exists", return_value=True)
    @patch("screaming_frog_mcp.server.subprocess.run")
    def test_unknown_when_no_license_in_output(self, mock_run, mock_exists):
        """When SF output lacks license line, license should be 'unknown'."""
        mock_run.return_value = MagicMock(stdout="some other output\n", stderr="")
        result = sf_check()
        assert "License: unknown" in result

    @patch("screaming_frog_mcp.server.os.path.exists", return_value=True)
    @patch("screaming_frog_mcp.server.subprocess.run")
    def test_version_from_stderr(self, mock_run, mock_exists):
        """Version info can appear in stderr (SF writes startup logs there)."""
        mock_run.return_value = MagicMock(
            stdout="",
            stderr="INFO  - Running: Screaming Frog SEO Spider 24.0\n",
        )
        result = sf_check()
        assert "Version: Screaming Frog SEO Spider 24.0" in result


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestSfCheckErrors:
    """Tests for sf_check error paths."""

    @patch("screaming_frog_mcp.server.os.path.exists", return_value=False)
    def test_missing_cli(self, mock_exists):
        result = sf_check()
        assert "ERROR" in result
        assert "not found" in result

    @patch("screaming_frog_mcp.server.os.path.exists", return_value=True)
    @patch("screaming_frog_mcp.server.subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 60))
    def test_timeout(self, mock_run, mock_exists):
        result = sf_check()
        assert "timed out" in result

    @patch("screaming_frog_mcp.server.os.path.exists", return_value=True)
    @patch("screaming_frog_mcp.server.subprocess.run", side_effect=OSError("Permission denied"))
    def test_exception_includes_type_and_message(self, mock_run, mock_exists):
        """Error message must include exception type and message."""
        result = sf_check()
        assert "OSError" in result
        assert "Permission denied" in result
        assert "ERROR" in result
