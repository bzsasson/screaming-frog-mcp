# -*- coding: utf-8 -*-
"""
Tests for issue #16: regular expression denial of service (ReDoS) in the
filter_value parameter of read_crawl_data and aggregate_crawl_data.

A catastrophic-backtracking pattern like (a+)+$ against a cell of repeated
characters hangs a single .search() call for minutes. The filter must
bound pattern length, time out individual matches, and cap the wall-clock
cost of the whole filtering loop, returning clear errors instead of
hanging.

Run with: uv run python -m pytest tests/test_redos.py -v
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import screaming_frog_mcp.server as server
from screaming_frog_mcp.server import (
    _export_dirs,
    aggregate_crawl_data,
    read_crawl_data,
)

# The regex package's engine neutralizes the classic (a+)+$ internally,
# so the adversarial case here is one its optimizer cannot save; it was
# measured to exceed the match timeout on this subject.
EVIL_PATTERN = r"(a|aa)+$"
EVIL_CELL = "a" * 64 + "!"


@pytest.fixture
def adversarial_export(tmp_path):
    """Export whose CSV contains a cell crafted to explode EVIL_PATTERN."""
    export_id = "test-redos"
    export_dir = tmp_path / export_id
    export_dir.mkdir()
    (export_dir / "data.csv").write_text(
        "Address,Title\n"
        f"https://example.com/,{EVIL_CELL}\n"
        "https://example.com/a,normal title\n"
    )
    _export_dirs[export_id] = {
        "path": export_dir, "created": time.time(), "db_id": "test",
    }
    yield export_id
    _export_dirs.pop(export_id, None)


@pytest.fixture
def large_export(tmp_path):
    """Export with enough rows to trip the loop budget checkpoint."""
    export_id = "test-budget"
    export_dir = tmp_path / export_id
    export_dir.mkdir()
    rows = "\n".join(f"https://example.com/{i},t{i}" for i in range(3000))
    (export_dir / "big.csv").write_text("Address,Title\n" + rows + "\n")
    _export_dirs[export_id] = {
        "path": export_dir, "created": time.time(), "db_id": "test",
    }
    yield export_id
    _export_dirs.pop(export_id, None)


class TestMatchTimeout:
    def test_read_returns_error_not_hang(self, adversarial_export):
        t0 = time.time()
        result = read_crawl_data(
            adversarial_export, "data.csv",
            filter_column="Title", filter_value=EVIL_PATTERN, filter_mode="regex",
        )
        assert time.time() - t0 < 10, "filtering must not hang"
        assert "ERROR" in result
        assert "timed out" in result.lower()

    def test_aggregate_returns_error_not_hang(self, adversarial_export):
        t0 = time.time()
        result = aggregate_crawl_data(
            adversarial_export, "data.csv", group_by="Address",
            filter_column="Title", filter_value=EVIL_PATTERN, filter_mode="regex",
        )
        assert time.time() - t0 < 10, "aggregation must not hang"
        assert "ERROR" in result
        assert "timed out" in result.lower()

    def test_error_suggests_simplifying_pattern(self, adversarial_export):
        result = read_crawl_data(
            adversarial_export, "data.csv",
            filter_column="Title", filter_value=EVIL_PATTERN, filter_mode="regex",
        )
        assert "simpl" in result.lower() or "pattern" in result.lower()


class TestPatternLengthCap:
    def test_overlong_filter_value_rejected(self, adversarial_export):
        result = read_crawl_data(
            adversarial_export, "data.csv",
            filter_column="Title",
            filter_value="a" * (server.MAX_FILTER_VALUE_LENGTH + 1),
            filter_mode="contains",
        )
        assert "ERROR" in result
        assert str(server.MAX_FILTER_VALUE_LENGTH) in result

    def test_cap_applies_to_regex_mode(self, adversarial_export):
        result = read_crawl_data(
            adversarial_export, "data.csv",
            filter_column="Title",
            filter_value="(a)" * server.MAX_FILTER_VALUE_LENGTH,
            filter_mode="regex",
        )
        assert "ERROR" in result

    def test_value_at_cap_accepted(self, adversarial_export):
        result = read_crawl_data(
            adversarial_export, "data.csv",
            filter_column="Title",
            filter_value="x" * server.MAX_FILTER_VALUE_LENGTH,
            filter_mode="contains",
        )
        assert "ERROR" not in result  # no matches is fine, an error is not


class TestLoopBudget:
    def test_budget_exceeded_returns_error(self, large_export, monkeypatch):
        monkeypatch.setattr(server, "FILTER_TIME_BUDGET_SECONDS", 0.0)
        result = read_crawl_data(
            large_export, "big.csv",
            filter_column="Title", filter_value="zzz", filter_mode="contains",
        )
        assert "ERROR" in result
        assert "budget" in result.lower() or "too long" in result.lower()

    def test_normal_budget_unaffected(self, large_export):
        result = read_crawl_data(
            large_export, "big.csv",
            filter_column="Title", filter_value="t42", filter_mode="exact",
        )
        assert "ERROR" not in result
        assert "t42" in result


class TestRegexSemanticsPreserved:
    def test_documented_lookahead_pattern_still_works(self, adversarial_export):
        # The README documents ^(?!200)\d+ for non-200 filtering; the
        # timeout-capable engine must keep supporting it.
        result = read_crawl_data(
            adversarial_export, "data.csv",
            filter_column="Address", filter_value=r"^(?!x)https", filter_mode="regex",
        )
        assert "example.com" in result

    def test_invalid_regex_still_reported(self, adversarial_export):
        result = read_crawl_data(
            adversarial_export, "data.csv",
            filter_column="Title", filter_value="[", filter_mode="regex",
        )
        assert "ERROR" in result
        assert "regex" in result.lower()
