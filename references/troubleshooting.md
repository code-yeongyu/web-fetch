# Troubleshooting

When a fetch behaves badly, the answer almost always lives in `trace.json`. This file walks through the most common failure modes and how to recognize them in the trace.

## Read the trace first

```bash
JSON=$(python3 web_fetch.py <URL> --print-path json --quiet)
jq . "$JSON" | less
```

The fields that matter:

| Field | What it tells you |
|---|---|
| `_meta.ok` | Top-line success flag. False means content is empty. |
| `_meta.http_status` | The HTTP status of the **final** request (after redirects + CF retry). |
| `_meta.attempts[]` | Every individual HTTP call. Length 1 = clean run. Length 2 = CF retry fired. |
| `_meta.attempts[].cf_challenge` | True if that attempt hit a Cloudflare challenge page. |
| `_meta.final_url` | Where you actually ended up. If different from the requested URL, you got redirected. |
| `_meta.content_type` | The MIME the server returned. If empty/wrong, conversion may have skipped. |
| `_meta.converted` | True if HTML was converted to markdown/text; false means content is the raw body. |
| `_meta.error` | Snippet of the response body when status >= 400. |

## Symptom tree

### `result.md` exists but is empty

Look at `_meta.bytes` (rendered) vs `_meta.raw_bytes` (response body).

- `raw_bytes > 0`, `bytes == 0` → HTML→markdown conversion produced nothing. Usually means the response was wrapped in dropped tags (`<head>`, `<script>`, etc.) or the page is mostly JS-injected and the markup is empty. Try `--format html` or `--format raw` to see what actually came back.
- `raw_bytes == 0` → the server returned 200 with an empty body. Common with API endpoints that return 204 / empty 200.

### HTTP 403 with one attempt

```json
"attempts": [{"user_agent": "browser", "status": 403, "cf_challenge": false, ...}]
```

The site detected automated traffic but it was not Cloudflare's branded challenge. Possible causes:

- Custom WAF rule (Akamai, AWS WAF, Imperva).
- Bot scoring on the User-Agent + TLS fingerprint combo.
- Rate limiting (often returns 403 instead of 429).

Workarounds:

- Add a referrer: this script does not send `Referer` by default. The site may require it. Use `--use-curl` and run a manual `curl -H 'Referer: ...'` to confirm.
- Use a real browser (`playwright`, `firecrawl`) outside this skill.

### HTTP 403 with two attempts (CF retry fired but failed)

```json
"attempts": [
  {"user_agent": "browser", "status": 403, "cf_challenge": true, ...},
  {"user_agent": "honest", "status": 403, "cf_challenge": true, ...}
]
```

The site is gating with the JS challenge that requires a real browser to solve. There is no curl workaround. Move to a headless-browser tool.

### HTTP 429 (rate limited)

The trace will show `attempts[0].status == 429`. Check the response body for retry hints:

```bash
jq -r '._meta.error' "$JSON"
# or look at the raw response
cat $(jq -r '._meta.raw_path' "$JSON")
```

Many APIs include `Retry-After`. We do not auto-honor it because this skill is "fetch once and report"; back off in the calling agent and retry later.

### "curl exit 28" or "curl exit 56"

Network-level errors before any HTTP response.

| curl exit | Meaning |
|---|---|
| 6 | DNS resolution failed. Check the hostname. |
| 7 | Connection refused. Service is down or wrong port. |
| 22 (with `-f`) | HTTP error. Not used here, but if you see it manually, check status. |
| 28 | Operation timed out. Bump `--timeout`. |
| 35 | SSL connect error. TLS handshake failed. Often means the server has an outdated TLS stack. |
| 51 | Server SSL certificate is invalid (CN mismatch, expired, etc.). |
| 52 | Server replied with empty data. |
| 56 | Failure receiving network data mid-stream. Bad network or server killed connection. |
| 60 | SSL CA bundle problem. macOS sometimes hits this. |

For 60 specifically: check that `curl --version` shows a recent TLS backend. On macOS, system curl uses Secure Transport which sometimes lags. Try Homebrew curl instead.

### "response exceeds 5242880 bytes" (urllib) or curl `--max-filesize` rejection

The page is bigger than 5 MB. Three options:

1. The URL is wrong (you are downloading a tarball when you wanted a docs page). Double-check.
2. Use `--format raw` and pipe to a file directly:
   ```bash
   curl -sSL <URL> > /tmp/big-file.html
   # then process with rg / jq / etc. directly
   ```
3. Edit `MAX_RESPONSE_SIZE_BYTES` in the script. The cap exists to keep accidental binaries out of `$TMPDIR`; if you legitimately need bigger files, raise it.

### Markdown conversion is ugly / lossy

The stdlib HTML→markdown converter is intentionally simple. It covers headings, paragraphs, links, lists, code/pre, emphasis, blockquotes. It does NOT handle:

- Nested tables (degraded to `|` separators with no row headers).
- `<details>` / `<summary>` (treated as plain text).
- MathML, KaTeX, complex `<svg>` (stripped).
- CSS-driven content (`::before` / `::after` text, JS-injected DOM).

If conversion quality matters more than zero dependencies:

- Use `--format html` and feed the raw HTML to `pandoc -f html -t markdown` if pandoc is installed.
- Or use `--format text` for a flatter strip that may preserve more semantic content.

### Content type was JSON or XML, not HTML

When the server returns `application/json` or `application/xml`, the script does NOT convert. You get the raw bytes in `result.md` (the file extension is misleading; it is whatever was in the body). Use:

```bash
jq . "$CONTENT"          # JSON
xmllint --format "$CONTENT"  # XML, if libxml2 is installed
```

Or change to `--format raw` to skip the markdown filename suffix:

```bash
python3 web_fetch.py https://api.example.com/data.json --format raw
# writes to result.txt with raw bytes, no conversion attempted
```

### Redirect went somewhere unexpected

```bash
jq -r '._meta.final_url' "$JSON"
```

If `final_url` is different from the URL you passed, the server redirected. Check:

- Was it HTTPS upgrade? (`http://` → `https://` is normal.)
- Is the final host the same domain? (Cross-domain redirects can indicate hijacking or an intermediary auth gate.)
- Is the path different? (Some sites redirect `/foo` to `/foo/` or to a localized version like `/en/foo`.)

If the redirect is wrong, fetch the canonical URL directly.

### Two attempts, second one is 200 (CF retry succeeded)

```json
"attempts": [
  {"user_agent": "browser", "status": 403, "cf_challenge": true, ...},
  {"user_agent": "honest", "status": 200, "cf_challenge": false, ...}
]
```

Working as designed. The site allows the honest `web-fetch/<version>` UA through. No action needed; the rendered content uses the second attempt's body.

### `transport: "urllib"` instead of `curl`

The script auto-detected that `curl` is not on `PATH`. To verify:

```bash
which curl   # or: command -v curl
```

Install curl (usually already there on macOS / Linux; Windows 10 1803+ has `curl.exe`). Or force urllib explicitly:

```bash
python3 web_fetch.py <URL> --use-urllib
```

The behavior is the same; curl is just preferred for consistent TLS / proxy handling.

## When the skill is the wrong tool

Move to a different tool when:

- **JS-rendered SPA**: the markup is mostly empty until a bundle runs. Use `playwright` or a service like `firecrawl` / `scrapingbee` that renders.
- **Authenticated content**: this skill never sends cookies or auth. Wire your auth into a different tool (or accept that it cannot be fetched).
- **Bulk crawling**: 50+ URLs in tight sequence will rate-limit you. Use a real crawler (`scrapy`, `crawlee`).
- **Binary downloads**: tarballs, zips, PDFs, images. Use plain `curl -O` and process the file directly.
