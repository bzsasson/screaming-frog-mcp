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

## Supported Versions

Only the latest release on PyPI receives security updates.
