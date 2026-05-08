# Changelog

## 0.3.3 (2026-05-08)

### Bug fixes

- **Fixed false "Crawl save failed" warning on SF 23.2.** Screaming Frog 23.2 logs `WARN - Crawl save failed {}` even when the crawl saves successfully. The server now detects this false positive by checking for the database shutdown confirmation that proves data was written to disk. Genuine save failures (no database shutdown) still produce the warning.

## 0.3.2 (2026-05-08)

### Bug fixes

- Fixed PyPI publish workflow: pinned SHA was the annotated tag object, not the commit. Docker image lookup failed.
- Updated README: removed reference to removed `max_urls` parameter.

## 0.3.1 (2026-05-08)

### Bug fixes

- **Removed broken `max_urls` parameter from `crawl_site`.** The `--max-crawl-size` CLI flag doesn't exist in Screaming Frog. The parameter silently failed (SF exits 0 with FATAL). To limit crawl size, pass a config file via `config_file` instead.
- **Fixed `crawl_status` always showing "URLs crawled: unknown".** The parser looked for "urls crawled" but SF logs "crawled N urls". Now extracts the numeric count.
- **Fixed `crawl_status` falsely claiming "saved in SF's internal database"** when SF logged a FATAL error on startup or "Crawl save failed". Now detects both conditions and reports them accurately.
- **Fixed `read_crawl_data` showing "No matching rows"** when offset exceeds total rows. Now shows "No rows at offset N (only M matching rows total)".

### Improvements

- `crawl_site` now detects immediate startup failures (FATAL errors, bad flags, license issues) within 2 seconds and returns an error instead of falsely reporting the crawl as started.
- Pinned `pypa/gh-action-pypi-publish` to v1.14.0 SHA for supply chain safety.
- Added 40 new tests (172 total): sf_check parsing, env var configuration, error format consistency, row count logic, crawl status parsing, offset behavior.

## 0.3.0 (2026-05-08)

### Bug fixes

- Fixed `read_crawl_data` failing on Screaming Frog summary reports (`crawl_overview.csv` and similar `--save-report` exports). These files use a vertical key-value layout with section headers, not tabular CSVs -- `csv.DictReader` would misparse them and the error was silently swallowed.
- Fixed `sf_check` returning "Version: unknown / License: unknown" on working installs. The `--help` flag doesn't emit version or license info; switched to `--list-crawls` (read-only) which does.
- Fixed `export_crawl` data row count undercounting summary report files (no header row to subtract).
- Fixed duplicated log filter list in `list_crawls` that could drift from the shared `_SF_LOG_FILTERS` constant.

### Improvements

- All error messages now include the exception type and message instead of opaque "Failed to ..." strings. Affects `crawl_site`, `list_crawls`, `export_crawl`, `delete_crawl`, `read_crawl_data`, and `sf_check`.
- `SF_EXPORT_TTL_SECONDS` env var: configure how long exported CSV files are kept before auto-cleanup (default: 3600s / 1 hour). Useful for multi-hour audit sessions.
- `SF_EXPORT_TIMEOUT_SECONDS` env var: configure max wait time for `export_crawl` operations (default: 300s / 5 minutes). Increase for very large crawls (100k+ URLs).

### New features

- Summary report parsing: `read_crawl_data` now detects and properly renders SF summary reports (e.g. `crawl_overview.csv`) as structured, readable text with section headers and key-value pairs.

## 0.2.2 (2026-04-22)

### Bug fixes

- Fixed `UnicodeDecodeError` on Windows (cp1252 locale) that crashed `list_crawls` and could affect other subprocess calls (#5)
- Added `encoding='utf-8', errors='replace'` to all `subprocess.run` calls so non-ASCII CLI output is handled safely on any locale
- Added `None` guard on value length check in `read_crawl_data` CSV rendering

## 0.2.1 (2026-04-20)

### New features

- `filter_mode` parameter for `read_crawl_data`: `contains` (default), `exact`, or `regex`
- CI pipeline: tests run on push/PR across Python 3.10-3.13
- Trusted publishing: PyPI releases via GitHub Actions (no manual token needed)

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
