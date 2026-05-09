# Screaming Frog SEO Spider MCP Server

An MCP (Model Context Protocol) server that gives Claude (or any MCP-compatible client) programmatic access to [Screaming Frog SEO Spider](https://www.screamingfrog.co.uk/seo-spider/), crawl websites, export crawl data, and manage your crawl storage, all from your AI assistant.

## See it in action

The [Pre-Launch Website Audit](https://github.com/bzsasson/pre-launch-audit-skill) skill for Claude Code uses this MCP server for its technical SEO and on-page audits, site-wide crawl data, custom extractions, bulk analysis across all URLs. The skill runs 5 coordinated sub-audits and works without SF (bash fallbacks), but Screaming Frog is the biggest upgrade for crawl-dependent checks.

## Prerequisites

1. **Screaming Frog SEO Spider** installed on your machine (tested with v23.x, should work with v16+).
   Download from: https://www.screamingfrog.co.uk/seo-spider/

2. **A valid Screaming Frog license.** The free version has a 500-URL crawl limit. Most MCP features (headless CLI, saving/loading crawls, exports) require a paid license.

3. **Python 3.10+**

## Important: How the Workflow Works

Screaming Frog uses an internal database that can only be accessed by one process at a time. This means:

> **You must close the Screaming Frog GUI before the MCP server can access crawl data.**

The typical workflow is:

1. **Run your crawl** — either through the SF GUI (with all your custom settings, filters, etc.) or via the MCP `crawl_site` tool.
2. **Close the Screaming Frog GUI** — the GUI locks the crawl database. The MCP server's headless CLI cannot read or export data while the GUI is running.
3. **Use the MCP tools** — once the GUI is closed, you can list crawls, export data, read CSVs, and more through your AI assistant.

If you forget to close the GUI, the server will detect it and show a clear error message telling you to quit SF first.

## Setup

### Option A: Install from PyPI (recommended)

```bash
pip install screaming-frog-mcp
```

Or run directly with `uvx` (no install needed):

```bash
uvx screaming-frog-mcp
```

### Option B: Clone and install from source

```bash
git clone https://github.com/bzsasson/screaming-frog-mcp.git
cd screaming-frog-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Configure the CLI path

The default Screaming Frog CLI path works for macOS. If you're on Linux or Windows, set the `SF_CLI_PATH` environment variable:

| OS      | Default Path |
|---------|-------------|
| macOS   | `/Applications/Screaming Frog SEO Spider.app/Contents/MacOS/ScreamingFrogSEOSpiderLauncher` |
| Linux   | `/usr/bin/screamingfrogseospider` |
| Windows | `C:\Program Files (x86)\Screaming Frog SEO Spider\ScreamingFrogSEOSpiderCli.exe` |

If you cloned the repo, copy `.env.example` to `.env` and edit it.

### Add to Claude Code

If installed via pip/uvx:

```json
{
  "mcpServers": {
    "screaming-frog": {
      "command": "uvx",
      "args": ["screaming-frog-mcp"],
      "env": {
        "SF_CLI_PATH": "/path/to/ScreamingFrogSEOSpiderLauncher"
      }
    }
  }
}
```

If cloned from source:

```json
{
  "mcpServers": {
    "screaming-frog": {
      "command": "/path/to/screaming-frog-mcp/.venv/bin/python",
      "args": ["/path/to/screaming-frog-mcp/sf_mcp.py"]
    }
  }
}
```

### Add to Claude Desktop

Add to your Claude Desktop config (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "screaming-frog": {
      "command": "uvx",
      "args": ["screaming-frog-mcp"],
      "env": {
        "SF_CLI_PATH": "/path/to/ScreamingFrogSEOSpiderLauncher"
      }
    }
  }
}
```

## Available Tools

| Tool | Description |
|------|-------------|
| `sf_check` | Verify Screaming Frog is installed, check version and license status |
| `crawl_site` | Start a headless background crawl (see note below) |
| `crawl_status` | Check progress of a running crawl |
| `list_crawls` | List all saved crawls with their Database IDs |
| `export_crawl` | Export crawl data as CSV files (many export options available) |
| `read_crawl_data` | Read exported CSV data with pagination and filtering |
| `delete_crawl` | Permanently delete a crawl from the database |
| `storage_summary` | Show disk usage of SF's crawl storage |

## Usage Examples

### Check installation

> "Is Screaming Frog installed and licensed?"

The assistant will call `sf_check` and report version/license info.

### Work with existing crawls (recommended flow)

For most use cases, **crawl in the Screaming Frog GUI** where you have full control over configuration, JavaScript rendering, crawl scope, custom extraction, etc. Then close the GUI and use the MCP to analyze the results:

After you've crawled a site in the Screaming Frog GUI and closed it:

> "List my saved crawls"
> "Export the crawl for example.com"
> "Show me all pages with missing meta descriptions"
> "What are the 404 pages?"

### Crawl a site via MCP (optional)

> "Crawl https://example.com"

The `crawl_site` tool can kick off headless crawls via CLI. This is useful for quick re-crawls or automated workflows, but note the limitations compared to the GUI:
- Uses default crawl settings (no custom extraction, JavaScript rendering config, etc.)
- You can pass a `.seospiderconfig` file to customize settings (including crawl URL limits), but the GUI is easier for complex setups
- The crawl must finish and save before you can export data

### Export options

The server supports all of Screaming Frog's export tabs, bulk exports, and reports. Ask the assistant to read the `screaming-frog://export-reference` resource for the full list, or specify them directly:

```
export_tabs: "Internal:All,Response Codes:All,Page Titles:All"
bulk_export: "All Inlinks,All Outlinks"
save_report: "Crawl Overview"
```

## Configuration

### Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SF_CLI_PATH` | Path to the Screaming Frog CLI executable | macOS default path |
| `SF_ALLOWED_DOMAINS` | Comma-separated list of allowed crawl target domains. When set, `crawl_site` only accepts URLs matching these domains. | Empty (all domains allowed) |
| `SF_CONFIG_DIR` | Directory containing `.seospiderconfig` files that `crawl_site` can load. | `~/.config/sf-mcp/configs/` |
| `SF_EXPORT_TTL_SECONDS` | How long exported CSV files are kept before auto-cleanup. Increase for multi-hour audit sessions. | `3600` (1 hour) |
| `SF_EXPORT_TIMEOUT_SECONDS` | Max time to wait for an `export_crawl` operation to complete. Increase for very large crawls (100k+ URLs). | `300` (5 minutes) |

### Filtering modes

`read_crawl_data` supports three filter modes via the `filter_mode` parameter:

| Mode | Behavior | Example |
|------|----------|---------|
| `contains` (default) | Case-insensitive substring match | `filter_value="4"` matches 400, 204, 1450 |
| `exact` | Case-insensitive exact match | `filter_value="404"` matches only 404 |
| `regex` | Python regex (case-insensitive) | `filter_value="^[45]"` matches 4xx and 5xx |

## Temp file cleanup

Exported CSVs are stored in `~/.cache/sf-mcp/exports/` and are automatically cleaned up after 1 hour (configurable via `SF_EXPORT_TTL_SECONDS`).

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "GUI is already running" error | Quit the Screaming Frog application, then retry |
| Empty CSV exports (headers only, 0 data rows) | The GUI likely has the database locked — close it and re-export |
| CLI not found | Check that `SF_CLI_PATH` in `.env` points to the correct executable |
| Crawl not appearing in `list_crawls` | Make sure you saved the crawl in the GUI (File > Save) before closing |
| Export times out | Large crawls may need more time — set `SF_EXPORT_TIMEOUT_SECONDS` to a higher value (e.g. `600`), or export fewer tabs |
| `list_crawls` fails on Windows | Fixed in v0.2.2 — update with `uvx screaming-frog-mcp@latest` or `pip install -U screaming-frog-mcp` |

## License

MIT

<!-- mcp-name: io.github.bzsasson/screaming-frog-mcp -->
