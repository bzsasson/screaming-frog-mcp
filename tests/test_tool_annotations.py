# -*- coding: utf-8 -*-
"""
Tests for MCP tool annotations -- the "locked-down by design" claim made
machine-readable. Clients surface readOnlyHint/destructiveHint in
permission prompts, so the read tools should declare themselves read-only
and delete_crawl should declare itself destructive.

Run with: uv run python -m pytest tests/test_tool_annotations.py -v
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from screaming_frog_mcp.server import mcp

READ_ONLY_TOOLS = {
    "sf_check",
    "list_crawls",
    "crawl_status",
    "read_crawl_data",
    "aggregate_crawl_data",
    "storage_summary",
}


def _tools_by_name():
    tools = asyncio.run(mcp.list_tools())
    return {t.name: t for t in tools}


class TestReadOnlyAnnotations:
    def test_read_tools_declare_read_only(self):
        tools = _tools_by_name()
        for name in READ_ONLY_TOOLS:
            assert name in tools, f"tool {name} missing"
            ann = tools[name].annotations
            assert ann is not None, f"{name} has no annotations"
            assert ann.readOnlyHint is True, f"{name} should be readOnlyHint=True"


class TestDestructiveAnnotations:
    def test_delete_crawl_is_destructive_not_read_only(self):
        tools = _tools_by_name()
        ann = tools["delete_crawl"].annotations
        assert ann is not None
        assert ann.destructiveHint is True
        assert ann.readOnlyHint is not True


class TestWriteToolsNotReadOnly:
    def test_crawl_site_is_open_world_not_read_only(self):
        tools = _tools_by_name()
        ann = tools["crawl_site"].annotations
        assert ann is not None
        assert ann.readOnlyHint is not True
        assert ann.openWorldHint is True  # it fetches the external web

    def test_export_crawl_not_read_only(self):
        # export writes files and loading a crawl with a newer SF migrates it,
        # so it must not advertise itself as read-only
        tools = _tools_by_name()
        ann = tools["export_crawl"].annotations
        assert ann is not None
        assert ann.readOnlyHint is not True
