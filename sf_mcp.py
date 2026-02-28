# -*- coding: utf-8 -*-
"""
Screaming Frog SEO Spider MCP Server

Provides tools to crawl sites, export data, and manage crawl storage
using Screaming Frog's CLI. All crawl data is stored in SF's internal
database (~/.ScreamingFrogSEOSpider/ProjectInstanceData/).
CSV exports are generated on-demand into temp dirs.
"""

import asyncio
import csv
import glob
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional, Union

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

# --- Configuration ---

SF_CLI_PATH = os.getenv(
    "SF_CLI_PATH",
    "/Applications/Screaming Frog SEO Spider.app/Contents/MacOS/ScreamingFrogSEOSpiderLauncher",
)

SF_DATA_DIR = Path.home() / ".ScreamingFrogSEOSpider" / "ProjectInstanceData"
TEMP_EXPORT_BASE = Path(tempfile.gettempdir()) / "sf-exports"
EXPORT_TTL_SECONDS = 3600  # 1 hour

DEFAULT_EXPORT_TABS = (
    "Internal:All,Response Codes:All,Page Titles:All,"
    "Meta Description:All,H1:All,H2:All,Images:All,"
    "Canonicals:All,Directives:All"
)

# --- State ---

# Track running crawl processes: crawl_id -> {pid, proc, url, label, started}
_running_crawls: dict = {}

# Track temp export dirs: export_id -> {path, created, db_id}
_export_dirs: dict = {}


def _sf_gui_is_running() -> bool:
    """Check if the Screaming Frog GUI (Java process) is already running.
    The headless CLI cannot access the crawl database while the GUI has it locked."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "ScreamingFrogSEOSpider.jar"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


SF_GUI_WARNING = (
    "ERROR: Screaming Frog GUI is already running. "
    "The headless CLI cannot access the crawl database while the GUI has it locked. "
    "Please quit the SF GUI first, then retry."
)

# --- Server ---

mcp = FastMCP("Screaming Frog SEO Spider")


def _cleanup_old_exports():
    """Remove temp export dirs older than EXPORT_TTL_SECONDS."""
    now = time.time()
    expired = [
        eid for eid, info in _export_dirs.items()
        if now - info["created"] > EXPORT_TTL_SECONDS
    ]
    for eid in expired:
        path = _export_dirs[eid]["path"]
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
        del _export_dirs[eid]

    # Also clean orphaned dirs on disk
    if TEMP_EXPORT_BASE.exists():
        for d in TEMP_EXPORT_BASE.iterdir():
            if d.is_dir():
                age = now - d.stat().st_mtime
                if age > EXPORT_TTL_SECONDS:
                    shutil.rmtree(d, ignore_errors=True)


# Clean up on startup
_cleanup_old_exports()


# --- Tools ---


@mcp.tool()
def sf_check() -> str:
    """
    Verify that Screaming Frog SEO Spider is installed and the CLI is accessible.
    Returns version info and license status.
    """
    if not os.path.exists(SF_CLI_PATH):
        return f"ERROR: Screaming Frog CLI not found at {SF_CLI_PATH}"

    try:
        result = subprocess.run(
            [SF_CLI_PATH, "--headless", "--help"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout + result.stderr

        # Extract version and license info from the startup logs
        version = "unknown"
        license_status = "unknown"
        for line in output.splitlines():
            if "Running: Screaming Frog SEO Spider" in line:
                version = line.split("Running: ")[-1].strip()
            if "Licence Status:" in line:
                license_status = line.split("Licence Status: ")[-1].strip()

        return (
            f"Screaming Frog is installed and accessible.\n"
            f"Version: {version}\n"
            f"License: {license_status}\n"
            f"CLI path: {SF_CLI_PATH}\n"
            f"Data dir: {SF_DATA_DIR}"
        )
    except subprocess.TimeoutExpired:
        return "Screaming Frog CLI found but timed out during check."
    except Exception as e:
        return f"ERROR checking Screaming Frog: {e}"


@mcp.tool()
async def crawl_site(
    url: str,
    config_file: Optional[str] = None,
    label: Optional[str] = None,
    max_urls: Optional[int] = None,
) -> str:
    """
    Start a background Screaming Frog crawl that saves to SF's internal database.

    Args:
        url: The URL to crawl (e.g. https://example.com)
        config_file: Optional path to a .seospiderconfig file for crawl settings
        label: Optional label for identifying this crawl (e.g. 'freshgovjobs')
        max_urls: Optional max number of URLs to crawl (overrides config)

    Returns:
        A crawl_id to use with crawl_status to check progress.
        The crawl runs in the background - use crawl_status to poll.
    """
    if not os.path.exists(SF_CLI_PATH):
        return f"ERROR: Screaming Frog CLI not found at {SF_CLI_PATH}"

    if _sf_gui_is_running():
        return SF_GUI_WARNING

    crawl_id = f"crawl-{uuid.uuid4().hex[:8]}"

    cmd = [
        SF_CLI_PATH,
        "--headless",
        "--crawl", url,
        "--save-crawl",
    ]

    if config_file:
        cmd.extend(["--config", config_file])

    if max_urls:
        cmd.extend(["--max-crawl-size", str(max_urls)])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        _running_crawls[crawl_id] = {
            "pid": proc.pid,
            "proc": proc,
            "url": url,
            "label": label or url.replace("https://", "").replace("http://", "").split("/")[0],
            "started": time.time(),
            "cmd": " ".join(cmd),
        }

        return (
            f"Crawl started in background.\n"
            f"Crawl ID: {crawl_id}\n"
            f"PID: {proc.pid}\n"
            f"URL: {url}\n"
            f"Label: {_running_crawls[crawl_id]['label']}\n\n"
            f"Use crawl_status(crawl_id='{crawl_id}') to check progress."
        )
    except Exception as e:
        return f"ERROR starting crawl: {e}"


@mcp.tool()
async def crawl_status(crawl_id: str) -> str:
    """
    Check the status of a running or completed crawl.

    Args:
        crawl_id: The crawl_id returned by crawl_site
    """
    if crawl_id not in _running_crawls:
        active = ", ".join(_running_crawls.keys()) if _running_crawls else "none"
        return f"Unknown crawl_id: {crawl_id}\nActive crawls: {active}"

    info = _running_crawls[crawl_id]
    proc = info["proc"]
    elapsed = time.time() - info["started"]
    elapsed_str = f"{int(elapsed // 60)}m {int(elapsed % 60)}s"

    if proc.returncode is None:
        # Still running - check without blocking
        try:
            await asyncio.wait_for(proc.wait(), timeout=0.1)
        except asyncio.TimeoutError:
            pass

    if proc.returncode is None:
        return (
            f"Crawl {crawl_id} is still running.\n"
            f"URL: {info['url']}\n"
            f"Label: {info['label']}\n"
            f"PID: {info['pid']}\n"
            f"Elapsed: {elapsed_str}\n\n"
            f"Use crawl_status(crawl_id='{crawl_id}') to check again."
        )

    # Process completed
    stdout = ""
    stderr = ""
    if proc.stdout:
        raw = await proc.stdout.read()
        stdout = raw.decode("utf-8", errors="replace")
    if proc.stderr:
        raw = await proc.stderr.read()
        stderr = raw.decode("utf-8", errors="replace")

    # Extract useful info from logs
    urls_crawled = "unknown"
    for line in (stdout + stderr).splitlines():
        if "URLs crawled" in line.lower() or "crawl complete" in line.lower():
            urls_crawled = line.strip()

    status = "completed" if proc.returncode == 0 else f"failed (exit code {proc.returncode})"

    result = (
        f"Crawl {crawl_id} {status}.\n"
        f"URL: {info['url']}\n"
        f"Label: {info['label']}\n"
        f"Elapsed: {elapsed_str}\n"
        f"URLs crawled: {urls_crawled}\n"
    )

    if proc.returncode != 0:
        # Show last 20 lines of output for debugging
        all_output = (stdout + stderr).strip().splitlines()
        tail = "\n".join(all_output[-20:])
        result += f"\nLast output:\n{tail}"

    result += (
        f"\n\nThe crawl is saved in SF's internal database.\n"
        f"Use list_crawls() to see all saved crawls and get the DB ID.\n"
        f"Then use export_crawl(db_id='...') to export data as CSV."
    )

    return result


@mcp.tool()
def list_crawls() -> str:
    """
    List all crawls saved in Screaming Frog's internal database.
    Returns crawl names, Database IDs, and sizes.
    Use the Database ID with export_crawl or delete_crawl.
    """
    if not os.path.exists(SF_CLI_PATH):
        return f"ERROR: Screaming Frog CLI not found at {SF_CLI_PATH}"

    # Note: --list-crawls works fine even when the GUI is running (read-only).
    # No GUI check needed here.

    try:
        result = subprocess.run(
            [SF_CLI_PATH, "--headless", "--list-crawls"],
            capture_output=True,
            text=True,
            timeout=60,
        )

        output = result.stdout + result.stderr

        # Parse the crawl list from output
        # SF outputs crawl info in its log format
        crawl_lines = []
        for line in output.splitlines():
            # Filter out the verbose startup/info logs, keep crawl-relevant lines
            if any(skip in line for skip in [
                "INFO  -", "WARNING:", "com.sun.", "Lock File",
                "font", "proxy", "Signature", "License",
                "Running:", "Platform", "Java Info", "VM args",
                "Log File", "Fatal Log", "Logging Status",
                "Memory:", "Licence", "Locale:", "Time Zone",
                "Checking Licence", "antialias", "SfRoboto",
            ]):
                continue
            if line.strip():
                crawl_lines.append(line.strip())

        if not crawl_lines:
            # If we couldn't parse structured output, try to extract from INFO lines
            db_crawls = []
            for line in output.splitlines():
                if "Database Id" in line or "database" in line.lower():
                    db_crawls.append(line.strip())

            if db_crawls:
                return "Saved crawls in SF database:\n\n" + "\n".join(db_crawls)

            # Fallback: show the full filtered output
            return (
                "Screaming Frog --list-crawls output:\n\n"
                + output[-3000:]  # Last 3000 chars to avoid huge output
                + "\n\nNote: If no crawls are shown, the SF database may be empty."
            )

        return "Saved crawls in SF database:\n\n" + "\n".join(crawl_lines)

    except subprocess.TimeoutExpired:
        return "ERROR: Timed out listing crawls (60s limit)."
    except Exception as e:
        return f"ERROR listing crawls: {e}"


@mcp.tool()
async def export_crawl(
    db_id: str,
    export_tabs: Optional[str] = None,
    bulk_export: Optional[str] = None,
    save_report: Optional[str] = None,
) -> str:
    """
    Load a saved crawl from SF's database and export data as CSV files.

    Args:
        db_id: The Database ID from list_crawls (e.g. '1234' or a crawl identifier)
        export_tabs: Comma-separated export tabs (default: Internal:All,Response Codes:All,Page Titles:All,Meta Description:All,H1:All,H2:All,Images:All,Canonicals:All,Directives:All). See the export-reference resource for all options.
        bulk_export: Optional bulk export types (e.g. 'All Links:All Links,All Inlinks:All Inlinks')
        save_report: Optional reports to save (e.g. 'Crawl Overview')

    Returns:
        An export_id and list of generated CSV files. Use read_crawl_data to read them.
    """
    if not os.path.exists(SF_CLI_PATH):
        return f"ERROR: Screaming Frog CLI not found at {SF_CLI_PATH}"

    if _sf_gui_is_running():
        return SF_GUI_WARNING

    _cleanup_old_exports()

    export_id = f"export-{uuid.uuid4().hex[:8]}"
    export_dir = TEMP_EXPORT_BASE / export_id
    export_dir.mkdir(parents=True, exist_ok=True)

    tabs = export_tabs or DEFAULT_EXPORT_TABS

    cmd = [
        SF_CLI_PATH,
        "--headless",
        "--load-crawl", db_id,
        "--export-tabs", tabs,
        "--output-folder", str(export_dir),
        "--timestamped-output",
    ]

    if bulk_export:
        cmd.extend(["--bulk-export", bulk_export])

    if save_report:
        cmd.extend(["--save-report", save_report])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout_raw, stderr_raw = await asyncio.wait_for(
            proc.communicate(), timeout=300
        )
        stdout = stdout_raw.decode("utf-8", errors="replace")
        stderr = stderr_raw.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            all_output = (stdout + stderr).strip().splitlines()
            tail = "\n".join(all_output[-15:])
            return f"ERROR exporting crawl (exit code {proc.returncode}):\n{tail}"

        # List generated files
        csv_files = sorted(export_dir.rglob("*.csv"))
        file_list = []
        for f in csv_files:
            size = f.stat().st_size
            size_str = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / (1024 * 1024):.1f} MB"
            rel_path = f.relative_to(export_dir)
            file_list.append(f"  {rel_path} ({size_str})")

        _export_dirs[export_id] = {
            "path": export_dir,
            "created": time.time(),
            "db_id": db_id,
        }

        if not file_list:
            return (
                f"Export completed but no CSV files were generated.\n"
                f"Export ID: {export_id}\n"
                f"This may mean the crawl DB ID is invalid or the crawl has no data.\n"
                f"Check the DB ID with list_crawls()."
            )

        # Check if CSVs are empty (headers only, no data rows).
        # This is the telltale sign that the SF GUI has the database locked.
        total_data_rows = 0
        for f in csv_files:
            try:
                with open(f, "r", newline="", encoding="utf-8-sig") as fh:
                    reader = csv.reader(fh)
                    rows = sum(1 for _ in reader)
                    total_data_rows += max(0, rows - 1)  # subtract header
            except Exception:
                pass

        if total_data_rows == 0:
            gui_hint = ""
            if _sf_gui_is_running():
                gui_hint = (
                    " The Screaming Frog GUI is currently running — this is almost certainly "
                    "the cause. Quit the GUI and re-run the export."
                )
            return (
                f"WARNING: Export produced {len(csv_files)} CSV file(s) but ALL are empty "
                f"(headers only, 0 data rows). This typically means the SF GUI has the "
                f"crawl database locked.{gui_hint}\n\n"
                f"Export ID: {export_id}\n"
                f"DB ID: {db_id}"
            )

        return (
            f"Export completed. {len(csv_files)} CSV files generated "
            f"({total_data_rows} total data rows).\n"
            f"Export ID: {export_id}\n"
            f"DB ID: {db_id}\n\n"
            f"Files:\n" + "\n".join(file_list) + "\n\n"
            f"Use read_crawl_data(export_id='{export_id}', file='filename.csv') to read data.\n"
            f"Files auto-delete after 1 hour."
        )
    except asyncio.TimeoutError:
        return "ERROR: Export timed out (5 minute limit). The crawl may be very large."
    except Exception as e:
        return f"ERROR exporting crawl: {e}"


@mcp.tool()
def read_crawl_data(
    export_id: str,
    file: str,
    limit: int = 100,
    offset: int = 0,
    filter_column: Optional[str] = None,
    filter_value: Optional[Union[str, int, float]] = None,
) -> str:
    """
    Read CSV data from an export. Use after export_crawl.

    Args:
        export_id: The export_id from export_crawl
        file: CSV filename to read (from the file list in export_crawl output)
        limit: Max rows to return (default 100)
        offset: Number of rows to skip (for pagination)
        filter_column: Optional column name to filter by
        filter_value: Optional value to match in the filter column (case-insensitive substring)

    Returns:
        CSV data as formatted text with column headers.
    """
    # Coerce filter_value to string (MCP clients may send numbers as int/float)
    if filter_value is not None:
        filter_value = str(filter_value)

    if export_id not in _export_dirs:
        active = ", ".join(_export_dirs.keys()) if _export_dirs else "none"
        return f"Unknown export_id: {export_id}\nActive exports: {active}"

    export_dir = _export_dirs[export_id]["path"]
    if not export_dir.exists():
        del _export_dirs[export_id]
        return "Export directory has been cleaned up. Run export_crawl again."

    # Find the file - try exact match first, then search
    target = export_dir / file
    if not target.exists():
        # Search subdirectories
        matches = list(export_dir.rglob(file))
        if not matches:
            # Try partial match
            matches = list(export_dir.rglob(f"*{file}*"))
        if not matches:
            available = [str(f.relative_to(export_dir)) for f in export_dir.rglob("*.csv")]
            return f"File '{file}' not found.\nAvailable files:\n" + "\n".join(f"  {f}" for f in available)
        target = matches[0]

    try:
        with open(target, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = []
            skipped = 0
            for row in reader:
                # Apply filter
                if filter_column and filter_value:
                    cell = row.get(filter_column, "")
                    if filter_value.lower() not in cell.lower():
                        continue

                if skipped < offset:
                    skipped += 1
                    continue

                rows.append(row)
                if len(rows) >= limit:
                    break

            if not rows:
                return f"No matching rows in {file}."

            # Format as text table
            columns = list(rows[0].keys())

            # Build output
            output = f"File: {target.relative_to(export_dir)}\n"
            output += f"Showing rows {offset + 1}-{offset + len(rows)}"
            if filter_column:
                output += f" (filtered: {filter_column} contains '{filter_value}')"
            output += f"\n\n"

            # Header
            output += " | ".join(columns) + "\n"
            output += "-+-".join("-" * min(len(c), 30) for c in columns) + "\n"

            # Rows
            for row in rows:
                values = []
                for col in columns:
                    val = row.get(col, "")
                    if len(val) > 80:
                        val = val[:77] + "..."
                    values.append(val)
                output += " | ".join(values) + "\n"

            # Truncation note
            if len(rows) == limit:
                output += f"\n... showing first {limit} rows. Use offset={offset + limit} for next page."

            return output

    except Exception as e:
        return f"ERROR reading {file}: {e}"


@mcp.tool()
def delete_crawl(db_id: str) -> str:
    """
    Delete a crawl from Screaming Frog's internal database to free disk space.

    Args:
        db_id: The Database ID from list_crawls

    WARNING: This permanently deletes the crawl data. It cannot be undone.
    """
    if not os.path.exists(SF_CLI_PATH):
        return f"ERROR: Screaming Frog CLI not found at {SF_CLI_PATH}"

    if _sf_gui_is_running():
        return SF_GUI_WARNING

    try:
        result = subprocess.run(
            [SF_CLI_PATH, "--headless", "--delete-crawl", db_id],
            capture_output=True,
            text=True,
            timeout=60,
        )

        output = result.stdout + result.stderr

        if result.returncode == 0:
            return f"Crawl {db_id} deleted successfully."

        # Check for common errors
        all_lines = output.strip().splitlines()
        tail = "\n".join(all_lines[-10:])
        return f"Delete may have failed (exit code {result.returncode}):\n{tail}"

    except subprocess.TimeoutExpired:
        return "ERROR: Delete timed out (60s limit)."
    except Exception as e:
        return f"ERROR deleting crawl: {e}"


@mcp.tool()
def storage_summary() -> str:
    """
    Show disk usage of Screaming Frog's internal crawl storage.
    Returns total size and per-crawl breakdown of ProjectInstanceData.
    """
    if not SF_DATA_DIR.exists():
        return f"SF data directory not found: {SF_DATA_DIR}"

    total_size = 0
    entries = []

    for item in sorted(SF_DATA_DIR.iterdir()):
        if item.is_dir():
            dir_size = sum(f.stat().st_size for f in item.rglob("*") if f.is_file())
            total_size += dir_size
            size_str = _format_size(dir_size)
            entries.append(f"  {item.name}: {size_str}")
        elif item.is_file():
            total_size += item.stat().st_size

    # Also check temp exports
    temp_size = 0
    temp_count = 0
    if TEMP_EXPORT_BASE.exists():
        for d in TEMP_EXPORT_BASE.iterdir():
            if d.is_dir():
                temp_count += 1
                temp_size += sum(f.stat().st_size for f in d.rglob("*") if f.is_file())

    result = f"Screaming Frog Storage Summary\n{'=' * 40}\n\n"
    result += f"Internal DB location: {SF_DATA_DIR}\n"
    result += f"Total DB size: {_format_size(total_size)}\n\n"

    if entries:
        result += "Crawl databases:\n" + "\n".join(entries) + "\n"
    else:
        result += "No crawl databases found.\n"

    if temp_count > 0:
        result += f"\nTemp exports: {temp_count} dirs, {_format_size(temp_size)}"
        result += " (auto-cleaned after 1 hour)"

    return result


def _format_size(size_bytes: int) -> str:
    """Format bytes into human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


# --- Resource ---

EXPORT_REFERENCE = """
# Screaming Frog Export Reference

## --export-tabs (Tab:Filter)
Export data from the main crawl tabs. Format: "Tab:Filter" comma-separated.

### Tabs and Filters:
- Internal: All, HTML, JavaScript, CSS, Images, PDF, Flash, Other, Unknown
- External: All, HTML, JavaScript, CSS, Images, PDF, Flash, Other, Unknown
- Protocol: All, HTTP URLs, HTTPS URLs, HTTP Images, HTTPS Images
- Response Codes: All, Blocked by Robots.txt, Blocked by User, No Response, 1xx, 2xx, 3xx, 4xx, 5xx
- URL: All, Non ASCII Characters, Underscores, Uppercase, Parameters, Duplicate URLs, Over 115 Characters
- Page Titles: All, Missing, Duplicate, Over 60 Characters, Below 30 Characters, Over 560 Pixels, Below 200 Pixels, Same as H1, Multiple
- Meta Description: All, Missing, Duplicate, Over 155 Characters, Below 70 Characters, Over 990 Pixels, Below 400 Pixels, Multiple
- Meta Keywords: All, Missing, Duplicate
- H1: All, Missing, Duplicate, Over 70 Characters, Multiple
- H2: All, Missing, Duplicate, Over 70 Characters, Multiple
- Images: All, Over 100 KB, Missing Alt Text, Missing Alt Attribute, Alt Text Over 100 Characters
- Canonicals: All, Contains Canonical, Self Referencing, Canonicalised, Missing, Multiple
- Pagination: All, Contains Pagination, First Page, Paginated 2+, Paginated with rel=noindex
- Directives: All, Index, Noindex, Follow, Nofollow, None, NoArchive, NoSnippet, Max-Snippet, Max-Image-Preview, Max-Video-Preview, NoODP, NoYDir, NoTranslate, Unavailable After, Refresh
- Hreflang: All, Contains Hreflang, Non 200 Hreflang URLs, Unlinked Hreflang URLs, Missing Return Links, Inconsistent Language & Region, Non Canonical, Noindex
- JavaScript: All, Frameworks & Libraries, JavaScript Files, Missing, Async, Defer, Async & Defer
- Structured Data: All, Contains Structured Data, Missing, Validation Errors, Validation Warnings, Schema.org, JSON-LD, Microdata, RDFa
- Sitemaps: All, URLs in Sitemap, URLs Not in Sitemap, Orphan URLs
- AMP: All, AMP, Non AMP, Missing Non AMP
- Content: All, Near Duplicates, Exact Duplicates
- Security: All, HTTP URLs, Mixed Content, Form URL Insecure, Form on HTTP URL
- Spelling & Grammar: All, Spelling Errors, Grammar Errors

## --bulk-export (Type)
Export large datasets. Comma-separated.

- All Links:All Links
- All Inlinks:All Inlinks
- All Outlinks:All Outlinks
- All Anchor Text:All Anchor Text
- Response Times:Response Times
- Cookies:Cookies
- Content:Unique Content,Near Duplicates,Exact Duplicates
- Custom Search:Contains,Does Not Contain
- Canonicals:Canonicals
- Hreflang:Hreflang
- Images:All Image Inlinks,All Image Outlinks,Missing Alt Tags,Alt Text Over 100
- JavaScript:JavaScript Links,JavaScript Rendering
- Redirect Chains:All Redirect Chains
- HTTP Headers:HTTP Headers
- Sitemaps:All Sitemap URLs
- Structured Data:All Structured Data,Validation Errors,Validation Warnings
- Accessibility:Accessibility Issues
- Links:External Links

## --save-report (Report)
Save summary reports. Comma-separated.

- Crawl Overview
- Redirect Chains
- Redirect & Canonical Chains
- Insecure Content
- SERP Summary
- PageSpeed Summary
"""


@mcp.resource("screaming-frog://export-reference")
def get_export_reference() -> str:
    """Complete reference of all Screaming Frog export options."""
    return EXPORT_REFERENCE


if __name__ == "__main__":
    mcp.run()
