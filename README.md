# Screaming Frog SEO Spider MCP Server (headless)

A headless MCP (Model Context Protocol) server for [Screaming Frog SEO Spider](https://www.screamingfrog.co.uk/seo-spider/). It drives the SF command line and saved crawl database directly, so Claude (or any MCP-compatible client) can run crawls, export crawl data, and analyze the results with the Screaming Frog GUI closed — on your laptop, on a server, or inside scheduled audits and CI pipelines.

This is a community project, not affiliated with Screaming Frog. Since SEO Spider v24 there is also an official MCP built into the app — the two work differently and solve different problems.

## How this differs from the official Screaming Frog MCP

Screaming Frog shipped an [official MCP server in SEO Spider v24](https://www.screamingfrog.co.uk/blog/seo-spider-24/). It runs inside the desktop application: you open the app, enable the MCP server (a local HTTP endpoint), and your AI client controls the live session. The application has to stay open the whole time.

This server is the opposite. It talks to Screaming Frog's headless CLI and the saved crawl database, and it requires the GUI to be *closed* (SF's database only allows one process at a time). No desktop session, no open port, no Node runtime — just a Python process speaking stdio.

In practice that means:

**Use the official MCP when** you're at your machine with the app open and want to work interactively — start a crawl from chat, generate link-equity visualizations, auto-compare your last two crawls, or pull in Ahrefs data through SF's API integrations. None of that exists here.

**Use this server when** there is no GUI session to attach to:

- Scheduled or recurring audits (cron jobs, Claude Code scheduled agents) where nobody is around to open an app
- CI pipelines and remote servers
- Analyzing a crawl after the fact — run the crawl in the GUI with your full config, close it, then query the saved data
- Large crawls where you need `read_crawl_data`'s pagination and regex filtering to pull specific rows instead of dumping whole CSVs into the model's context window
- Housekeeping on the crawl database itself: `list_crawls`, `delete_crawl`, `storage_summary`

A few things only this server currently does: pre-flight diagnostics (`sf_check` catches license problems and GUI database locks before you waste a crawl), filtered and paginated reads of any export, and crawl storage management. A few things only the official one does: visual outputs, crawl comparison, and live control of an open session.

Both need a licensed Screaming Frog install on the same machine — neither is a cloud crawler. The two configs can coexist in the same MCP client; they just can't touch the database at the same moment, because the official one needs the app open and this one needs it closed.

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

Install as a persistent [uv tool](https://docs.astral.sh/uv/guides/tools/) so the server starts instantly:

```bash
uv tool install screaming-frog-mcp
```

This puts a `screaming-frog-mcp` executable on your PATH (typically `~/.local/bin/screaming-frog-mcp`). Update later with `uv tool upgrade screaming-frog-mcp`.

Alternatively, install with pip:

```bash
pip install screaming-frog-mcp
```

> **Avoid `uvx screaming-frog-mcp` in MCP client configs.** `uvx` resolves and downloads the package environment at launch — on a cold cache this can exceed the client's 60-second initialize timeout, causing intermittent "Could not attach to MCP server" errors. A persistent install never touches the network at startup.

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

If installed via `uv tool install` or pip:

```json
{
  "mcpServers": {
    "screaming-frog": {
      "command": "/path/to/screaming-frog-mcp",
      "args": [],
      "env": {
        "SF_CLI_PATH": "/path/to/ScreamingFrogSEOSpiderLauncher"
      }
    }
  }
}
```

Find the executable path with `which screaming-frog-mcp` (e.g. `~/.local/bin/screaming-frog-mcp` for uv tool installs). Use the full absolute path — GUI apps don't inherit your shell's PATH.

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

Add to your Claude Desktop config (`claude_desktop_config.json`), using the same absolute executable path:

```json
{
  "mcpServers": {
    "screaming-frog": {
      "command": "/path/to/screaming-frog-mcp",
      "args": [],
      "env": {
        "SF_CLI_PATH": "/path/to/ScreamingFrogSEOSpiderLauncher"
      }
    }
  }
}
```

Restart Claude Desktop after editing the config.

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

> **Server won't connect at all?** ("Could not attach to MCP server", "failed to connect") — see [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for a step-by-step diagnostic guide: testing the server manually, verifying the MCP handshake, and finding your client's logs.

| Problem | Solution |
|---------|----------|
| "GUI is already running" error | Quit the Screaming Frog application, then retry |
| Empty CSV exports (headers only, 0 data rows) | The GUI likely has the database locked — close it and re-export |
| CLI not found | Check that `SF_CLI_PATH` in `.env` points to the correct executable |
| Crawl not appearing in `list_crawls` | Make sure you saved the crawl in the GUI (File > Save) before closing |
| Export times out | Large crawls may need more time — set `SF_EXPORT_TIMEOUT_SECONDS` to a higher value (e.g. `600`), or export fewer tabs |
| `list_crawls` fails on Windows | Fixed in v0.2.2 — update with `uv tool upgrade screaming-frog-mcp` or `pip install -U screaming-frog-mcp` |
| "Could not attach to MCP server" / initialize timeout | Your config launches the server via `uvx`, which downloads dependencies at startup and can exceed the 60s handshake timeout on a cold cache. Switch to a persistent install (`uv tool install screaming-frog-mcp`) and point `command` at the installed executable — see [Setup](#setup) |

## License

MIT

<!-- mcp-name: io.github.bzsasson/screaming-frog-mcp -->
