# Troubleshooting

Start by identifying which kind of failure you have:

- **Your MCP client can't connect.** Messages like "Could not attach to MCP server screaming-frog", "failed to connect", or the server showing as disconnected in your client. Go to [Connection failures](#connection-failures).
- **The server connects, but tools fail.** `sf_check`, exports, or crawls return errors. Go to [Tool errors](#tool-errors).

## Connection failures

A connection failure means your MCP client (Claude Code, Claude Desktop, etc.) couldn't launch the server process or didn't get a handshake response in time. The server code is almost never the culprit. It's usually the launch command, PATH, or a startup timeout.

### Step 1: Run the configured command manually

Copy the exact `command` from your MCP config and run it in a terminal:

```bash
/path/to/screaming-frog-mcp
```

- **It sits silently waiting for input.** That's healthy. The server speaks JSON-RPC on stdin/stdout and prints nothing until the client talks to it. Press Ctrl+C and move to Step 2.
- **`command not found` or `no such file or directory`.** The path in your config is wrong, or you used a bare command name like `uvx` or `screaming-frog-mcp`. GUI apps (Claude Desktop) do not inherit your shell's PATH, so bare names that work in your terminal can still fail in the client. Find the absolute path with `which screaming-frog-mcp` and put that in the config.
- **A Python traceback.** The installed environment is broken. Reinstall: `uv tool install --force screaming-frog-mcp` (or `pip install --force-reinstall screaming-frog-mcp`).

### Step 2: Test the MCP handshake

Send an `initialize` request and confirm the server answers (macOS/Linux):

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}' | /path/to/screaming-frog-mcp
```

A healthy server replies within a second or two with a JSON object containing `"serverInfo":{"name":"Screaming Frog SEO Spider",...}`. If you get that, the server is fine and the problem is in your client config or a startup timeout (see below).

### Step 3: Check the client logs

The client logs say exactly why the connection failed.

**Claude Code** (macOS; on Linux use `~/.cache/` instead of `~/Library/Caches/`):

```
~/Library/Caches/claude-cli-nodejs/<project-dir>/mcp-logs-screaming-frog/*.jsonl
```

You can also run `claude --debug` or use the `/mcp` command inside Claude Code to see live connection status.

**Claude Desktop** (macOS paths; on Windows look under `%APPDATA%\Claude\logs\`):

```
~/Library/Logs/Claude/mcp-server-screaming-frog.log
~/Library/Logs/Claude/mcp.log
```

### Common causes

| Symptom in the logs | Cause | Fix |
|---|---|---|
| `Request timed out` / `MCP error -32001` during initialize, often with a `Downloading ...` line just before it | The config launches the server via `uvx`, which resolves and downloads the package environment at startup. On a cold or invalidated uv cache this exceeds the client's 60-second handshake timeout. It is intermittent: once the cache is warm it connects fine, then breaks again when a dependency re-resolves. | Switch to a persistent install: `uv tool install screaming-frog-mcp`, then point `command` at the absolute path of the installed executable (see [Setup](README.md#setup)). |
| `spawn uvx ENOENT` / `command not found` | Bare command name and the client doesn't have your shell's PATH | Use the absolute path in `command` |
| Config changes have no effect | The client only reads its config at startup | Restart Claude Desktop, or start a new Claude Code session |

## Tool errors

If the server connects but tools fail, run `sf_check` first ("Is Screaming Frog installed and licensed?"). It verifies the Screaming Frog CLI path, version, and license, and its error messages name the specific problem.

The most common cause by far: **the Screaming Frog GUI is open.** SF's database allows one process at a time, so the MCP server cannot read or export crawl data while the GUI runs. Quit the GUI and retry.

For the full symptom table (empty exports, CLI not found, export timeouts, missing crawls), see [Troubleshooting in the README](README.md#troubleshooting).

## Checking and updating your version

The server binary takes no `--version` flag (it immediately starts speaking MCP on stdin). Check the installed version with:

```bash
uv tool list          # if installed as a uv tool
pip show screaming-frog-mcp   # if installed with pip
```

Compare against the [latest release on PyPI](https://pypi.org/project/screaming-frog-mcp/), and update with `uv tool upgrade screaming-frog-mcp` or `pip install -U screaming-frog-mcp`. Restart your MCP client afterwards.

## Still stuck?

[Open an issue](https://github.com/bzsasson/screaming-frog-mcp/issues) and include:

- Your OS and MCP client (Claude Code / Claude Desktop / other) with versions
- The `screaming-frog` entry from your MCP config
- The output of the manual run and handshake test (Steps 1–2)
- The relevant client log lines (Step 3)
- The output of `sf_check`, if the server connects
