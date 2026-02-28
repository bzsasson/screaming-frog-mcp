# Screaming Frog SEO Spider MCP Server

An MCP (Model Context Protocol) server that gives Claude (or any MCP-compatible client) programmatic access to [Screaming Frog SEO Spider](https://www.screamingfrog.co.uk/seo-spider/) — crawl websites, export crawl data, and manage your crawl storage, all from your AI assistant.

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

### 1. Clone and install

```bash
git clone https://github.com/bzsasson/screaming-frog-mcp.git
cd screaming-frog-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure the CLI path

Copy the example env file and adjust the path if needed:

```bash
cp .env.example .env
```

The default path works for macOS. Edit `.env` if you're on Linux or Windows:

| OS      | Default Path |
|---------|-------------|
| macOS   | `/Applications/Screaming Frog SEO Spider.app/Contents/MacOS/ScreamingFrogSEOSpiderLauncher` |
| Linux   | `/usr/bin/screamingfrogseospider` |
| Windows | `C:\Program Files (x86)\Screaming Frog SEO Spider\ScreamingFrogSEOSpiderCli.exe` |

### 3. Add to Claude Code

Add the following to your Claude Code MCP settings (`~/.claude/settings.json` or project-level `.claude/settings.json`):

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

Replace `/path/to/` with the actual path where you cloned the repo.

### For other MCP clients

The server runs as a standard MCP stdio server. Start it with:

```bash
/path/to/.venv/bin/python /path/to/sf_mcp.py
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

> "Crawl https://example.com with a max of 100 URLs"

The `crawl_site` tool can kick off headless crawls via CLI. This is useful for quick re-crawls or automated workflows, but note the limitations compared to the GUI:
- Uses default crawl settings (no custom extraction, JavaScript rendering config, etc.)
- You can pass a `.seospiderconfig` file to customize settings, but the GUI is easier for complex setups
- The crawl must finish and save before you can export data

### Export options

The server supports all of Screaming Frog's export tabs, bulk exports, and reports. Ask the assistant to read the `screaming-frog://export-reference` resource for the full list, or specify them directly:

```
export_tabs: "Internal:All,Response Codes:All,Page Titles:All"
bulk_export: "All Inlinks,All Outlinks"
save_report: "Crawl Overview"
```

## Temp file cleanup

Exported CSVs are stored in temporary directories (`/tmp/sf-exports/`) and are automatically cleaned up after 1 hour.

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "GUI is already running" error | Quit the Screaming Frog application, then retry |
| Empty CSV exports (headers only, 0 data rows) | The GUI likely has the database locked — close it and re-export |
| CLI not found | Check that `SF_CLI_PATH` in `.env` points to the correct executable |
| Crawl not appearing in `list_crawls` | Make sure you saved the crawl in the GUI (File > Save) before closing |
| Export times out | Large crawls may need more time — try exporting fewer tabs |

## License

MIT
