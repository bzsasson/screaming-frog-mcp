# -*- coding: utf-8 -*-
"""
Tests for export_crawl row count logic -- summary reports vs tabular CSVs.

Run with: uv run python -m pytest tests/test_row_count.py -v
"""

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from screaming_frog_mcp.server import _is_sf_summary_report


class TestRowCountLogic:
    """Tests for the row counting logic that distinguishes summary reports
    from tabular CSVs when computing total_data_rows in export_crawl."""

    @staticmethod
    def _count_data_rows(file_path: Path) -> int:
        """Replicate the row counting logic from export_crawl (server.py:684-701)."""
        with open(file_path, "r", newline="", encoding="utf-8-sig") as fh:
            first_line = fh.readline()
            fh.seek(0)
            reader = csv.reader(fh)
            rows = sum(1 for _ in reader)
            if _is_sf_summary_report(first_line):
                return rows  # no header to subtract
            else:
                return max(0, rows - 1)  # subtract header

    def test_tabular_csv_subtracts_header(self, tmp_path):
        """Tabular CSVs should subtract 1 for the header row."""
        csv_file = tmp_path / "internal_all.csv"
        csv_file.write_text(
            "URL,Status Code,Word Count\n"
            "https://example.com/,200,1500\n"
            "https://example.com/about,200,800\n"
            "https://example.com/contact,200,400\n"
        )
        assert self._count_data_rows(csv_file) == 3

    def test_summary_report_counts_all_rows(self, tmp_path):
        """Summary reports should count all rows (no header to subtract)."""
        csv_file = tmp_path / "crawl_overview.csv"
        csv_file.write_text(
            '"Site Crawled","https://example.com/"\n'
            '"Start Date","2026-05-01"\n'
            '"Start Time","10:30:00"\n'
            '""'  '\n'
            '"Internal"\n'
            '"All","60","100.00%","60","Internal URLs"\n'
            '"HTML","40","66.67%","60","Internal URLs"\n'
        )
        assert self._count_data_rows(csv_file) == 7

    def test_empty_tabular_csv_zero_rows(self, tmp_path):
        """A tabular CSV with only a header has 0 data rows."""
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("URL,Status Code,Word Count\n")
        assert self._count_data_rows(csv_file) == 0

    def test_single_data_row_tabular(self, tmp_path):
        """A tabular CSV with header + 1 data row = 1 data row."""
        csv_file = tmp_path / "single.csv"
        csv_file.write_text(
            "URL,Status Code\n"
            "https://example.com/,200\n"
        )
        assert self._count_data_rows(csv_file) == 1

    def test_summary_report_with_bom(self, tmp_path):
        """Summary report with BOM should still be detected correctly."""
        csv_file = tmp_path / "crawl_overview.csv"
        content = (
            '"Site Crawled","https://example.com/"\n'
            '"Start Date","2026-05-01"\n'
        )
        # utf-8-sig adds BOM on write and strips it on read
        csv_file.write_text(content, encoding="utf-8-sig")
        assert self._count_data_rows(csv_file) == 2

    def test_mixed_export_row_count(self, tmp_path):
        """Simulate an export with both tabular and summary CSVs."""
        # Tabular: 3 data rows
        tabular = tmp_path / "internal_all.csv"
        tabular.write_text(
            "URL,Status Code\n"
            "https://example.com/,200\n"
            "https://example.com/a,200\n"
            "https://example.com/b,301\n"
        )
        # Summary: 5 rows (all count)
        summary = tmp_path / "crawl_overview.csv"
        summary.write_text(
            '"Site Crawled","https://example.com/"\n'
            '"Start Date","2026-05-01"\n'
            '"Internal"\n'
            '"All","60","100.00%"\n'
            '"HTML","40","66.67%"\n'
        )

        total = self._count_data_rows(tabular) + self._count_data_rows(summary)
        assert total == 8  # 3 tabular + 5 summary
