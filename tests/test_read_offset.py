# -*- coding: utf-8 -*-
"""
Tests for read_crawl_data offset behavior -- improved messaging when
offset exceeds total rows.

Run with: uv run python -m pytest tests/test_read_offset.py -v
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sf_mcp import _export_dirs, read_crawl_data


class TestOffsetBeyondData:
    """Tests for offset exceeding available rows."""

    @pytest.fixture
    def csv_export(self, tmp_path):
        """Create a mock export with a small CSV file."""
        export_id = "test-offset"
        export_dir = tmp_path / export_id
        export_dir.mkdir()
        csv_file = export_dir / "test.csv"
        csv_file.write_text(
            "URL,Status Code\n"
            "https://example.com/,200\n"
            "https://example.com/about,200\n"
            "https://example.com/contact,301\n"
        )
        _export_dirs[export_id] = {
            "path": export_dir,
            "created": time.time(),
            "db_id": "test",
        }
        yield export_id
        _export_dirs.pop(export_id, None)

    def test_offset_past_end_shows_total(self, csv_export):
        """When offset exceeds rows, message should include total count."""
        result = read_crawl_data(csv_export, "test.csv", offset=100)
        assert "offset" in result.lower()
        assert "3" in result  # 3 data rows

    def test_offset_past_end_with_filter(self, csv_export):
        """When offset exceeds filtered rows, message should include count."""
        result = read_crawl_data(
            csv_export, "test.csv",
            filter_column="Status Code", filter_value="200", filter_mode="exact",
            offset=100,
        )
        assert "offset" in result.lower()
        assert "2" in result  # 2 rows match status=200

    def test_zero_offset_normal(self, csv_export):
        """Offset 0 should return data normally."""
        result = read_crawl_data(csv_export, "test.csv", offset=0)
        assert "example.com" in result

    def test_offset_exact_boundary(self, csv_export):
        """Offset equal to row count should show offset message, not generic 'no matching'."""
        result = read_crawl_data(csv_export, "test.csv", offset=3)
        assert "offset" in result.lower()
        assert "3" in result

    def test_no_match_without_offset(self, csv_export):
        """Genuine no-match (filter, no offset) should say 'No matching rows'."""
        result = read_crawl_data(
            csv_export, "test.csv",
            filter_column="Status Code", filter_value="999", filter_mode="exact",
        )
        assert "No matching rows" in result
