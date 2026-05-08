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
import ipaddress
import logging
import os
import re
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional, Union
from urllib.parse import urlparse

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

logger = logging.getLogger(__name__)

# --- Configuration ---

SF_CLI_PATH = os.getenv(
    "SF_CLI_PATH",
    "/Applications/Screaming Frog SEO Spider.app/Contents/MacOS/ScreamingFrogSEOSpiderLauncher",
)

SF_DATA_DIR = Path.home() / ".ScreamingFrogSEOSpider" / "ProjectInstanceData"
TEMP_EXPORT_BASE = Path.home() / ".cache" / "sf-mcp" / "exports"
EXPORT_TTL_SECONDS = int(os.getenv("SF_EXPORT_TTL_SECONDS", "3600"))  # default 1 hour
MAX_CONCURRENT_CRAWLS = 2
MAX_ACTIVE_EXPORTS = 10
MAX_READ_LIMIT = 1000
MAX_INPUT_LENGTH = 2000
MAX_CRAWL_DURATION = 7200  # 2 hours
EXPORT_TIMEOUT_SECONDS = int(os.getenv("SF_EXPORT_TIMEOUT_SECONDS", "300"))  # default 5 min

# Optional domain allowlist for crawl targets (env var, comma-separated)
_allowed_domains_raw = os.getenv("SF_ALLOWED_DOMAINS", "")
ALLOWED_DOMAINS = [d.strip().lower() for d in _allowed_domains_raw.split(",") if d.strip()]

# Allowed config directory for .seospiderconfig files
CONFIG_DIR = Path(os.getenv(
    "SF_CONFIG_DIR",
    str(Path.home() / ".config" / "sf-mcp" / "configs"),
))

DEFAULT_EXPORT_TABS = (
    "Internal:All,Response Codes:All,Page Titles:All,"
    "Meta Description:All,H1:All,H2:All,Images:All,"
    "Canonicals:All,Directives:All"
)

# Allowlisted CLI argument characters for export_tabs / bulk_export / save_report.
# Derived from EXPORT_REFERENCE: alphanumeric, spaces, commas, colons, ampersands,
# hyphens, dots, parens, plus signs, forward slashes, percent signs,
# angle brackets (SF uses <head>, <body> in filter names).
_CLI_ARG_PATTERN = re.compile(r'^[a-zA-Z0-9 ,:&\-\.\(\)\+/%<>]+$')

# --- State ---

# Track running crawl processes: crawl_id -> {pid, proc, url, label, started}
_running_crawls: dict = {}

# Track temp export dirs: export_id -> {path, created, db_id}
_export_dirs: dict = {}


def _validate_url(url: str) -> Optional[str]:
    """Returns error message if URL is invalid/dangerous, None if OK."""
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL format."
    if parsed.scheme not in ("http", "https"):
        return f"Only http/https URLs are allowed, got: {parsed.scheme or 'none'}"
    hostname = parsed.hostname or ""
    if not hostname:
        return "URL must include a hostname."

    # Strip IPv6 brackets for ip_address() parsing
    clean_host = hostname.strip("[]")

    # Block private/internal IPs (literal IP in URL)
    try:
        ip = ipaddress.ip_address(clean_host)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return f"Internal/private addresses are not allowed: {hostname}"
    except ValueError:
        pass  # it's a domain name, not an IP -- that's fine

    # Block known dangerous hostnames
    blocked = {
        "localhost",
        "metadata.google.internal",
        "metadata.internal",
        "169.254.169.254",
    }
    if clean_host.lower() in blocked:
        return f"Blocked hostname: {hostname}"

    # Domain allowlist (if configured via SF_ALLOWED_DOMAINS env var)
    if ALLOWED_DOMAINS:
        if clean_host.lower() not in ALLOWED_DOMAINS:
            return (
                f"Domain {hostname} not in allowed list. "
                f"Set SF_ALLOWED_DOMAINS to permit it."
            )

    # DNS resolution check: resolve the hostname and verify all IPs are public.
    # Mitigates DNS rebinding attacks where a domain resolves to a private IP.
    try:
        addrs = socket.getaddrinfo(clean_host, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in addrs:
            resolved_ip = ipaddress.ip_address(sockaddr[0])
            if resolved_ip.is_private or resolved_ip.is_loopback or resolved_ip.is_link_local:
                return f"Domain {hostname} resolves to internal address {sockaddr[0]}"
    except socket.gaierror:
        return f"Cannot resolve hostname: {hostname}"

    return None


def _validate_cli_arg(value: str, name: str) -> Optional[str]:
    """Validate CLI argument values against an allowlist of safe characters."""
    if not value or len(value) > MAX_INPUT_LENGTH:
        return f"ERROR: {name} is empty or exceeds {MAX_INPUT_LENGTH} chars"
    if value.strip().startswith("-"):
        return f"ERROR: {name} must not start with '-'"
    if not _CLI_ARG_PATTERN.match(value):
        return f"ERROR: {name} contains invalid characters"
    return None


def _validate_db_id(db_id: str) -> Optional[str]:
    """Validate db_id is a UUID (the format SF uses for crawl database IDs)."""
    if not db_id or len(db_id) > 100:
        return "ERROR: db_id is empty or too long"
    # SF uses UUID format: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    if not re.match(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$', db_id):
        return "ERROR: db_id must be a valid UUID (e.g. from list_crawls)"
    return None


def _path_is_contained(target: Path, parent: Path) -> bool:
    """Check that target is inside parent (no path traversal)."""
    try:
        target.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _sf_gui_is_running() -> bool:
    """Check if the Screaming Frog GUI (Java process) is already running.
    The headless CLI cannot access the crawl database while the GUI has it locked."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "ScreamingFrogSEOSpider.jar"],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            timeout=5,
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
        if path.exists() and not path.is_symlink():
            shutil.rmtree(path, ignore_errors=True)
        del _export_dirs[eid]

    # Also clean orphaned dirs on disk — skip symlinks
    if TEMP_EXPORT_BASE.exists():
        for d in TEMP_EXPORT_BASE.iterdir():
            if d.is_symlink():
                d.unlink()  # remove the symlink itself, never follow
            elif d.is_dir():
                age = now - d.stat().st_mtime
                if age > EXPORT_TTL_SECONDS:
                    shutil.rmtree(d, ignore_errors=True)


def _cleanup_completed_crawls():
    """Remove completed crawl entries from memory and clean up log files."""
    completed = [
        cid for cid, info in _running_crawls.items()
        if info["proc"].returncode is not None
    ]
    for cid in completed:
        info = _running_crawls[cid]
        _close_crawl_logs(info)
        log_dir = info.get("log_dir")
        if log_dir and log_dir.exists() and not log_dir.is_symlink():
            shutil.rmtree(log_dir, ignore_errors=True)
        del _running_crawls[cid]


# Lines to filter from SF CLI output (contain internal paths, JVM info, etc.)
_SF_LOG_FILTERS = [
    "INFO  -", "WARNING:", "com.sun.", "Lock File",
    "font", "proxy", "Signature", "License",
    "Running:", "Platform", "Java Info", "VM args",
    "Log File", "Fatal Log", "Logging Status",
    "Memory:", "Licence", "Locale:", "Time Zone",
    "Checking Licence", "antialias", "SfRoboto",
]


def _sanitize_sf_output(output: str) -> str:
    """Filter verbose SF CLI log lines that may leak internal paths or config."""
    lines = output.splitlines()
    return "\n".join(
        line for line in lines
        if not any(skip in line for skip in _SF_LOG_FILTERS)
    )


def _close_crawl_logs(info: dict) -> None:
    """Close log file handles for a crawl."""
    for key in ("stdout_log", "stderr_log"):
        fh = info.get(key)
        if fh and not fh.closed:
            fh.close()


def _read_crawl_logs(info: dict) -> str:
    """Read crawl log files and return combined output."""
    output = ""
    log_dir = info.get("log_dir")
    if not log_dir:
        return output
    for name in ("stdout.log", "stderr.log"):
        log_file = log_dir / name
        if log_file.exists():
            try:
                output += log_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                pass
    return output


# Ensure export base dir exists with restricted permissions
TEMP_EXPORT_BASE.mkdir(parents=True, exist_ok=True)
os.chmod(TEMP_EXPORT_BASE, 0o700)

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
        return "ERROR: Screaming Frog CLI not found. Check SF_CLI_PATH in .env."

    try:
        # Use --list-crawls (read-only, works even with GUI running) because
        # --help doesn't emit version or license info in its output.
        result = subprocess.run(
            [SF_CLI_PATH, "--headless", "--list-crawls"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
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
            f"License: {license_status}"
        )
    except subprocess.TimeoutExpired:
        return "Screaming Frog CLI found but timed out during check."
    except Exception as exc:
        return f"ERROR: Could not check Screaming Frog installation: {type(exc).__name__}: {exc}"


@mcp.tool()
async def crawl_site(
    url: str,
    config_file: Optional[str] = None,
    label: Optional[str] = None,
) -> str:
    """
    Start a background Screaming Frog crawl that saves to SF's internal database.

    Args:
        url: The URL to crawl (e.g. https://example.com)
        config_file: Optional path to a .seospiderconfig file for crawl settings.
            To limit the number of URLs crawled, set the limit in a config file
            (Configuration > Spider > Limits in the SF GUI) and pass it here.
        label: Optional label for identifying this crawl (e.g. 'freshgovjobs')

    Returns:
        A crawl_id to use with crawl_status to check progress.
        The crawl runs in the background - use crawl_status to poll.
    """
    if not os.path.exists(SF_CLI_PATH):
        return "ERROR: Screaming Frog CLI not found. Check SF_CLI_PATH in .env."

    # Validate URL (SSRF protection)
    url_err = _validate_url(url)
    if url_err:
        return f"ERROR: {url_err}"

    if _sf_gui_is_running():
        return SF_GUI_WARNING

    # Enforce concurrent crawl limit
    _cleanup_completed_crawls()
    active = sum(1 for info in _running_crawls.values()
                 if info["proc"].returncode is None)
    if active >= MAX_CONCURRENT_CRAWLS:
        return f"ERROR: Maximum {MAX_CONCURRENT_CRAWLS} concurrent crawls. Wait for running crawls to finish."

    crawl_id = f"crawl-{uuid.uuid4().hex[:8]}"

    cmd = [
        SF_CLI_PATH,
        "--headless",
        "--crawl", url,
        "--save-crawl",
    ]

    if config_file:
        config_path = Path(config_file).resolve()
        if config_path.suffix != ".seospiderconfig":
            return "ERROR: Config file must have .seospiderconfig extension."
        if config_path.is_symlink():
            return "ERROR: Config file must not be a symlink."
        if not _path_is_contained(config_path, CONFIG_DIR):
            return (
                f"ERROR: Config files must be in {CONFIG_DIR}. "
                f"Set SF_CONFIG_DIR to change the allowed directory."
            )
        if not config_path.exists():
            return "ERROR: Config file not found."
        cmd.extend(["--config", str(config_path)])

    try:
        # Write crawl output to temp log files instead of PIPE to avoid
        # pipe buffer deadlock on long-running crawls (macOS pipe buffer ~64KB).
        log_dir = TEMP_EXPORT_BASE / f"{crawl_id}-logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_log = open(log_dir / "stdout.log", "w")
        stderr_log = open(log_dir / "stderr.log", "w")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=stdout_log,
            stderr=stderr_log,
        )

        crawl_label = label or url.replace("https://", "").replace("http://", "").split("/")[0]

        # Wait briefly to catch immediate startup failures (bad flags, license
        # issues, etc.). SF FATAL errors happen in the first 1-2 seconds.
        try:
            await asyncio.wait_for(proc.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass  # still running -- that's the normal case

        if proc.returncode is not None:
            # Process already exited -- check for FATAL
            stdout_log.close()
            stderr_log.close()
            early_output = ""
            for name in ("stdout.log", "stderr.log"):
                log_file = log_dir / name
                if log_file.exists():
                    try:
                        early_output += log_file.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        pass
            fatal_line = None
            for line in early_output.splitlines():
                if "FATAL" in line:
                    fatal_line = line.strip()
                    break
            if fatal_line:
                return f"ERROR: Crawl failed to start.\n{fatal_line}"
            return (
                f"ERROR: Crawl exited immediately (exit code {proc.returncode}). "
                f"Check SF installation and license."
            )

        _running_crawls[crawl_id] = {
            "proc": proc,
            "url": url,
            "label": crawl_label,
            "started": time.time(),
            "log_dir": log_dir,
            "stdout_log": stdout_log,
            "stderr_log": stderr_log,
        }

        return (
            f"Crawl started in background.\n"
            f"Crawl ID: {crawl_id}\n"
            f"URL: {url}\n"
            f"Label: {crawl_label}\n\n"
            f"Use crawl_status(crawl_id='{crawl_id}') to check progress."
        )
    except Exception as exc:
        logger.exception("Failed to start crawl")
        return f"ERROR: Failed to start crawl: {type(exc).__name__}: {exc}"


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

    # Enforce max crawl duration
    if proc.returncode is None and elapsed > MAX_CRAWL_DURATION:
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            proc.kill()
        _close_crawl_logs(info)
        return (
            f"Crawl {crawl_id} terminated (exceeded {MAX_CRAWL_DURATION // 3600}h limit).\n"
            f"URL: {info['url']}\n"
            f"Elapsed: {elapsed_str}\n"
            f"The partial crawl may be saved. Use list_crawls() to check."
        )

    if proc.returncode is None:
        return (
            f"Crawl {crawl_id} is still running.\n"
            f"URL: {info['url']}\n"
            f"Label: {info['label']}\n"
            f"Elapsed: {elapsed_str}\n\n"
            f"Use crawl_status(crawl_id='{crawl_id}') to check again."
        )

    # Process completed -- read logs from files
    _close_crawl_logs(info)
    log_output = _read_crawl_logs(info)

    # Extract useful info from logs
    urls_crawled = "unknown"
    save_failed = False
    db_shutdown_seen = False
    fatal_error = None
    for line in log_output.splitlines():
        # SF logs: "Completed the spider of ... crawled N urls"
        if "crawled" in line.lower() and "urls" in line.lower():
            match = re.search(r"crawled\s+(\d+)\s+urls", line, re.IGNORECASE)
            urls_crawled = match.group(1) if match else line.strip()
        if "crawl save failed" in line.lower():
            save_failed = True
        if "shutdown database" in line.lower() and "projectinstancedata" in line.lower():
            db_shutdown_seen = True
        if "FATAL" in line and fatal_error is None:
            fatal_error = line.strip()

    # SF 23.2 logs "Crawl save failed {}" even when the crawl is saved
    # successfully. Detect this false positive by checking for the database
    # shutdown line that proves the data was written to disk.
    if save_failed and db_shutdown_seen:
        save_failed = False

    # Determine actual status -- SF can exit 0 even on FATAL errors
    if fatal_error and proc.returncode == 0:
        status = "failed"
    elif proc.returncode == 0:
        status = "completed"
    else:
        status = f"failed (exit code {proc.returncode})"

    result = (
        f"Crawl {crawl_id} {status}.\n"
        f"URL: {info['url']}\n"
        f"Label: {info['label']}\n"
        f"Elapsed: {elapsed_str}\n"
        f"URLs crawled: {urls_crawled}\n"
    )

    if fatal_error:
        result += f"\nFATAL: {fatal_error}\n"

    if proc.returncode != 0 or fatal_error:
        # Show last 20 lines of filtered output for debugging
        filtered = _sanitize_sf_output(log_output)
        tail = "\n".join(filtered.strip().splitlines()[-20:])
        result += f"\nLast output:\n{tail}"

    if save_failed:
        result += (
            f"\n\nWARNING: Crawl save failed. The crawl data may not be "
            f"in SF's internal database. Check if the SF GUI has the "
            f"database locked, or try again."
        )
    elif fatal_error:
        result += (
            f"\n\nThe crawl did not complete successfully. "
            f"Check the error above and try again."
        )
    else:
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
        return "ERROR: Screaming Frog CLI not found. Check SF_CLI_PATH in .env."

    # Note: --list-crawls works fine even when the GUI is running (read-only).
    # No GUI check needed here.

    try:
        result = subprocess.run(
            [SF_CLI_PATH, "--headless", "--list-crawls"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

        output = result.stdout + result.stderr

        # Parse the crawl list from output
        # SF outputs crawl info in its log format
        crawl_lines = []
        for line in output.splitlines():
            # Filter out the verbose startup/info logs, keep crawl-relevant lines
            if any(skip in line for skip in _SF_LOG_FILTERS):
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
                + _sanitize_sf_output(output[-3000:])
                + "\n\nNote: If no crawls are shown, the SF database may be empty."
            )

        return "Saved crawls in SF database:\n\n" + "\n".join(crawl_lines)

    except subprocess.TimeoutExpired:
        return "ERROR: Timed out listing crawls (60s limit)."
    except Exception as exc:
        logger.exception("Failed to list crawls")
        return f"ERROR: Failed to list crawls: {type(exc).__name__}: {exc}"


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
        bulk_export: Optional bulk export types (e.g. 'All Inlinks,All Outlinks')
        save_report: Optional reports to save (e.g. 'Crawl Overview')

    Returns:
        An export_id and list of generated CSV files. Use read_crawl_data to read them.
    """
    if not os.path.exists(SF_CLI_PATH):
        return "ERROR: Screaming Frog CLI not found. Check SF_CLI_PATH in .env."

    # Validate all inputs
    db_err = _validate_db_id(db_id)
    if db_err:
        return db_err

    for param_name, param_val in [("export_tabs", export_tabs), ("bulk_export", bulk_export), ("save_report", save_report)]:
        if param_val:
            arg_err = _validate_cli_arg(param_val, param_name)
            if arg_err:
                return arg_err

    if _sf_gui_is_running():
        return SF_GUI_WARNING

    _cleanup_old_exports()

    # Enforce export limit
    if len(_export_dirs) >= MAX_ACTIVE_EXPORTS:
        return f"ERROR: Maximum {MAX_ACTIVE_EXPORTS} active exports. Wait for cleanup or delete old exports."

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
            proc.communicate(), timeout=EXPORT_TIMEOUT_SECONDS
        )
        stdout = stdout_raw.decode("utf-8", errors="replace")
        stderr = stderr_raw.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            filtered = _sanitize_sf_output(stdout + stderr)
            tail = "\n".join(filtered.strip().splitlines()[-15:])
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
                    first_line = fh.readline()
                    fh.seek(0)
                    reader = csv.reader(fh)
                    rows = sum(1 for _ in reader)
                    # Summary reports (crawl_overview.csv etc.) have no header row;
                    # tabular CSVs do. Only subtract header for tabular files.
                    if _is_sf_summary_report(first_line):
                        total_data_rows += rows
                    else:
                        total_data_rows += max(0, rows - 1)
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
            f"Files auto-delete after {EXPORT_TTL_SECONDS // 60} minutes."
        )
    except asyncio.TimeoutError:
        return (
            f"ERROR: Export timed out ({EXPORT_TIMEOUT_SECONDS}s limit). "
            f"The crawl may be very large. Set SF_EXPORT_TIMEOUT_SECONDS to increase."
        )
    except Exception as exc:
        logger.exception("Failed to export crawl")
        return f"ERROR: Failed to export crawl: {type(exc).__name__}: {exc}"


def _is_sf_summary_report(first_line: str) -> bool:
    """Detect whether a CSV file is an SF summary report (e.g. crawl_overview.csv).

    SF summary reports are vertical key-value layouts, not tabular CSVs.
    The first row is always a two-cell pair like: "Site Crawled","https://..."
    """
    try:
        cells = next(csv.reader([first_line]))
    except (csv.Error, StopIteration):
        return False
    return (
        len(cells) == 2
        and cells[0].strip().lower() == "site crawled"
    )


def _read_sf_summary_report(f, target: Path, export_dir: Path) -> str:
    """Parse an SF summary report (crawl_overview.csv and similar) into readable text.

    These files have:
    - Header key-value pairs (2 cells): "Site Crawled","https://example.com/"
    - Section headers (1 cell): "Internal"
    - Data rows (3-5 cells): "label","count","percent","total","description"
    - Blank rows separating sections
    """
    reader = csv.reader(f)
    output = f"File: {target.relative_to(export_dir)}\n"
    output += "(Screaming Frog summary report)\n\n"

    current_section = None

    for row in reader:
        # Skip empty rows
        if not row or all(cell.strip() == "" for cell in row):
            continue

        cells = [cell.strip() for cell in row]

        # Key-value header pair (exactly 2 non-empty cells).
        # These appear at the top of the file before any section headers.
        # Once we hit a section, 2-cell rows don't appear.
        if len(cells) == 2 and cells[0] and cells[1] and current_section is None:
            output += f"{cells[0]}: {cells[1]}\n"
            continue

        # Section header (single non-empty cell, not a number)
        if len(cells) == 1 or (len(cells) >= 1 and all(c == "" for c in cells[1:])):
            label = cells[0]
            if label and not label.replace(",", "").replace(".", "").isdigit():
                current_section = label
                output += f"\n=== {label} ===\n"
                continue

        # Sub-header row (e.g. "Summary","URLs","% of Total",...)
        # Detect by checking if it looks like column names (no pure-number cells)
        if len(cells) >= 3 and not any(
            c.replace(",", "").replace(".", "").replace("%", "").isdigit()
            for c in cells if c
        ):
            # This is a column header row within the report; skip it
            # (the data rows below are self-describing enough)
            continue

        # Data row: label, count, percent, and optionally total + description
        if len(cells) >= 3:
            label = cells[0]
            count = cells[1]
            pct = cells[2]
            output += f"  {label}: {count} ({pct})\n"
            continue

        # Fallback: render whatever we got
        output += "  " + " | ".join(cells) + "\n"

    return output


@mcp.tool()
def read_crawl_data(
    export_id: str,
    file: str,
    limit: int = 100,
    offset: int = 0,
    filter_column: Optional[str] = None,
    filter_value: Optional[Union[str, int, float]] = None,
    filter_mode: Optional[str] = None,
) -> str:
    """
    Read CSV data from an export. Use after export_crawl.

    Args:
        export_id: The export_id from export_crawl
        file: CSV filename to read (from the file list in export_crawl output)
        limit: Max rows to return (default 100, max 1000)
        offset: Number of rows to skip (for pagination)
        filter_column: Optional column name to filter by
        filter_value: Optional value to match in the filter column
        filter_mode: How to match filter_value: "contains" (default, case-insensitive substring), "exact" (case-insensitive exact match), or "regex" (Python regex)

    Returns:
        CSV data as formatted text with column headers.
    """
    # Clamp limit and offset to sane values
    limit = max(1, min(limit, MAX_READ_LIMIT))
    offset = max(0, offset)

    # Validate filter_mode
    mode = (filter_mode or "contains").lower()
    if mode not in ("contains", "exact", "regex"):
        return "ERROR: filter_mode must be 'contains', 'exact', or 'regex'"

    # Coerce filter_value to string (MCP clients may send numbers as int/float)
    if filter_value is not None:
        filter_value = str(filter_value)

    # Pre-compile regex if needed
    filter_regex = None
    if mode == "regex" and filter_value:
        try:
            filter_regex = re.compile(filter_value, re.IGNORECASE)
        except re.error as e:
            return f"ERROR: Invalid regex pattern: {e}"

    if export_id not in _export_dirs:
        active = ", ".join(_export_dirs.keys()) if _export_dirs else "none"
        return f"Unknown export_id: {export_id}\nActive exports: {active}"

    export_dir = _export_dirs[export_id]["path"]
    if not export_dir.exists():
        del _export_dirs[export_id]
        return "Export directory has been cleaned up. Run export_crawl again."

    # Find the file - try exact match first, then search
    # Sanitize: strip path separators and traversal attempts
    safe_file = Path(file).name  # extract just the filename, no directory components
    target = export_dir / file
    # Path traversal check
    if not _path_is_contained(target, export_dir):
        target = export_dir / safe_file  # fall back to just the filename

    if not target.exists():
        # Search subdirectories — only use the safe filename, escape glob chars
        escaped = glob.escape(safe_file)
        matches = [f for f in export_dir.rglob(escaped)
                   if _path_is_contained(f, export_dir) and not f.is_symlink()]
        if not matches:
            # Try partial match with escaped filename
            matches = [f for f in export_dir.rglob(f"*{escaped}*")
                       if _path_is_contained(f, export_dir) and not f.is_symlink()]
        if not matches:
            available = [str(f.relative_to(export_dir)) for f in export_dir.rglob("*.csv")]
            return f"File '{safe_file}' not found.\nAvailable files:\n" + "\n".join(f"  {f}" for f in available)
        target = matches[0]

    # Final containment check
    if not _path_is_contained(target, export_dir):
        return "ERROR: Invalid file path."

    try:
        with open(target, "r", encoding="utf-8-sig") as f:
            # Detect SF summary report format (e.g. crawl_overview.csv).
            # These files are vertical key-value layouts with section headers
            # and blank rows, NOT row-oriented tabular CSVs. The first row
            # is a reliable signal: two cells like "Site Crawled","https://..."
            first_line = f.readline()
            f.seek(0)

            if _is_sf_summary_report(first_line):
                return _read_sf_summary_report(f, target, export_dir)

            reader = csv.DictReader(f)

            # Validate filter_column exists in headers
            if filter_column and reader.fieldnames and filter_column not in reader.fieldnames:
                available = ", ".join(reader.fieldnames[:20])
                return f"Column '{filter_column}' not found.\nAvailable columns: {available}"

            rows = []
            skipped = 0
            for row in reader:
                # Apply filter
                if filter_column and filter_value:
                    cell = row.get(filter_column, "")
                    if mode == "exact":
                        if cell.lower() != filter_value.lower():
                            continue
                    elif mode == "regex":
                        if not filter_regex.search(cell):
                            continue
                    else:  # contains
                        if filter_value.lower() not in cell.lower():
                            continue

                if skipped < offset:
                    skipped += 1
                    continue

                rows.append(row)
                if len(rows) >= limit:
                    break

            if not rows:
                total_available = skipped  # rows that matched filter but were skipped by offset
                if offset > 0 and total_available > 0:
                    return (
                        f"No rows at offset {offset} in {file} "
                        f"(only {total_available} matching row{'s' if total_available != 1 else ''} total)."
                    )
                return f"No matching rows in {file}."

            # Format as text table
            columns = list(rows[0].keys())

            # Build output
            output = f"File: {target.relative_to(export_dir)}\n"
            output += f"Showing rows {offset + 1}-{offset + len(rows)}"
            if filter_column:
                output += f" (filtered: {filter_column} {mode} '{filter_value}')"
            output += f"\n\n"

            # Header
            output += " | ".join(columns) + "\n"
            output += "-+-".join("-" * min(len(c), 30) for c in columns) + "\n"

            # Rows
            for row in rows:
                values = []
                for col in columns:
                    val = row.get(col, "")
                    if val is not None and len(val) > 80:
                        val = val[:77] + "..."
                    values.append(val)
                output += " | ".join(values) + "\n"

            # Truncation note
            if len(rows) == limit:
                output += f"\n... limit of {limit} rows reached. Use offset={offset + limit} for next page."

            return output

    except Exception as exc:
        logger.exception("Failed to read export data")
        return f"ERROR: Failed to read {safe_file}: {type(exc).__name__}: {exc}"


@mcp.tool()
def delete_crawl(db_id: str) -> str:
    """
    Delete a crawl from Screaming Frog's internal database to free disk space.

    Args:
        db_id: The Database ID from list_crawls

    WARNING: This permanently deletes the crawl data. It cannot be undone.
    """
    if not os.path.exists(SF_CLI_PATH):
        return "ERROR: Screaming Frog CLI not found. Check SF_CLI_PATH in .env."

    db_err = _validate_db_id(db_id)
    if db_err:
        return db_err

    if _sf_gui_is_running():
        return SF_GUI_WARNING

    try:
        result = subprocess.run(
            [SF_CLI_PATH, "--headless", "--delete-crawl", db_id],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

        output = result.stdout + result.stderr

        if result.returncode == 0:
            return f"Crawl {db_id} deleted successfully."

        # Check for common errors -- filter internal paths from output
        filtered = _sanitize_sf_output(output)
        tail = "\n".join(filtered.strip().splitlines()[-10:])
        return f"Delete may have failed (exit code {result.returncode}):\n{tail}"

    except subprocess.TimeoutExpired:
        return "ERROR: Delete timed out (60s limit)."
    except Exception as exc:
        logger.exception("Failed to delete crawl")
        return f"ERROR: Failed to delete crawl: {type(exc).__name__}: {exc}"


@mcp.tool()
def storage_summary() -> str:
    """
    Show disk usage of Screaming Frog's internal crawl storage.
    Returns total size and per-crawl breakdown of ProjectInstanceData.
    """
    if not SF_DATA_DIR.exists():
        return "SF data directory not found."

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
    result += f"Total DB size: {_format_size(total_size)}\n\n"

    if entries:
        result += "Crawl databases:\n" + "\n".join(entries) + "\n"
    else:
        result += "No crawl databases found.\n"

    if temp_count > 0:
        result += f"\nTemp exports: {temp_count} dirs, {_format_size(temp_size)}"
        ttl_str = f"{EXPORT_TTL_SECONDS // 3600}h" if EXPORT_TTL_SECONDS >= 3600 else f"{EXPORT_TTL_SECONDS // 60}m"
        result += f" (auto-cleaned after {ttl_str})"

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
Export large datasets. Comma-separated list of export names (no Category: prefix).
Example: --bulk-export "All Inlinks,All Outlinks"

Available exports:
- All Links
- All Inlinks
- All Outlinks
- All Anchor Text
- Response Times
- Cookies
- Unique Content
- Near Duplicates
- Exact Duplicates
- Contains
- Does Not Contain
- Canonicals
- Hreflang
- All Image Inlinks
- All Image Outlinks
- Missing Alt Tags
- Alt Text Over 100
- JavaScript Links
- JavaScript Rendering
- All Redirect Chains
- HTTP Headers
- All Sitemap URLs
- All Structured Data
- Validation Errors
- Validation Warnings
- Accessibility Issues
- External Links

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


def main():
    """Run the Screaming Frog MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
