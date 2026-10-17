# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please report it responsibly.

**Email:** bzsasson+security@gmail.com

**Please include:**
- Description of the vulnerability
- Steps to reproduce
- Affected files and line numbers
- Suggested fix (if any)

**Response timeline:**
- Acknowledgment within 48 hours
- Fix target within 14 days for critical issues
- We follow coordinated disclosure -- please allow time for a fix before public disclosure

## Scope

This MCP server wraps the Screaming Frog CLI and accepts input from AI model clients.
The primary threat model is prompt injection via malicious web content influencing
the AI client to send crafted tool parameters.

Security-relevant areas:
- Input validation for all tool parameters
- SSRF protection for crawl URLs
- Path traversal protection for file operations
- CLI argument injection prevention

### Limits of the SSRF protection

The server validates the crawl seed URL before starting: scheme allowlist,
private and link-local IP blocking, DNS resolution checks, and the optional
`SF_ALLOWED_DOMAINS` allowlist. It does not and cannot control what
Screaming Frog itself fetches after the crawl starts. SF follows redirects
and status-checks the links it discovers, so crawling a hostile site can
cause SF to send requests to addresses the seed check would have rejected,
including internal ones. This is inherent to running any crawler against
untrusted content, not specific to this wrapper. When crawling sites you do
not control, run the crawl from a network position where internal requests
are harmless, and use a `.seospiderconfig` that disables external link
checking. The seed validation is a guardrail against a prompt-injected
crawl target, not a sandbox around the crawler.

## Supported Versions

Only the latest release on PyPI receives security updates.
