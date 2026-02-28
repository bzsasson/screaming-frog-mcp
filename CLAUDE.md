# Screaming Frog MCP Server

## Project context
MCP server giving Claude (or any MCP client) access to Screaming Frog SEO Spider's crawl data. Public repo at github.com/bzsasson/screaming-frog-mcp.

## Marketing workflow
All marketing plans, content, and tracking live in `/marketing/` (gitignored, local only).

### "marketing next step" protocol
When the user says "marketing next step" (or similar):
1. Read `marketing/TRACKER.md` — this has the full plan with checkboxes
2. Find the first unchecked item in the current phase
3. Execute it (submit a PR, prep content for posting, etc.)
4. Update the checkbox in TRACKER.md when done
5. Tell the user what was done and what's next

### Content for posting
Ready-to-post content lives in `marketing/content/`. Each file is a self-contained post for a specific platform. The user copy-pastes to post — Claude cannot post to social media or web forums directly.

### Directory submissions
PRs to awesome-mcp lists can be created directly via `gh` CLI. Web directory submissions (forms) need the user to visit the URL and submit.

### What's safe to do autonomously
- Submit PRs to GitHub awesome lists (PRs are proposals, low risk)
- Update repo metadata (description, topics)
- Create/update marketing content files
- Update TRACKER.md

### What needs user action
- Posting to Reddit, Twitter/X, HN, Discord (user copy-pastes from content files)
- Web form submissions to directories
- Anything that sends messages from the user's accounts

### "marketing check" protocol
When the user says "marketing check" (or at the start of any marketing session):
1. Run: `gh api repos/bzsasson/screaming-frog-mcp --jq '{stars: .stargazers_count, forks: .forks_count, watchers: .subscribers_count, open_issues: .open_issues_count}'`
2. Run: `gh api repos/bzsasson/screaming-frog-mcp/traffic/views --jq '{views_14d: .count, uniques_14d: .uniques}'` (may need push access)
3. Run: `gh api repos/bzsasson/screaming-frog-mcp/traffic/popular/referrers` (shows where traffic comes from)
4. Check PR statuses: `gh search prs --author=bzsasson --state=open "screaming-frog"` and `--state=merged`
5. Append a dated metrics snapshot to `marketing/LOG.md`
6. Compare with previous snapshots to show trend

### Files in /marketing/
- `TRACKER.md` — master plan with checkboxes (phases 1-3)
- `LOG.md` — timestamped activity log + metrics snapshots
- `content/` — ready-to-post content for each platform

## Repo owner
Boaz Sasson (bzsasson on GitHub). All commits should be authored by Boaz only — no Claude co-author lines.
