# Pipeline patterns

The whole reason `web-fetch` writes to a file is so you can pipe the path through standard Unix tools. This file has worked examples for the most common cases. Pick the closest match and adapt.

## POSIX (macOS / Linux / Git Bash / WSL)

### Capture paths into shell variables

```bash
# Two paths on stdout (default --print-path=all): content, then json
read -r CONTENT JSON < <(python3 web_fetch.py https://example.com --quiet | tr '\n' ' ')

# Or just the content path
CONTENT=$(python3 web_fetch.py https://example.com --print-path content --quiet)

# Or just the json envelope path
JSON=$(python3 web_fetch.py https://example.com --print-path json --quiet)
```

### Search inside the page

```bash
# Find lines mentioning a token
rg -in "TaskGroup" "$CONTENT"

# Lines + context
rg -B2 -A6 "asyncio.run" "$CONTENT"

# Word boundaries (avoid partial matches)
rg -inw "await" "$CONTENT" | head -20

# Multiple alternates
rg -in "deprecated|removed since" "$CONTENT"

# Count matches
rg -c "TaskGroup" "$CONTENT"

# Show only matched part (good for extracting URLs)
rg -o 'https?://[A-Za-z0-9./_-]+' "$CONTENT" | sort -u
```

### Section extraction (markdown)

```bash
# Everything between "## TaskGroup" and the next "## " heading
awk '/^## TaskGroup/{flag=1} /^## /{if(flag&&!/^## TaskGroup/)exit} flag' "$CONTENT"

# Same but tolerant of any heading level
awk '/^#+ TaskGroup/{flag=1; next} /^#+ /{if(flag)exit} flag' "$CONTENT"

# Just code blocks (fenced)
awk '/^```/{f=!f; next} f' "$CONTENT"

# Headings only (table of contents)
rg -n '^#{1,6} ' "$CONTENT"
```

### Inspect metadata via jq

```bash
# Where did we end up? (final URL after redirects)
jq -r '._meta.final_url' "$JSON"

# What MIME was returned?
jq -r '._meta.content_type' "$JSON"

# Was it converted from HTML?
jq -r '._meta.converted' "$JSON"

# How big is the rendered content vs raw?
jq -r '._meta | "rendered=\(.bytes) raw=\(.raw_bytes)"' "$JSON"

# Each attempt + status (helpful when CF retry fired)
jq -r '._meta.attempts[] | "\(.user_agent)\t\(.status)\t\(.duration_ms)ms\t\(.bytes)B"' "$JSON"

# Just the content (without the envelope)
jq -r '.content' "$JSON"
```

### Compose: fetch + filter + format

```bash
# Get all GitHub issue links from a project README
CONTENT=$(python3 web_fetch.py https://github.com/anthropics/anthropic-sdk-python --print-path content --quiet)
rg -o 'https://github.com/[^)]+/issues/[0-9]+' "$CONTENT" | sort -u

# Pull external links from a docs page (skip same-host)
CONTENT=$(python3 web_fetch.py https://docs.python.org/3/library/asyncio.html --print-path content --quiet)
rg -o 'https?://[^) ]+' "$CONTENT" | rg -v 'docs\.python\.org' | sort -u

# Diff rendered markdown vs raw HTML
diff <(rg -o 'https?://[^) ]+' "$CONTENT" | sort -u) \
     <(rg -o 'href="[^"]+"' "$JSON" | sort -u | head -50)
```

### Batch fetch many URLs in parallel

```bash
# urls.txt has one URL per line
xargs -n1 -P8 -I{} python3 web_fetch.py {} --print-path content --quiet < urls.txt > paths.txt

# Now grep across all of them at once
xargs cat < paths.txt | rg -in "deprecated"

# Or process each one independently
while read -r p; do
  echo "=== $p ==="
  rg -in "deprecated" "$p" | head -5
done < paths.txt
```

### Stable output dir for repeated runs

```bash
# Fetch into a known directory so subsequent runs overwrite
python3 web_fetch.py https://example.com --output-dir ./scratch/example-com --quiet
ls ./scratch/example-com/
```

This is useful when you want to track changes to a page over time (commit the directory and diff between versions).

### Stream the content directly

If you really do not want a temp file (just want the content on stdout):

```bash
# All output goes to stdout: paths first, then content
python3 web_fetch.py https://example.com --print-content --quiet

# Just the content, no path lines (use jq to read result.json)
JSON=$(python3 web_fetch.py https://example.com --print-path json --quiet)
jq -r '.content' "$JSON"
```

## Windows PowerShell

```powershell
# Default: two paths printed on stdout
$paths = python3 web_fetch.py https://example.com --quiet
$content = $paths[0]
$json = $paths[1]

# Or grab the content path directly
$content = python3 web_fetch.py https://example.com --print-path content --quiet

# Search inside the file
Select-String -Path $content -Pattern 'TaskGroup' -Context 2,6

# Inspect metadata (Windows has built-in JSON parsing)
Get-Content $json | ConvertFrom-Json | Select-Object -ExpandProperty _meta

# Get just the final URL
(Get-Content $json | ConvertFrom-Json)._meta.final_url
```

If you have `rg.exe` and `jq.exe` installed (via scoop / chocolatey / winget), all of the POSIX examples above also work in PowerShell with minor quoting differences:

```powershell
rg -in "TaskGroup" $content
jq -r '._meta.final_url' $json
```

## Anti-patterns

- **Reading the whole file when you only need one section.** Use `rg` first; quote the matching lines.
- **Re-fetching the same URL across follow-up turns.** Save `$CONTENT` between turns; the temp dir persists for the session.
- **Hardcoding paths from a previous run.** The `<runid>` changes. Pass `--output-dir` if you need a stable path.
- **Pasting the whole `result.md` into a chat reply.** Quote the relevant lines from `rg`. Mention the path.
