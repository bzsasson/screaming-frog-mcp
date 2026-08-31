# Release checklist

Every version bump goes through all of these steps. The MCP registry step is
the one that gets forgotten: bumping `server.json` in git does nothing until
`mcp-publisher publish` runs (the registry sat at 0.1.0 while PyPI reached
0.4.0 because of exactly this).

1. Bump `version` in `pyproject.toml`.
2. Bump both `version` fields in `server.json` (top-level and `packages[0]`)
   to match. Keep `description` at 100 characters or fewer — the registry
   rejects longer ones with a 422.
3. Add a CHANGELOG.md entry.
4. Commit, tag `vX.Y.Z`, push.
5. Publish to PyPI (build + upload, or the release workflow if one exists).
6. Publish to the MCP registry:

   ```
   mcp-publisher login github   # only if the cached token expired
   mcp-publisher publish
   ```

   Login uses a GitHub device code that must be approved in a browser.

7. Verify both:

   ```
   curl -s https://pypi.org/pypi/screaming-frog-mcp/json | jq -r .info.version
   curl -s "https://registry.modelcontextprotocol.io/v0/servers/io.github.bzsasson%2Fscreaming-frog-mcp/versions" | jq -r '.servers[] | select(._meta["io.modelcontextprotocol.registry/official"].isLatest) | .server.version'
   ```

   The registry search endpoint (`/v0/servers?search=`) lags behind the
   versions endpoint; trust the versions endpoint.
