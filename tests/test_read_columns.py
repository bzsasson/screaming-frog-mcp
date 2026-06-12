# -*- coding: utf-8 -*-
"""
Tests for read_crawl_data column selection -- request a subset of columns
so wide exports (Internal:All has dozens) don't flood the context window.

Run with: uv run python -m pytest tests/test_read_columns.py -v
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sf_mcp import _export_dirs, read_crawl_data


@pytest.fixture
def csv_export(tmp_path):
    export_id = "test-columns"
    export_dir = tmp_path / export_id
    export_dir.mkdir()
    csv_file = export_dir / "internal_all.csv"
    csv_file.write_text(
        "Address,Status Code,Title 1,Word Count\n"
        "https://example.com/,200,Home,500\n"
        "https://example.com/a,404,Lost,10\n"
    )
    _export_dirs[export_id] = {
        "path": export_dir,
        "created": time.time(),
        "db_id": "test",
    }
    yield export_id
    _export_dirs.pop(export_id, None)


class TestColumnSelection:
    def test_returns_only_requested_columns(self, csv_export):
        result = read_crawl_data(csv_export, "internal_all.csv", columns="Address,Status Code")
        assert "Address" in result
        assert "Status Code" in result
        assert "Title 1" not in result
        assert "Word Count" not in result
        assert "Home" not in result  # Title cell excluded too

    def test_whitespace_around_names_tolerated(self, csv_export):
        result = read_crawl_data(csv_export, "internal_all.csv", columns=" Address , Status Code ")
        assert "Address" in result
        assert "Title 1" not in result

    def test_unknown_column_lists_available(self, csv_export):
        result = read_crawl_data(csv_export, "internal_all.csv", columns="Address,Nope")
        assert "not found" in result
        assert "Title 1" in result  # available columns listed

    def test_no_columns_param_returns_all(self, csv_export):
        result = read_crawl_data(csv_export, "internal_all.csv")
        assert "Title 1" in result
        assert "Word Count" in result

    def test_columns_combine_with_filter(self, csv_export):
        result = read_crawl_data(
            csv_export, "internal_all.csv", columns="Address",
            filter_column="Status Code", filter_value="404", filter_mode="exact",
        )
        assert "example.com/a" in result
        assert "example.com/," not in result
        assert "404" not in result.split("\n\n", 1)[1]  # filtered column not in output rows
