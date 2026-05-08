# -*- coding: utf-8 -*-
"""
Tests for error message format across all tool exception handlers.

Verifies that every `except Exception as exc` handler in server.py
surfaces the exception type and message via `{type(exc).__name__}: {exc}`.

Run with: uv run python -m pytest tests/test_error_format.py -v
"""

import ast
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_PY = PROJECT_ROOT / "src" / "screaming_frog_mcp" / "server.py"


class TestErrorFormatConsistency:
    """AST-based tests verifying all generic exception handlers
    surface type(exc).__name__ and exc in the error message."""

    @staticmethod
    def _find_generic_exception_handlers():
        """Find all `except Exception as <name>:` handlers in server.py.

        Returns list of (line_number, exception_var_name, handler_body_nodes).
        """
        source = SERVER_PY.read_text()
        tree = ast.parse(source, filename=str(SERVER_PY))
        handlers = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                # Only generic Exception handlers with a bound name
                if (
                    node.type is not None
                    and isinstance(node.type, ast.Name)
                    and node.type.id == "Exception"
                    and node.name is not None
                ):
                    handlers.append((node.lineno, node.name, node.body))
        return handlers

    @staticmethod
    def _handler_has_type_and_message(body_nodes, exc_name):
        """Check if the handler body contains a string with both
        type(exc).__name__ and exc referenced (via f-string or format)."""
        source = SERVER_PY.read_text()
        for node in body_nodes:
            # Get the source lines for this handler body
            start = node.lineno
            end = node.end_lineno or start
            handler_source = "\n".join(
                source.splitlines()[start - 1 : end]
            )
            # Check for the pattern: type(exc).__name__ and {exc}
            has_type = f"type({exc_name}).__name__" in handler_source
            has_msg = f"{{{exc_name}}}" in handler_source
            if has_type and has_msg:
                return True
        return False

    def test_all_generic_handlers_surface_exception_info(self):
        """Every `except Exception as exc:` handler must include
        type(exc).__name__ and {exc} in its error message."""
        handlers = self._find_generic_exception_handlers()
        assert len(handlers) >= 5, (
            f"Expected at least 5 generic exception handlers, found {len(handlers)}"
        )

        failures = []
        for lineno, exc_name, body in handlers:
            if not self._handler_has_type_and_message(body, exc_name):
                failures.append(
                    f"  Line {lineno}: except Exception as {exc_name} -- "
                    f"missing type({exc_name}).__name__ or {{{exc_name}}} in error message"
                )

        assert not failures, (
            "Generic exception handlers missing exception type+message:\n"
            + "\n".join(failures)
        )

    def test_error_format_pattern(self):
        """Verify the consistent pattern: 'ERROR: <context>: {type(exc).__name__}: {exc}'"""
        source = SERVER_PY.read_text()
        # Find all f-string error returns with the exception pattern
        pattern = r'type\((\w+)\)\.__name__.*\{\1\}'
        matches = re.findall(pattern, source)
        # Should find at least one per tool (sf_check, crawl_site, list_crawls,
        # export_crawl, read_crawl_data, delete_crawl)
        assert len(matches) >= 5, (
            f"Expected at least 5 error format patterns, found {len(matches)}"
        )
