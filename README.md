# Screaming Frog SEO Spider MCP Server (headless)

A headless MCP (Model Context Protocol) server for [Screaming Frog SEO Spider](https://www.screamingfrog.co.uk/seo-spider/). It drives the SF command line and saved crawl database directly, so Claude (or any MCP-compatible client) can run crawls, export crawl data, and analyze the results with the Screaming Frog GUI closed: on your laptop, on a server, or inside scheduled audits and CI pipelines.

This is a community project, not affiliated with Screaming Frog. Since SEO Spider v24 there is also an official MCP built into the app. The two work differently and solve different problems.

## How this differs from the official Screaming Frog MCP

Screaming Frog shipped an [official MCP server in SEO Spider v24](https://www.screamingfrog.co.uk/blog/seo-spider-24/). It's substantial: around 29 tools covering crawl control (start, pause, resume, progress), reports and bulk exports with field selection, URL-level inspection, screenshots, embeddings exports, and optionally a Node.js script runner with npm and filesystem read/write tools. It runs in two modes, either a Streamable HTTP server inside the open app, or a STDIO mode where the MCP client launches the Spider itself, headless. Setup is documented for [Claude Desktop and LM Studio](https://www.screamingfrog.co.uk/seo-spider/user-guide/configuration/#mcp-server).

If you want maximum capability in an interactive session (visualizations, crawl comparison, screenshots, scripted post-processing of exports), use the official MCP. It does far more, and it's maintained by the vendor.

This server makes a different trade: it's a small, deliberately limited wrapper around SF's CLI and the saved crawl database, built for runs where nobody is watching.

**Locked-down by design.** Eight read-and-export tools, nothing else. No script runner, no `npm install`, no filesystem write access. The official MCP offers all three, and its own docs note that enabling the Node runtime "allows the execution of arbitrary code on your system" and should only be granted to a fully trusted client. There's also an `SF_ALLOWED_DOMAINS` allowlist to restrict what an agent is able to crawl. When an agent runs unattended on a schedule, a tool surface this small is a feature.

**Installs anywhere, plainly.** A pip/uv-installable Python package with a one-line stdio config on any MCP client (Claude Code, Cursor, whatever) on macOS, Linux, or Windows. The official STDIO mode ships as a Claude Desktop extension (`.mcpb`); the HTTP mode means opening the app and starting the server from its settings.

**Light process model.** Screaming Frog only runs while a tool actually needs it. The official server *is* the Spider application running for the whole session, whichever mode you pick.

**A few tools the official set doesn't have:** `aggregate_crawl_data` for counts and distributions computed server-side (the official path to "how many 404s" is a full export, or a Node script), `delete_crawl` and `storage_summary` for cleaning up SF's crawl database (their `sf_clear_crawl` clears a paused crawl, it doesn't manage stored ones), regex filtering across any column of any export via `read_crawl_data`, and `sf_check` pre-flight diagnostics that catch license problems and GUI database locks before you waste a crawl.

**What it feels like from chat.** The official server is stateful: you ask it to load a crawl by ID, the Spider holds it in memory for the session, and follow-up questions answer in under a second. The cost is that the session owns SF's database the whole conversation, and exports come back as full inline dumps unless the model saves files and writes Node scripts to slice them (the approach their own docs recommend for staying inside the context window). This server is stateless: each export spawns the SF CLI fresh, so the first answer on a crawl takes longer, but you can just ask ("list my crawls, export the latest one") without managing IDs or sessions, reads return only the filtered rows you asked for, and the database is released between calls. For "show me the 404s on a 100k-URL crawl", the difference is the whole export in context versus a page of matching rows.

Typical split: crawl interactively in the GUI with your full config, close it, and let this server handle the unattended side. That covers scheduled audits, CI checks, and agents querying the saved data. Both need a licensed Screaming Frog install on the same machine; neither is a cloud crawler. Note that this server requires the GUI to be closed (SF's database allows one process at a time).

## See it in action

The [Pre-Launch Website Audit](https://github.com/bzsasson/pre-launch-audit-skill) skill for Claude Code uses this MCP server for its technical SEO and on-page audits, site-wide crawl data, custom extractions, bulk analysis across all URLs. The skill runs 5 coordinated sub-audits and works without SF (bash fallbacks), but Screaming Frog is the biggest upgrade for crawl-dependent checks.

## Prerequisites

1. **Screaming Frog SEO Spider** installed on your machine (tested with v23.x and v24.x, should work with v16+).
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

> **Avoid `uvx screaming-frog-mcp` in MCP client configs.** `uvx` resolves and downloads the package environment at launch. On a cold cache this can exceed the client's 60-second initialize timeout, causing intermittent "Could not attach to MCP server" errors. A persistent install never touches the network at startup.

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

Find the executable path with `which screaming-frog-mcp` (e.g. `~/.local/bin/screaming-frog-mcp` for uv tool installs). Use the full absolute path, since GUI apps don't inherit your shell's PATH.

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
| `read_crawl_data` | Read exported CSV data with pagination, filtering, and column selection |
| `aggregate_crawl_data` | Counts and group-by breakdowns over exported data ("how many 404s", "status code distribution") without reading rows into context |
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

> **Server won't connect at all?** ("Could not attach to MCP server", "failed to connect") See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for a step-by-step diagnostic guide: testing the server manually, verifying the MCP handshake, and finding your client's logs.

| Problem | Solution |
|---------|----------|
| "GUI is already running" error | Quit the Screaming Frog application, then retry |
| Empty CSV exports (headers only, 0 data rows) | The GUI likely has the database locked — close it and re-export |
| CLI not found | Check that `SF_CLI_PATH` in `.env` points to the correct executable |
| Crawl not appearing in `list_crawls` | Make sure you saved the crawl in the GUI (File > Save) before closing |
| Export times out | Large crawls may need more time — set `SF_EXPORT_TIMEOUT_SECONDS` to a higher value (e.g. `600`), or export fewer tabs |
| `list_crawls` fails on Windows | Fixed in v0.2.2 — update with `uv tool upgrade screaming-frog-mcp` or `pip install -U screaming-frog-mcp` |
| "Could not attach to MCP server" / initialize timeout | Your config launches the server via `uvx`, which downloads dependencies at startup and can exceed the 60s handshake timeout on a cold cache. Switch to a persistent install (`uv tool install screaming-frog-mcp`) and point `command` at the installed executable, per [Setup](#setup) |

## License

MIT

<!-- mcp-name: io.github.bzsasson/screaming-frog-mcp -->
