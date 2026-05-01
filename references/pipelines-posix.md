# Pipeline patterns - POSIX (macOS / Linux / WSL / Git Bash)

This file covers Bash / zsh on macOS, modern Linux, WSL, and Git Bash on Windows. For native Windows PowerShell, see `pipelines-windows.md`.

## Capture paths into shell variables

```bash
# Two paths on stdout (default --print-path=all): content, then json
read -r CONTENT JSON < <(python3 web_fetch.py https://example.com --quiet | tr '\n' ' ')

# Or just the content path
CONTENT=$(python3 web_fetch.py https://example.com --print-path content --quiet)

# Or just the json envelope path
JSON=$(python3 web_fetch.py https://example.com --print-path json --quiet)
```

## Search inside the page

```bash
rg -in "TaskGroup" "$CONTENT"                    # match (case-insensitive, with line numbers)
rg -B2 -A6 "asyncio.run" "$CONTENT"              # context lines
rg -inw "await" "$CONTENT" | head -20            # word boundary
rg -in "deprecated|removed since" "$CONTENT"     # alternates
rg -c "TaskGroup" "$CONTENT"                     # count matches
rg -o 'https?://[A-Za-z0-9./_-]+' "$CONTENT" | sort -u   # extract URLs
```

If `rg` is not installed, fall back to `grep -RiIn`. The flags differ slightly:

```bash
grep -in "TaskGroup" "$CONTENT"
grep -B2 -A6 "asyncio.run" "$CONTENT"
grep -inE "deprecated|removed since" "$CONTENT"
```

## Section extraction (markdown)

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

## Inspect metadata via jq

```bash
jq -r '._meta.final_url' "$JSON"
jq -r '._meta.content_type' "$JSON"
jq -r '._meta.converted' "$JSON"
jq -r '._meta | "rendered=\(.bytes) raw=\(.raw_bytes)"' "$JSON"
jq -r '._meta.attempts[] | "\(.user_agent)\t\(.status)\t\(.duration_ms)ms\t\(.bytes)B"' "$JSON"
jq -r '.content' "$JSON"
```

If `jq` is not installed:

```bash
python3 -c "import json,sys; print(json.load(open('$JSON'))['_meta']['final_url'])"
```

## Compose - fetch + filter + format

```bash
# All GitHub issue links from a project README
CONTENT=$(python3 web_fetch.py https://github.com/anthropics/anthropic-sdk-python --print-path content --quiet)
rg -o 'https://github.com/[^)]+/issues/[0-9]+' "$CONTENT" | sort -u

# External links from a docs page (skip same-host)
CONTENT=$(python3 web_fetch.py https://docs.python.org/3/library/asyncio.html --print-path content --quiet)
rg -o 'https?://[^) ]+' "$CONTENT" | rg -v 'docs\.python\.org' | sort -u
```

## Batch fetch many URLs in parallel

```bash
# urls.txt has one URL per line
xargs -n1 -P8 -I{} python3 web_fetch.py {} --print-path content --quiet < urls.txt > paths.txt

# Grep across all of them at once
xargs cat < paths.txt | rg -in "deprecated"

# Or process each one independently
while read -r p; do
  echo "=== $p ==="
  rg -in "deprecated" "$p" | head -5
done < paths.txt
```

`xargs -P` is GNU/BSD-portable. On macOS, default `xargs` works; on very old Linux without `-P`, fall back to a `&`/`wait` loop:

```bash
while read -r url; do
  python3 web_fetch.py "$url" --print-path content --quiet &
done < urls.txt
wait
```

## Stable output dir for repeated runs

```bash
python3 web_fetch.py https://example.com --output-dir ./scratch/example-com --quiet
ls ./scratch/example-com/
```

Useful when you want to track changes to a page over time (commit the directory and diff between versions).

## Stream the content directly (no temp file path)

```bash
# All output to stdout: paths first, then content
python3 web_fetch.py https://example.com --print-content --quiet

# Just the content, no path lines (use jq to read result.json)
JSON=$(python3 web_fetch.py https://example.com --print-path json --quiet)
jq -r '.content' "$JSON"
```

## Anti-patterns

- **Reading the whole file when you only need one section** - use `rg` first; quote the matching lines.
- **Re-fetching the same URL across follow-up turns** - save `$CONTENT` between turns; the temp dir persists for the session.
- **Hardcoding paths from a previous run** - the `<runid>` changes per call. Pass `--output-dir` if you need a stable path.
- **Pasting the whole `result.md` into a chat reply** - quote the relevant lines from `rg` output. Mention the path so the user can grep it themselves.
