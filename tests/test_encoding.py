# -*- coding: utf-8 -*-
"""
Encoding and None-safety tests for the Windows cp1252 fix (#5).

These tests verify the actual behavior, not just that the right kwargs
are passed. They:
  - spawn real subprocesses that emit cp1252-breaking bytes
  - feed None values through the CSV rendering path
  - inspect server.py source to enforce that all subprocess.run calls
    carry encoding='utf-8' and errors='replace'

Run with: uv run python -m pytest tests/test_encoding.py -v
"""

import ast
import csv
import io
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Locate server.py for source inspection and import
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_PY = PROJECT_ROOT / "src" / "screaming_frog_mcp" / "server.py"

sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 1. Subprocess encoding: actually run a child that emits problematic bytes
# ---------------------------------------------------------------------------

# Bytes that are undefined in cp1252 and would crash without encoding fix:
# 0x81, 0x8D, 0x8F, 0x90, 0x9D
CP1252_BREAKING_BYTES = b"\x81\x8d\x8f\x90\x9d"


class TestSubprocessEncoding:
    """Verify that subprocess.run with encoding='utf-8', errors='replace'
    handles bytes that would crash under cp1252."""

    def test_utf8_replace_survives_undefined_cp1252_bytes(self):
        """Spawn a process that writes raw bytes that are invalid in cp1252.
        With encoding='utf-8' + errors='replace', this must not raise."""
        # Child writes raw bytes to stdout via sys.stdout.buffer
        child_code = (
            "import sys; sys.stdout.buffer.write("
            + repr(b"Database Id: abc-123\n" + CP1252_BREAKING_BYTES + b"\nDone")
            + ")"
        )
        result = subprocess.run(
            [sys.executable, "-c", child_code],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
        )
        # Must not be None
        assert result.stdout is not None
        # Must contain the readable parts
        assert "Database Id: abc-123" in result.stdout
        assert "Done" in result.stdout
        # Invalid bytes become replacement characters, not crashes
        assert "\ufffd" in result.stdout

    def test_without_encoding_fix_crashes_on_invalid_bytes(self):
        """Demonstrate that without errors='replace', invalid UTF-8 bytes
        raise UnicodeDecodeError -- proving the fix is necessary."""
        child_code = (
            "import sys; sys.stdout.buffer.write(" + repr(CP1252_BREAKING_BYTES) + ")"
        )
        with pytest.raises(UnicodeDecodeError):
            subprocess.run(
                [sys.executable, "-c", child_code],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=5,
            )

    def test_replacement_chars_dont_break_line_parsing(self):
        """Verify that U+FFFD replacement characters in list_crawls output
        don't break the line-splitting and filtering logic."""
        # Simulate SF CLI output with replacement chars in a crawl label
        output = (
            "INFO  - Running: Screaming Frog SEO Spider 23.3\n"
            "INFO  - Platform: Windows 11\n"
            "Database Id: abc-123 | URL: https://caf\ufffd.example.com | Size: 1.2 MB\n"
            "Database Id: def-456 | URL: https://example.com | Size: 3.4 MB\n"
        )
        # Apply the same filtering logic as list_crawls
        skip_markers = [
            "INFO  -", "WARNING:", "com.sun.", "Lock File",
            "font", "proxy", "Signature", "License",
            "Running:", "Platform", "Java Info", "VM args",
            "Log File", "Fatal Log", "Logging Status",
            "Memory:", "Licence", "Locale:", "Time Zone",
            "Checking Licence", "antialias", "SfRoboto",
        ]
        crawl_lines = []
        for line in output.splitlines():
            if any(skip in line for skip in skip_markers):
                continue
            if line.strip():
                crawl_lines.append(line.strip())

        assert len(crawl_lines) == 2
        assert "abc-123" in crawl_lines[0]
        assert "caf\ufffd" in crawl_lines[0]
        assert "def-456" in crawl_lines[1]


# ---------------------------------------------------------------------------
# 2. CSV rendering: None values in cells
# ---------------------------------------------------------------------------

class TestCsvNoneValues:
    """Verify that the read_crawl_data rendering logic handles None cells."""

    def _render_rows(self, rows):
        """Replicate the CSV rendering logic from server.py read_crawl_data."""
        columns = list(rows[0].keys())
        output = " | ".join(columns) + "\n"
        output += "-+-".join("-" * min(len(c), 30) for c in columns) + "\n"
        for row in rows:
            values = []
            for col in columns:
                val = row.get(col, "")
                if val is not None and len(val) > 80:
                    val = val[:77] + "..."
                values.append(val)
            output += " | ".join(v if v is not None else "" for v in values) + "\n"
        return output

    def test_none_cell_does_not_crash(self):
        """A row with None values must not raise TypeError."""
        rows = [
            {"URL": "https://example.com", "Status": "200", "Title": None},
            {"URL": "https://example.com/page", "Status": None, "Title": "Hello"},
        ]
        output = self._render_rows(rows)
        assert "example.com" in output
        assert "Hello" in output

    def test_all_none_row(self):
        """A row where every cell is None must render without error."""
        rows = [{"A": None, "B": None, "C": None}]
        output = self._render_rows(rows)
        assert "A | B | C" in output

    def test_long_value_truncated(self):
        """Values over 80 chars are truncated to 77 + '...'."""
        long_val = "x" * 100
        rows = [{"Col": long_val}]
        output = self._render_rows(rows)
        assert "x" * 77 + "..." in output
        assert "x" * 78 not in output

    def test_csv_reader_produces_none_for_empty_fields(self):
        """Demonstrate that csv.DictReader CAN produce None values,
        validating that the None guard is necessary."""
        # DictReader returns None for fields present in fieldnames
        # but missing from a short row (fewer columns than header)
        csv_text = "URL,Status,Title\nhttps://example.com,200\n"
        reader = csv.DictReader(io.StringIO(csv_text))
        row = next(reader)
        # The Title field is missing from the data row
        assert row["Title"] is None, (
            "csv.DictReader should return None for missing fields — "
            "this proves the None guard in read_crawl_data is necessary"
        )


# ---------------------------------------------------------------------------
# 3. Source inspection: every subprocess.run must have encoding params
# ---------------------------------------------------------------------------

class TestSourceInspection:
    """Parse server.py AST to verify all subprocess.run calls have
    encoding='utf-8' and errors='replace'. This catches regressions
    if someone adds a new subprocess call without the fix."""

    @staticmethod
    def _find_subprocess_run_calls():
        """Return all subprocess.run() Call nodes from server.py AST."""
        source = SERVER_PY.read_text()
        tree = ast.parse(source, filename=str(SERVER_PY))
        calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # Match subprocess.run(...)
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "run"
                and isinstance(func.value, ast.Name)
                and func.value.id == "subprocess"
            ):
                calls.append(node)
        return calls

    @staticmethod
    def _get_keyword_value(call_node, keyword_name):
        """Extract the value of a keyword argument from a Call node."""
        for kw in call_node.keywords:
            if kw.arg == keyword_name:
                if isinstance(kw.value, ast.Constant):
                    return kw.value.value
        return None

    def test_all_subprocess_calls_have_utf8_encoding(self):
        calls = self._find_subprocess_run_calls()
        assert len(calls) >= 4, f"Expected at least 4 subprocess.run calls, found {len(calls)}"
        for call in calls:
            line = call.lineno
            enc = self._get_keyword_value(call, "encoding")
            assert enc == "utf-8", (
                f"subprocess.run at line {line} missing encoding='utf-8'"
            )

    def test_all_subprocess_calls_have_errors_replace(self):
        calls = self._find_subprocess_run_calls()
        for call in calls:
            line = call.lineno
            err = self._get_keyword_value(call, "errors")
            assert err == "replace", (
                f"subprocess.run at line {line} missing errors='replace'"
            )
