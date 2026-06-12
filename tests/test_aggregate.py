# -*- coding: utf-8 -*-
"""
Tests for aggregate_crawl_data -- server-side group-by counts and totals
over export CSVs, so the model gets answers instead of row dumps.

Run with: uv run python -m pytest tests/test_aggregate.py -v
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sf_mcp import _export_dirs, aggregate_crawl_data


@pytest.fixture
def csv_export(tmp_path):
    """Mock export with a CSV covering repeated values, an empty cell, and a filterable column."""
    export_id = "test-aggregate"
    export_dir = tmp_path / export_id
    export_dir.mkdir()
    csv_file = export_dir / "response_codes_all.csv"
    csv_file.write_text(
        "Address,Status Code,Content Type\n"
        "https://example.com/,200,text/html\n"
        "https://example.com/a,200,text/html\n"
        "https://example.com/b,200,text/html\n"
        "https://example.com/c,301,text/html\n"
        "https://example.com/d,301,\n"
        "https://example.com/e,404,text/html\n"
    )
    _export_dirs[export_id] = {
        "path": export_dir,
        "created": time.time(),
        "db_id": "test",
    }
    yield export_id
    _export_dirs.pop(export_id, None)


class TestGroupBy:
    def test_counts_per_value_sorted_desc(self, csv_export):
        result = aggregate_crawl_data(csv_export, "response_codes_all.csv", group_by="Status Code")
        # Most common first
        assert result.index("200") < result.index("301") < result.index("404")
        assert "200: 3" in result
        assert "301: 2" in result
        assert "404: 1" in result

    def test_includes_percentages_and_total(self, csv_export):
        result = aggregate_crawl_data(csv_export, "response_codes_all.csv", group_by="Status Code")
        assert "50.0%" in result  # 3 of 6
        assert "6" in result  # total row count

    def test_empty_cells_grouped_as_empty_label(self, csv_export):
        result = aggregate_crawl_data(csv_export, "response_codes_all.csv", group_by="Content Type")
        assert "(empty)" in result
        assert "text/html: 5" in result

    def test_top_limits_distinct_values(self, csv_export):
        result = aggregate_crawl_data(csv_export, "response_codes_all.csv", group_by="Status Code", top=1)
        assert "200: 3" in result
        assert "301" not in result.split("200: 3", 1)[1] or "more value" in result
        assert "2 more value" in result  # 301 and 404 hidden

    def test_filter_applies_before_grouping(self, csv_export):
        result = aggregate_crawl_data(
            csv_export, "response_codes_all.csv", group_by="Status Code",
            filter_column="Status Code", filter_value=r"^(?!200)\d+", filter_mode="regex",
        )
        assert "301: 2" in result
        assert "404: 1" in result
        assert "200:" not in result


class TestTotalOnly:
    def test_no_group_by_returns_total(self, csv_export):
        result = aggregate_crawl_data(csv_export, "response_codes_all.csv")
        assert "6" in result
        assert "row" in result.lower()

    def test_no_group_by_with_filter_counts_matches(self, csv_export):
        result = aggregate_crawl_data(
            csv_export, "response_codes_all.csv",
            filter_column="Status Code", filter_value="301", filter_mode="exact",
        )
        assert "2" in result
        # The unfiltered total (6) should not be presented as the answer
        assert "6 row" not in result


class TestErrors:
    def test_unknown_export_id(self):
        result = aggregate_crawl_data("nope", "x.csv", group_by="A")
        assert "Unknown export_id" in result

    def test_unknown_group_by_column_lists_available(self, csv_export):
        result = aggregate_crawl_data(csv_export, "response_codes_all.csv", group_by="Nope")
        assert "not found" in result
        assert "Status Code" in result

    def test_missing_file_lists_available(self, csv_export):
        result = aggregate_crawl_data(csv_export, "missing.csv", group_by="Status Code")
        assert "not found" in result
        assert "response_codes_all.csv" in result

    def test_invalid_regex_is_reported(self, csv_export):
        result = aggregate_crawl_data(
            csv_export, "response_codes_all.csv", group_by="Status Code",
            filter_column="Status Code", filter_value="[", filter_mode="regex",
        )
        assert "ERROR" in result
        assert "regex" in result.lower()
