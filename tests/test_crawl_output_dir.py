# -*- coding: utf-8 -*-
"""
Tests for issue #12: a fixed-name crawl.seospider blocked the next crawl.

In memory storage mode, SF's --save-crawl writes a file always named
crawl.seospider into the output directory (the process CWD when no
--output-folder is passed) and refuses to start if it already exists.
Fix: every crawl gets its own output directory, and crawl_status tells
memory-mode users where their file went instead of claiming the crawl
is in the database.

Run with: uv run python -m pytest tests/test_crawl_output_dir.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from screaming_frog_mcp.server import (
    _build_crawl_cmd,
    _cleanup_completed_crawls,
    _crawl_completion_guidance,
    _find_memory_mode_save,
    _running_crawls,
)


class TestBuildCrawlCmd:
    def test_output_folder_is_passed(self, tmp_path):
        out = tmp_path / "crawl-abc123"
        cmd = _build_crawl_cmd("https://example.com", out)
        assert "--output-folder" in cmd
        assert cmd[cmd.index("--output-folder") + 1] == str(out)

    def test_base_flags_present(self, tmp_path):
        cmd = _build_crawl_cmd("https://example.com", tmp_path)
        assert "--headless" in cmd
        assert "--save-crawl" in cmd
        assert cmd[cmd.index("--crawl") + 1] == "https://example.com"

    def test_distinct_dirs_for_distinct_crawls(self, tmp_path):
        cmd_a = _build_crawl_cmd("https://example.com", tmp_path / "crawl-a")
        cmd_b = _build_crawl_cmd("https://example.com", tmp_path / "crawl-b")
        dir_a = cmd_a[cmd_a.index("--output-folder") + 1]
        dir_b = cmd_b[cmd_b.index("--output-folder") + 1]
        assert dir_a != dir_b

    def test_config_appended_when_given(self, tmp_path):
        cfg = tmp_path / "limits.seospiderconfig"
        cmd = _build_crawl_cmd("https://example.com", tmp_path, config_path=cfg)
        assert cmd[cmd.index("--config") + 1] == str(cfg)

    def test_no_config_flag_without_config(self, tmp_path):
        cmd = _build_crawl_cmd("https://example.com", tmp_path)
        assert "--config" not in cmd


class TestFindMemoryModeSave:
    def test_finds_seospider_file(self, tmp_path):
        f = tmp_path / "crawl.seospider"
        f.write_bytes(b"x")
        assert _find_memory_mode_save(tmp_path) == f

    def test_finds_nested_seospider_file(self, tmp_path):
        sub = tmp_path / "2026.10.17.10.00.00"
        sub.mkdir()
        f = sub / "crawl.seospider"
        f.write_bytes(b"x")
        assert _find_memory_mode_save(tmp_path) == f

    def test_none_for_empty_dir(self, tmp_path):
        assert _find_memory_mode_save(tmp_path) is None

    def test_none_for_missing_dir(self, tmp_path):
        assert _find_memory_mode_save(tmp_path / "nope") is None


class TestCompletionGuidance:
    def test_memory_mode_names_file_and_storage_setting(self, tmp_path):
        f = tmp_path / "crawl.seospider"
        msg = _crawl_completion_guidance(
            save_failed=False, fatal_error=None, memory_save=f)
        assert str(f) in msg
        assert "memory storage mode" in msg.lower()
        assert "Storage Mode" in msg
        # Must not make the database-mode success claim
        assert "saved in sf's internal database" not in msg.lower()

    def test_database_mode_message_unchanged(self):
        msg = _crawl_completion_guidance(
            save_failed=False, fatal_error=None, memory_save=None)
        assert "internal database" in msg
        assert "list_crawls" in msg

    def test_save_failed_still_warns(self):
        msg = _crawl_completion_guidance(
            save_failed=True, fatal_error=None, memory_save=None)
        assert "WARNING" in msg

    def test_fatal_error_message(self):
        msg = _crawl_completion_guidance(
            save_failed=False, fatal_error="FATAL - boom", memory_save=None)
        assert "did not complete" in msg


class _FakeProc:
    returncode = 0


class TestCleanupOutputDirs:
    @pytest.fixture(autouse=True)
    def clean_registry(self):
        _running_crawls.clear()
        yield
        _running_crawls.clear()

    def test_empty_output_dir_removed(self, tmp_path):
        out = tmp_path / "crawl-x"
        out.mkdir()
        _running_crawls["crawl-x"] = {
            "proc": _FakeProc(), "output_dir": out, "log_dir": None,
        }
        _cleanup_completed_crawls()
        assert not out.exists()

    def test_output_dir_with_crawl_file_kept(self, tmp_path):
        out = tmp_path / "crawl-y"
        out.mkdir()
        (out / "crawl.seospider").write_bytes(b"x")
        _running_crawls["crawl-y"] = {
            "proc": _FakeProc(), "output_dir": out, "log_dir": None,
        }
        _cleanup_completed_crawls()
        assert (out / "crawl.seospider").exists()
