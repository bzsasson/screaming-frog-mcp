# -*- coding: utf-8 -*-
"""
Tests for crawl_status log parsing -- URL count extraction,
FATAL detection, and save failure detection.

Run with: uv run python -m pytest tests/test_crawl_status.py -v
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# We test the log parsing logic directly rather than mocking the full
# async crawl_status flow, since the parsing is the bug surface area.

# Simulate the log parsing logic from crawl_status (server.py)
def _parse_crawl_logs(log_output: str):
    """Replicate the log parsing from crawl_status."""
    urls_crawled = "unknown"
    save_failed = False
    db_shutdown_seen = False
    fatal_error = None
    for line in log_output.splitlines():
        if "crawled" in line.lower() and "urls" in line.lower():
            match = re.search(r"crawled\s+(\d+)\s+urls", line, re.IGNORECASE)
            urls_crawled = match.group(1) if match else line.strip()
        if "crawl save failed" in line.lower():
            save_failed = True
        if "shutdown database" in line.lower() and "projectinstancedata" in line.lower():
            db_shutdown_seen = True
        if "FATAL" in line and fatal_error is None:
            fatal_error = line.strip()
    # SF 23.2 false positive: warns "Crawl save failed {}" but data is saved
    if save_failed and db_shutdown_seen:
        save_failed = False
    return urls_crawled, save_failed, fatal_error


class TestUrlCountParsing:
    """Tests for extracting URLs crawled from SF log output."""

    def test_parses_real_sf_format(self):
        """SF logs 'crawled N urls', not 'N urls crawled'. Should extract just the number."""
        log = (
            "INFO  - Running: Screaming Frog SEO Spider 23.2\n"
            "INFO  - Completed the spider of https://example.com/ in 0 hrs 0 mins 11 secs (11578), null, crawled 4 urls\n"
        )
        urls_crawled, _, _ = _parse_crawl_logs(log)
        assert urls_crawled == "4"

    def test_parses_large_crawl(self):
        log = "INFO  - Completed the spider of https://big.example.com/ in 1 hrs 23 mins 45 secs, null, crawled 55796 urls\n"
        urls_crawled, _, _ = _parse_crawl_logs(log)
        assert urls_crawled == "55796"

    def test_unknown_when_no_crawl_line(self):
        log = "INFO  - Application Started\nINFO  - Application Exited\n"
        urls_crawled, _, _ = _parse_crawl_logs(log)
        assert urls_crawled == "unknown"


class TestFatalDetection:
    """Tests for detecting SF FATAL errors in crawl output."""

    def test_detects_unrecognized_option(self):
        log = (
            "INFO  - User Locale: en_IL\n"
            "INFO  - Applying antialising fix\n"
            "FATAL - Unrecognized option: --max-crawl-size\n"
        )
        _, _, fatal_error = _parse_crawl_logs(log)
        assert fatal_error is not None
        assert "Unrecognized option" in fatal_error

    def test_no_fatal_on_clean_crawl(self):
        log = (
            "INFO  - Application Started\n"
            "INFO  - Completed the spider of https://example.com/ crawled 4 urls\n"
            "INFO  - Application Exited\n"
        )
        _, _, fatal_error = _parse_crawl_logs(log)
        assert fatal_error is None

    def test_first_fatal_captured(self):
        """If multiple FATAL lines, capture the first one."""
        log = (
            "FATAL - First error\n"
            "FATAL - Second error\n"
        )
        _, _, fatal_error = _parse_crawl_logs(log)
        assert "First error" in fatal_error


class TestSaveFailureDetection:
    """Tests for detecting crawl save failures."""

    def test_detects_genuine_save_failure(self):
        """Save failed without a database shutdown = genuine failure."""
        log = (
            "INFO  - Completed the spider of https://example.com/ crawled 4 urls\n"
            "WARN  - Crawl save failed {}\n"
            "INFO  - Application Exited\n"
        )
        _, save_failed, _ = _parse_crawl_logs(log)
        assert save_failed is True

    def test_sf_232_false_positive_suppressed(self):
        """SF 23.2 logs 'Crawl save failed {}' even when save succeeds.
        If the database shutdown line is present, the save actually worked."""
        log = (
            "INFO  - Completed the spider of https://example.com/ crawled 4 urls\n"
            "INFO  - saveCrawl in state: SpiderCrawlIdleState\n"
            "WARN  - Crawl save failed {}\n"
            "INFO  - Shutdown database, location: /Users/test/.ScreamingFrogSEOSpider/ProjectInstanceData/abc-123/results_xyz/sql\n"
            "INFO  - Application Exited\n"
        )
        _, save_failed, _ = _parse_crawl_logs(log)
        assert save_failed is False

    def test_save_failed_without_projectinstancedata_is_genuine(self):
        """Shutdown database line without ProjectInstanceData path = still a failure."""
        log = (
            "INFO  - Completed the spider of https://example.com/ crawled 4 urls\n"
            "WARN  - Crawl save failed {}\n"
            "INFO  - Shutdown database, location: /tmp/some-other-path/sql\n"
            "INFO  - Application Exited\n"
        )
        _, save_failed, _ = _parse_crawl_logs(log)
        assert save_failed is True

    def test_no_false_positive_without_save_line(self):
        log = (
            "INFO  - About to run handler: SaveCrawlHandler\n"
            "INFO  - saveCrawl in state: SpiderCrawlIdleState\n"
            "INFO  - Application Exited\n"
        )
        _, save_failed, _ = _parse_crawl_logs(log)
        assert save_failed is False
