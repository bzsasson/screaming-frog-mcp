# -*- coding: utf-8 -*-
"""
Screaming Frog SEO Spider MCP Server -- standalone entry point.

This file delegates to the canonical implementation in
src/screaming_frog_mcp/server.py. All code changes should be
made there, not here.
"""

import sys
from pathlib import Path

# Allow running directly: python sf_mcp.py
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from screaming_frog_mcp.server import main  # noqa: E402

# Re-export validators, constants, and tools for tests that import from sf_mcp
from screaming_frog_mcp.server import (  # noqa: E402, F401
    _validate_url,
    _validate_db_id,
    _validate_cli_arg,
    _path_is_contained,
    _is_sf_summary_report,
    _read_sf_summary_report,
    _export_dirs,
    read_crawl_data,
    EXPORT_REFERENCE,
    MAX_READ_LIMIT,
    MAX_INPUT_LENGTH,
    ALLOWED_DOMAINS,
    CONFIG_DIR,
)

if __name__ == "__main__":
    main()
