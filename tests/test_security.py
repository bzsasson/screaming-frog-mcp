# -*- coding: utf-8 -*-
"""
Security tests for screaming-frog-mcp validators.

Run with: uv run python -m pytest tests/test_security.py -v
"""

import sys
from pathlib import Path

import pytest

# Add the project root so we can import sf_mcp directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sf_mcp import (
    _validate_url,
    _validate_db_id,
    _validate_cli_arg,
    _path_is_contained,
    EXPORT_REFERENCE,
)


# ---------------------------------------------------------------------------
# _validate_url
# ---------------------------------------------------------------------------

class TestValidateUrl:
    """Tests for SSRF protection in _validate_url."""

    # --- Should PASS (return None) ---

    @pytest.mark.parametrize("url", [
        "https://example.com",
        "https://technicalseonews.com/",
        "https://www.freshgovjobs.com/",
        "http://example.com/path?q=1",
        "https://www.google.com/search?q=test",
        "https://example.com:8080/path",
    ])
    def test_valid_urls_pass(self, url):
        assert _validate_url(url) is None

    # --- Should FAIL (return error string) ---

    @pytest.mark.parametrize("url,reason", [
        ("ftp://example.com", "non-http scheme"),
        ("file:///etc/passwd", "file scheme"),
        ("javascript:alert(1)", "javascript scheme"),
        ("", "empty string"),
        ("not-a-url", "no scheme"),
        ("https://", "no hostname"),
    ])
    def test_invalid_scheme_or_format(self, url, reason):
        result = _validate_url(url)
        assert result is not None, f"Should reject {reason}: {url}"

    @pytest.mark.parametrize("url,reason", [
        ("http://127.0.0.1/", "loopback IPv4"),
        ("http://10.0.0.1/", "private IPv4 class A"),
        ("http://192.168.1.1/", "private IPv4 class C"),
        ("http://172.16.0.1/", "private IPv4 class B"),
        ("http://169.254.169.254/", "link-local / cloud metadata"),
        ("http://localhost/", "localhost hostname"),
        ("http://metadata.google.internal/", "GCP metadata"),
        ("http://metadata.internal/", "generic metadata"),
        ("http://[::1]/", "IPv6 loopback bracket notation"),
    ])
    def test_ssrf_blocked(self, url, reason):
        result = _validate_url(url)
        assert result is not None, f"Should block SSRF via {reason}: {url}"

    def test_dns_resolution_blocks_localhost(self):
        """DNS resolution catches localhost even as a domain name."""
        result = _validate_url("http://localhost/")
        assert result is not None


# ---------------------------------------------------------------------------
# _validate_db_id
# ---------------------------------------------------------------------------

class TestValidateDbId:
    """Tests for database ID validation -- enforces UUID format."""

    # --- Should PASS: real SF database IDs are UUIDs ---

    @pytest.mark.parametrize("db_id", [
        "5f0deda5-75ef-4b49-935a-2b2c8d013e66",
        "d63a2a41-2d8a-4da0-b1fe-b1ffe6d4a9aa",
        "3bf21f8c-e5a1-497b-9973-0613d919bcfc",
        "87e7791e-3e0a-4159-aa4a-06aefa75853b",
        "1ba320f8-5109-468a-b35b-33e3fb66694b",
        "f05b87ae-ea07-4283-8c81-48266c352fbf",
        "48cc0aaf-91e4-4622-9d0f-f4603a54e9e2",
        "89799e51-50b4-4c6b-9271-b5bd8dd28a52",
    ])
    def test_real_uuid_db_ids_pass(self, db_id):
        """Real database IDs from a live SF install must pass."""
        assert _validate_db_id(db_id) is None

    # --- Should FAIL ---

    @pytest.mark.parametrize("db_id,reason", [
        ("--delete-all", "flag injection"),
        ("-rf", "short flag"),
        ("", "empty string"),
        ("foo/bar", "path separator /"),
        ("foo\\bar", "path separator backslash"),
        ("foo bar", "contains space"),
        ("foo;ls", "shell metachar semicolon"),
        ("foo|cat", "shell metachar pipe"),
        ("foo\x00bar", "null byte"),
        ("foo\nbar", "newline"),
        ("..", "double dot traversal"),
        (".", "single dot"),
        ("a" * 10000, "excessively long input"),
        ("not-a-uuid-at-all", "non-UUID format"),
        ("5f0deda5-75ef-4b49-935a-2b2c8d013e6", "truncated UUID"),
        ("5f0deda5-75ef-4b49-935a-2b2c8d013e666", "UUID with extra char"),
        ("5F0DEDA5-75EF-4B49-935A-2B2C8D013E66", "uppercase UUID"),
    ])
    def test_malicious_or_invalid_db_ids_rejected(self, db_id, reason):
        result = _validate_db_id(db_id)
        assert result is not None, f"Should reject {reason}: {repr(db_id)}"


# ---------------------------------------------------------------------------
# _validate_cli_arg
# ---------------------------------------------------------------------------

class TestValidateCliArg:
    """Tests for CLI argument value validation."""

    # --- Should PASS: known-good SF export values ---

    @pytest.mark.parametrize("value", [
        "Internal:All",
        "Internal:All,Response Codes:All,Page Titles:All",
        "Internal:All,Response Codes:All,Page Titles:All,Meta Description:All,H1:All,H2:All,Images:All,Canonicals:All,Directives:All",
        "All Inlinks",
        "All Inlinks,All Outlinks",
        "All Anchor Text",
        "Response Times",
        "Crawl Overview",
        "Redirect Chains",
        "Redirect & Canonical Chains",
        "Internal:Over 115 Characters",
        "Images:Over 100 KB",
        "Meta Description:Over 155 Characters",
        "Paginated 2+",
        "Content:Missing <head> Tag",
        "Content:Missing <body> Tag",
        "Internal:All,Response Codes:All,Page Titles:All,Meta Description:All,H1:All,H2:All,Images:All,Canonicals:All,Directives:All,Hreflang:All,JavaScript:All,Structured Data:All,Sitemaps:All,Content:All,Security:All",
    ])
    def test_valid_export_values_pass(self, value):
        """Known-good SF export tab/bulk export/report values must pass."""
        assert _validate_cli_arg(value, "export_tabs") is None

    # --- Should FAIL ---

    @pytest.mark.parametrize("value,reason", [
        ("--output-folder /tmp", "flag injection"),
        ("-rf", "short flag"),
        ("  --flag", "leading whitespace before flag"),
        ("\t--flag", "tab before flag"),
        ("Internal:All\x00--output-folder\x00/tmp", "null byte injection"),
        ("Internal:All\n--output-folder /tmp", "newline injection"),
        ("", "empty string"),
        ("a" * 2001, "exceeds length limit"),
        ("Internal:All;rm -rf /", "shell metachar semicolon"),
        ("Internal:All|cat /etc/passwd", "shell metachar pipe"),
        ("Internal:All`whoami`", "backtick injection"),
        ("Internal:All$(id)", "command substitution"),
    ])
    def test_injection_rejected(self, value, reason):
        result = _validate_cli_arg(value, "test_param")
        assert result is not None, f"Should reject {reason}: {repr(value)}"


# ---------------------------------------------------------------------------
# _path_is_contained
# ---------------------------------------------------------------------------

class TestPathIsContained:
    """Tests for path traversal protection."""

    def test_child_is_contained(self, tmp_path):
        child = tmp_path / "subdir" / "file.csv"
        child.parent.mkdir(parents=True, exist_ok=True)
        child.touch()
        assert _path_is_contained(child, tmp_path) is True

    def test_same_dir_is_contained(self, tmp_path):
        file = tmp_path / "file.csv"
        file.touch()
        assert _path_is_contained(file, tmp_path) is True

    def test_parent_traversal_rejected(self, tmp_path):
        outside = tmp_path / ".." / "outside.csv"
        assert _path_is_contained(outside, tmp_path) is False

    def test_absolute_outside_rejected(self, tmp_path):
        assert _path_is_contained(Path("/etc/passwd"), tmp_path) is False

    def test_symlink_followed_by_resolve(self, tmp_path):
        """Symlinks are resolved -- a symlink pointing outside is rejected."""
        target = Path("/tmp/symlink_target_test_sf_mcp")
        target.touch(exist_ok=True)
        try:
            link = tmp_path / "sneaky.csv"
            link.symlink_to(target)
            assert _path_is_contained(link, tmp_path) is False
        finally:
            target.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Export reference completeness
# ---------------------------------------------------------------------------

class TestExportReference:
    """Verify the EXPORT_REFERENCE constant contains expected values."""

    @pytest.mark.parametrize("tab", [
        "Internal", "External", "Response Codes", "Page Titles",
        "Meta Description", "H1", "H2", "Images", "Canonicals",
        "Directives", "Structured Data", "Sitemaps",
    ])
    def test_export_tabs_documented(self, tab):
        assert tab in EXPORT_REFERENCE

    @pytest.mark.parametrize("export", [
        "All Inlinks", "All Outlinks", "All Anchor Text",
        "Crawl Overview", "Redirect Chains",
    ])
    def test_bulk_exports_documented(self, export):
        assert export in EXPORT_REFERENCE
