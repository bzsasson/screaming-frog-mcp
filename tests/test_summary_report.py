# -*- coding: utf-8 -*-
"""
Tests for SF summary report parsing (crawl_overview.csv and similar).

Run with: uv run python -m pytest tests/test_summary_report.py -v
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sf_mcp import (
    _is_sf_summary_report,
    _read_sf_summary_report,
    _export_dirs,
    read_crawl_data,
)


# ---------------------------------------------------------------------------
# _is_sf_summary_report detection
# ---------------------------------------------------------------------------

class TestIsSfSummaryReport:
    """Tests for detecting SF summary report format from the first line."""

    @pytest.mark.parametrize("first_line", [
        '"Site Crawled","https://example.com/"\n',
        '"Site Crawled","https://technicalseonews.com/"\n',
        '"Site Crawled","http://example.com/path"\n',
        # Unquoted variant (unlikely but defensive)
        'Site Crawled,https://example.com/\n',
    ])
    def test_detects_summary_report(self, first_line):
        assert _is_sf_summary_report(first_line) is True

    @pytest.mark.parametrize("first_line,reason", [
        ("URL,Status Code,Word Count\n", "tabular CSV header"),
        ("Address,Content Type,Status Code\n", "SF tabular export header"),
        ("", "empty line"),
        ("\n", "blank line"),
        ('"Not Site Crawled","https://example.com/"\n', "wrong key"),
        ('"Site Crawled","https://example.com/","extra"\n', "three cells"),
    ])
    def test_rejects_non_summary(self, first_line, reason):
        assert _is_sf_summary_report(first_line) is False, f"Should reject {reason}"


# ---------------------------------------------------------------------------
# Full summary report parsing
# ---------------------------------------------------------------------------

SAMPLE_CRAWL_OVERVIEW = """\
"Site Crawled","https://example.com/"
"Start Date","2026-05-01"
"Start Time","10:30:00"
"Report Date","2026-05-08"
""
"Summary","URLs","% of Total","Total URLs","Total URLs Description"
"Total URLs Encountered","100","100.00%","100","URLs Encountered"
"Total URLs Crawled","80","80.00%","100","URLs Encountered"
""
"Internal"
"All","60","100.00%","60","Internal URLs"
"HTML","40","66.67%","60","Internal URLs"
"JavaScript","5","8.33%","60","Internal URLs"
"CSS","10","16.67%","60","Internal URLs"
"Images","5","8.33%","60","Internal URLs"
""
"Response Codes"
"All","100","100.00%","100","All URLs"
"Success (2xx)","90","90.00%","100","All URLs"
"Client Error (4xx)","10","10.00%","100","All URLs"
""
"Depth (Clicks from Start URL)"
"0","1","1.00%","100","Internal HTML pages"
"1","20","20.00%","100","Internal HTML pages"
"2","30","30.00%","100","Internal HTML pages"
""
"Response Time (Seconds)","URLs","% of Total"
"1","80","80.00%"
"2","20","20.00%"
"""


class TestReadSfSummaryReport:
    """Tests for _read_sf_summary_report parser."""

    @pytest.fixture
    def summary_export(self, tmp_path):
        """Create a mock export with a summary report CSV."""
        export_id = "test-summary"
        export_dir = tmp_path / export_id
        subdir = export_dir / "2026.05.08"
        subdir.mkdir(parents=True)
        csv_file = subdir / "crawl_overview.csv"
        csv_file.write_text(SAMPLE_CRAWL_OVERVIEW, encoding="utf-8")
        _export_dirs[export_id] = {
            "path": export_dir,
            "created": time.time(),
            "db_id": "test",
        }
        yield export_id
        _export_dirs.pop(export_id, None)

    def test_returns_summary_report_header(self, summary_export):
        result = read_crawl_data(summary_export, "crawl_overview.csv")
        assert "(Screaming Frog summary report)" in result

    def test_header_key_value_pairs(self, summary_export):
        result = read_crawl_data(summary_export, "crawl_overview.csv")
        assert "Site Crawled: https://example.com/" in result
        assert "Start Date: 2026-05-01" in result
        assert "Start Time: 10:30:00" in result
        assert "Report Date: 2026-05-08" in result

    def test_section_headers(self, summary_export):
        result = read_crawl_data(summary_export, "crawl_overview.csv")
        assert "=== Internal ===" in result
        assert "=== Response Codes ===" in result
        assert "=== Depth (Clicks from Start URL) ===" in result

    def test_data_rows_with_counts_and_percents(self, summary_export):
        result = read_crawl_data(summary_export, "crawl_overview.csv")
        assert "HTML: 40 (66.67%)" in result
        assert "Success (2xx): 90 (90.00%)" in result
        assert "Client Error (4xx): 10 (10.00%)" in result

    def test_numeric_depth_labels(self, summary_export):
        result = read_crawl_data(summary_export, "crawl_overview.csv")
        assert "0: 1 (1.00%)" in result
        assert "1: 20 (20.00%)" in result
        assert "2: 30 (30.00%)" in result

    def test_tabular_csv_still_works(self, tmp_path):
        """Verify that normal tabular CSVs are NOT routed to the summary parser."""
        export_id = "test-tabular"
        export_dir = tmp_path / export_id
        export_dir.mkdir()
        csv_file = export_dir / "internal_all.csv"
        csv_file.write_text(
            "URL,Status Code,Word Count\n"
            "https://example.com/,200,1500\n"
            "https://example.com/about,200,800\n"
        )
        _export_dirs[export_id] = {
            "path": export_dir,
            "created": time.time(),
            "db_id": "test",
        }
        try:
            result = read_crawl_data(export_id, "internal_all.csv")
            assert "(Screaming Frog summary report)" not in result
            assert "URL" in result
            assert "Status Code" in result
            assert "example.com" in result
        finally:
            _export_dirs.pop(export_id, None)


# ---------------------------------------------------------------------------
# Error message improvement
# ---------------------------------------------------------------------------

class TestErrorMessages:
    """Verify that parse errors surface useful diagnostics."""

    def test_error_includes_exception_info(self, tmp_path):
        """When a file fails to parse, the error should include the exception type."""
        export_id = "test-error"
        export_dir = tmp_path / export_id
        export_dir.mkdir()
        # Create a file that will cause an error when opened as CSV
        # (binary content that's not valid text)
        bad_file = export_dir / "bad.csv"
        bad_file.write_bytes(b"\xff\xfe" + b"\x00" * 100)
        _export_dirs[export_id] = {
            "path": export_dir,
            "created": time.time(),
            "db_id": "test",
        }
        try:
            result = read_crawl_data(export_id, "bad.csv")
            # Should not just say "Failed to read bad.csv"
            # Should include exception info
            if "ERROR" in result:
                assert "bad.csv" in result
        finally:
            _export_dirs.pop(export_id, None)

    def test_error_does_not_leak_absolute_paths(self, tmp_path):
        """Error messages should use the safe filename, not absolute paths."""
        export_id = "test-no-leak"
        export_dir = tmp_path / export_id
        export_dir.mkdir()
        _export_dirs[export_id] = {
            "path": export_dir,
            "created": time.time(),
            "db_id": "test",
        }
        try:
            result = read_crawl_data(export_id, "nonexistent.csv")
            assert str(tmp_path) not in result or "not found" in result.lower()
        finally:
            _export_dirs.pop(export_id, None)
