# Changelog

## 0.2.0 (2026-04-20)

### Security

- Tightened input validation across all tool parameters
- Strengthened SSRF protection with DNS resolution checks and IPv6 handling
- Added config file path containment
- Sanitized CLI output in error responses to prevent information leakage
- Added `SECURITY.md` with vulnerability reporting policy
- Added 98-test security test suite

### New features

- `SF_ALLOWED_DOMAINS` env var: optional comma-separated domain allowlist for crawl targets
- `SF_CONFIG_DIR` env var: restrict `.seospiderconfig` file loading to a safe directory (default `~/.config/sf-mcp/configs/`)
- `read_crawl_data` now validates `filter_column` against CSV headers and reports available columns on mismatch

### Bug fixes

- Fixed pipe buffer deadlock on long-running crawls (macOS)
- Added 2-hour crawl timeout to prevent runaway processes
- Capped `read_crawl_data` limit to 1000 rows to prevent memory exhaustion
- Clamped negative `limit` and `offset` values to sane defaults
- Rejected negative `max_urls` values in `crawl_site`
- Fixed misleading pagination message when using offset

### Internal

- Deduplicated `sf_mcp.py` into thin wrapper over `src/screaming_frog_mcp/server.py`
- Removed unused imports

## 0.1.0 (2026-03-01)

Initial release.
