---
name: web-fetch
description: "Fetch a URL and save the body to a temp file so you can pipe it through rg / jq / awk instead of dumping the whole page into the conversation. Use this whenever a user gives you a URL to read - articles, docs, PRs, gists, README files, blog posts, anything HTTP. Returns a path on disk; the agent then greps the path for the relevant section and quotes only what matters. Strongly preferred over the built-in webfetch tool when (a) the page is more than a few KB, (b) the user wants to find a specific phrase / table / code block on the page, (c) you need to keep the long page out of context, or (d) you want to inspect raw HTML alongside rendered markdown. Triggers: 'fetch', 'fetch this URL', 'fetch and save', 'fetch the page', 'pull this', 'grab this article', 'read this URL', 'read the docs at', 'mirror this page', 'page is too long', 'save the page so I can grep it', 'put it on disk so I can rg', 'cache this URL'."
---

# web-fetch

Fetch a URL, write the body to `$TMPDIR/web-fetch-<runid>/`, print the path. Pipe the path through `rg` / `jq` / `awk` to surgically extract what you need.

## Why this skill exists

The built-in `webfetch` tool dumps the whole rendered page into the conversation. For anything bigger than a few KB that drowns the context window. The fix is dead simple: **write the page to disk, then grep it**.

That is all this skill does. One curl call, one Cloudflare-aware retry, HTML → Markdown via stdlib, save to a temp dir, print the path. No providers, no fallback chain, no fancy machinery. The same shape as `pi-webfetch` and `opencode/webfetch`, but as a standalone skill that works from any agent (Claude Code, OpenCode, pi, hermes, openclaw, whatever speaks Bash).

## When to use it

Trigger this skill any time the user hands you a URL and the goal is to read its content. Examples:

- "Fetch <https://docs.python.org/3/library/asyncio.html> and tell me about TaskGroup."
- "Read the README at <https://github.com/anthropics/anthropic-sdk-python>."
- "What does this article say about <topic>? <URL>"
- "Pull <PR url>, what's the key change?"
- "Fetch the page and pull out only the deprecated section."

If the URL is `https://example.com` and you only need 3 lines, the built-in tool is fine. Use this skill when the page is **non-trivially large** or you want to **filter before reading**.

## How to invoke it

The script is at `scripts/web_fetch.py`. It needs `python3` (3.9+) and ideally `curl` (auto-detected; `urllib` fallback works too).

### Basic fetch (markdown is default)

```bash
python3 <skill_dir>/scripts/web_fetch.py https://docs.python.org/3/library/asyncio.html
```

Stdout prints two lines:

```
/tmp/web-fetch-20260501-171120-abc123/result.md
/tmp/web-fetch-20260501-171120-abc123/result.json
```

`result.md` is the converted markdown. `result.json` is the same content plus a `_meta` envelope.

### Pick format

```bash
python3 web_fetch.py https://example.com --format markdown   # default; HTML auto-converted
python3 web_fetch.py https://example.com --format text       # tags stripped, entities decoded
python3 web_fetch.py https://example.com --format html       # original HTML untouched
python3 web_fetch.py https://example.com --format raw        # bytes-as-they-came (no conversion)
```

### Other flags

| Flag | Default | Purpose |
|---|---|---|
| `--timeout SEC` | 30 (cap 120) | Per-request timeout |
| `--output-dir PATH` | `$TMPDIR/web-fetch-<runid>` | Custom output dir for stable paths |
| `--print-path {all,content,json}` | `all` | What to print on stdout |
| `--print-content` | off | Also dump rendered content to stdout (for direct piping) |
| `--use-curl` / `--use-urllib` | auto | Force the HTTP transport |
| `--quiet` / `--verbose` | off | Trace verbosity |

## The pipe-and-grep pattern

This is the whole point. Resist the temptation to read the entire `result.md`. Use the path:

```bash
# Capture the content path
CONTENT=$(python3 web_fetch.py https://docs.python.org/3/library/asyncio.html --print-path content --quiet)

# Find the relevant section
rg -n "TaskGroup" "$CONTENT" | head -20

# Get N lines of context around a match
rg -B2 -A8 "asyncio.run" "$CONTENT" | head -40

# Multiple keywords
rg -in "deprecated|removed|since 3\.1[0-9]" "$CONTENT"

# Grab specific markdown sections (## or ### headings)
awk '/^## TaskGroup/,/^## /' "$CONTENT"
```

For headers / metadata extraction:

```bash
JSON=$(python3 web_fetch.py https://example.com --print-path json --quiet)
jq -r '._meta.final_url, ._meta.content_type, ._meta.bytes' "$JSON"
jq -r '._meta.attempts[] | "\(.user_agent): \(.status) (\(.duration_ms)ms)"' "$JSON"
```

For Windows PowerShell, see `references/pipelines-windows.md`.

## What gets written

```
$TMPDIR/web-fetch-<runid>/
├── result.md          rendered markdown (or .txt / .html depending on --format)
├── result.json        { content, _meta }
├── trace.json         _meta only (faster to inspect)
└── raw.html           original response body (or raw.bin for non-text)
```

Useful when:

- You want to compare rendered markdown against raw HTML (`diff result.md raw.html`).
- You want to keep the raw bytes around for forensic / replay use.
- You want the structured `_meta` separate from the content for cheap inspection.

## The `_meta` envelope

Every successful fetch produces this metadata:

```json
{
  "version": "0.1.0",
  "url": "https://docs.python.org/3/library/asyncio.html",
  "format": "markdown",
  "ok": true,
  "http_status": 200,
  "content_type": "text/html",
  "final_url": "https://docs.python.org/3/library/asyncio.html",
  "converted": true,
  "bytes": 41023,
  "raw_bytes": 198541,
  "attempts": [
    {"user_agent": "browser", "status": 200, "duration_ms": 187, "bytes": 198541,
     "content_type": "text/html", "final_url": "...", "cf_challenge": false}
  ],
  "duration_ms": 199,
  "started_at": "2026-05-01T08:11:20.045449+00:00",
  "raw_path": "/tmp/.../raw.html",
  "content_path": "/tmp/.../result.md",
  "output_dir": "/tmp/.../",
  "transport": "curl"
}
```

`attempts[]` shows the actual HTTP calls. If a Cloudflare challenge fired, you will see two entries (`browser` then `honest`). If you need to debug a fetch that "looks weird," dump this trace.

## Cloudflare retry (built-in)

Some sites return HTTP 403 with a Cloudflare challenge page when called with a browser-like UA but a non-browser TLS fingerprint. The skill detects this case (status 403 or 503 plus body markers like `<title>Just a moment...</title>` or `cf-mitigated`) and retries once with a plain `web-fetch/<version>` UA. Some operators allow honest UAs through. This is the same trick `pi-webfetch` and `opencode/webfetch` use.

If both attempts fail, the script exits with code 2 and the trace records both attempts so you can see exactly why.

## Limits

- **5 MB response cap.** Anything larger is rejected (curl uses `--max-filesize`; urllib reads N+1 then aborts).
- **120 second timeout cap.** `--timeout` larger than this is silently clamped.
- **Read-only.** This skill never modifies remote state; all calls are GET.
- **Public HTTP/HTTPS only.** No file://, no localhost shortcuts, no credentials in the URL.
- **No JS rendering.** If the page needs a real browser to populate content, you will get the unhydrated shell. For SPAs / aggressively dynamic content, use a headless-browser tool (`playwright`, `firecrawl`, etc.) outside this skill.

## Key invariants (do not break)

- **Content lives on disk, not in the conversation.** Quote what is relevant from the file. Never paste a full fetched body into your response unless the user explicitly asked for the full content.
- **Always mention the path.** When you tell the user "I fetched X", also mention where it is on disk so they can grep it themselves.
- **Pipe before reading.** When the user asks a specific question about the page, run `rg` / `jq` / `awk` against the saved path and quote only matching lines. Do not pre-load the entire file.
- **Trace is machine-readable.** If a fetch fails, surface the per-attempt error from `trace.json`, do not blindly retry the same URL with the same args.

## More

- `references/pipelines-posix.md` - rg/jq/awk worked examples for macOS / Linux / WSL / Git Bash.
- `references/pipelines-windows.md` - PowerShell + cmd equivalents.
- `references/compat.md` - per-OS support matrix, Python/curl version floor, Windows / WSL / Alpine / RHEL 7 setup.
- `references/troubleshooting.md` - 403 / 429 / Cloudflare / TLS / proxy gotchas and how to read the trace.
- `README.md` - install, packaging, registration into pi/senpi/.agents/skills/, project structure.
