# web-fetch

LLM-neutral skill for fetching a URL and writing the body to a temp file so an agent can pipe the path through `rg` / `jq` / `awk` instead of dumping the whole page into the conversation.

Same shape as [`pi-webfetch`](https://github.com/code-yeongyu/pi-webfetch) and [`opencode/webfetch`](https://github.com/sst/opencode), packaged as a standalone skill that any Bash-capable agent (Claude Code, OpenCode, pi, hermes, openclaw) can load.

## Install

```bash
git clone https://github.com/code-yeongyu/web-fetch ~/.agents/skills/web-fetch
```

That is it. The script is single-file Python 3 stdlib; no `pip install` needed. `curl` is preferred but optional (urllib fallback).

### Symlink for active development

```bash
ln -s /path/to/your/clone ~/.agents/skills/web-fetch
```

### Other agents

- **Claude Code / OpenCode**: drop the directory under `~/.agents/skills/` and the skill auto-registers via the `name` + `description` in the frontmatter.
- **pi (`~/.senpi/agent`)**: not a `pi` extension - this is a skill, not a Tool extension. Pi consumes skills via `~/.agents/skills/` symlinks; see `~/.senpi/.pi/agent/skills/` for the convention.
- **Direct CLI use**: `python3 ~/.agents/skills/web-fetch/scripts/web_fetch.py <URL>`.

## Usage

```bash
# Default (markdown, auto-converted from HTML)
python3 scripts/web_fetch.py https://example.com

# Format options
python3 scripts/web_fetch.py https://example.com --format markdown
python3 scripts/web_fetch.py https://example.com --format text
python3 scripts/web_fetch.py https://example.com --format html
python3 scripts/web_fetch.py https://example.com --format raw

# Custom output dir, custom timeout
python3 scripts/web_fetch.py https://example.com --output-dir ./scratch --timeout 60

# Print only the content path (for piping)
python3 scripts/web_fetch.py https://example.com --print-path content

# Also write content to stdout
python3 scripts/web_fetch.py https://example.com --print-content
```

Stdout prints two paths by default: `result.<ext>` then `result.json`. The trace lives on stderr (suppress with `--quiet`).

See [SKILL.md](./SKILL.md) for the full agent-facing usage and [`references/pipelines.md`](./references/pipelines.md) for `rg` / `jq` / `awk` worked examples.

## Project layout

```
web-fetch/
├── SKILL.md                       agent-facing skill (loaded by Claude Code, OpenCode, pi, etc.)
├── README.md                      this file
├── LICENSE                        MIT
├── scripts/
│   └── web_fetch.py               single-file Python 3 stdlib script
├── references/
│   ├── pipelines-posix.md         rg / jq / awk patterns for macOS / Linux / WSL / Git Bash
│   ├── pipelines-windows.md       PowerShell + cmd equivalents
│   ├── compat.md                  per-OS support matrix, Python/curl version floor
│   └── troubleshooting.md         403 / 429 / Cloudflare / TLS gotchas
├── tests/
│   ├── smoke.sh                   POSIX self-test (fetches example.com)
│   └── smoke.ps1                  PowerShell self-test (Windows CI)
└── .github/workflows/ci.yml       matrix CI: macos/ubuntu/windows x py 3.9-3.13
```

## What it does

1. One curl GET (or urllib if curl missing).
2. If response is 403/503 with Cloudflare challenge markers → retry once with an honest UA.
3. If `Content-Type: text/html` and `--format` is markdown/text → convert via stdlib `html.parser`.
4. Write `result.<ext>` (rendered), `raw.<ext>` (original body), `result.json` (envelope), `trace.json` (metadata only).
5. Print paths on stdout.

## What it does NOT do

- No multi-provider fallback chains. (Use a different tool if curl cannot reach the site.)
- No JavaScript rendering. (SPAs need a real browser; use `playwright` / `firecrawl` outside this skill.)
- No authentication. (No cookies, no API keys; this is a public-content fetcher.)
- No retries beyond the one Cloudflare retry. (If the site is down, it is down.)
- No content caching across runs. (Each call writes a fresh `<runid>` directory; pass `--output-dir` for stable paths.)

The simplicity is the point. If you need providers / fallback / load-balancing, that belongs in a search skill, not a fetch skill.

## Limits

- 5 MB response size cap.
- 120 second timeout cap.
- Public HTTP/HTTPS only.

## Requirements

- Python ≥ 3.9 (stdlib only).
- `curl` (optional but recommended; auto-detected). Windows 10 1803+ ships `curl.exe`.

For older systems (RHEL 7, Ubuntu 18.04, etc.) and Windows-specific setup, see [`references/compat.md`](./references/compat.md).

## Testing

```bash
bash tests/smoke.sh        # POSIX (macOS / Linux / WSL / Git Bash)
pwsh tests/smoke.ps1       # Windows (PowerShell 5.1+ or 7+)
```

CI runs the matrix on every push: `{macos-latest, ubuntu-latest, ubuntu-22.04, windows-latest}` x `{Python 3.9, 3.10, 3.11, 3.12, 3.13}` plus a syntax-floor check on Python 3.9 and 3.10.

## License

[MIT](./LICENSE).

## Acknowledgments

- [`pi-webfetch`](https://github.com/code-yeongyu/pi-webfetch) - direct ancestor for the URL/format/timeout shape.
- [`opencode/webfetch`](https://github.com/sst/opencode/blob/main/packages/opencode/src/tool/webfetch.ts) - reference for the Cloudflare retry pattern.
- [Anthropic skills](https://docs.anthropic.com/en/docs/claude-code/skills) - the `SKILL.md` + `references/` packaging convention.
