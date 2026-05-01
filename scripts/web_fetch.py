#!/usr/bin/env python3
"""web-fetch: fetch a URL, save the body to a temp dir, print the path.

Single-file Python 3 stdlib. Shells out to `curl` (preferred, OS-neutral) or
falls back to `urllib.request` when curl is unavailable.

USAGE
    web-fetch URL [--format markdown|text|html|raw]
                  [--timeout SEC]
                  [--output-dir DIR]
                  [--print-content]
                  [--quiet|--verbose]

EXIT CODES
    0  Fetched successfully.
    1  Argument error.
    2  Fetch failed (network, HTTP >= 400, oversized, timeout).

OUTPUT
    Stdout : path to the rendered file, then path to result.json. Pipe-friendly.
    Stderr : trace lines prefixed [web-fetch].
    Files  : <output-dir>/result.<ext>     rendered content in requested format
             <output-dir>/raw.<ext>        original response body
             <output-dir>/result.json      content + _meta envelope
             <output-dir>/trace.json       _meta only

The skill writes content to disk and returns paths so callers can pipe through
rg / jq / awk / head instead of pulling 50KB of HTML into the conversation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html as _html
import html.parser
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from typing import Any

VERSION = "0.1.0"

DEFAULT_TIMEOUT_SECONDS = 30
MAX_TIMEOUT_SECONDS = 120
MAX_RESPONSE_SIZE_BYTES = 5 * 1024 * 1024

BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
)
HONEST_USER_AGENT = "web-fetch/" + VERSION

VERBOSE = False
QUIET = False


def trace(msg: str) -> None:
    if QUIET:
        return
    sys.stderr.write(f"[web-fetch] {msg}\n")
    sys.stderr.flush()


def vtrace(msg: str) -> None:
    if VERBOSE and not QUIET:
        sys.stderr.write(f"[web-fetch] {msg}\n")
        sys.stderr.flush()


def have_curl() -> bool:
    return shutil.which("curl") is not None


class HttpResp:
    __slots__ = ("status", "body", "content_type", "duration_ms", "final_url",
                 "cf_challenge")

    def __init__(self, status: int, body: bytes, content_type: str,
                 duration_ms: int, final_url: str, cf_challenge: bool):
        self.status = status
        self.body = body
        self.content_type = content_type
        self.duration_ms = duration_ms
        self.final_url = final_url
        self.cf_challenge = cf_challenge


_CF_MARKERS = (b"<title>Just a moment...</title>", b"cf-mitigated", b"cf-chl-bypass",
               b"Attention Required! | Cloudflare", b"challenge-platform")


def _detect_cf_challenge(status: int, body: bytes) -> bool:
    if status != 403 and status != 503:
        return False
    head = body[:4096].lower()
    return any(m.lower() in head for m in _CF_MARKERS)


def http_get(
    url: str,
    *,
    headers: dict[str, str],
    timeout: int,
    use_curl: bool,
) -> HttpResp:
    """GET with redirects + bounded timeout. Captures Content-Type and Cloudflare hints."""
    started = time.monotonic()
    if use_curl:
        marker = b"\n__WEBFETCH_TRAILER__\t"
        cmd = [
            "curl", "-sS", "-L",
            "-w", "\n__WEBFETCH_TRAILER__\t%{http_code}\t%{url_effective}\t%{content_type}",
            "-o", "-",
            url,
            "--max-time", str(timeout),
            "--max-filesize", str(MAX_RESPONSE_SIZE_BYTES),
        ]
        for k, v in headers.items():
            cmd += ["-H", f"{k}: {v}"]
        proc = subprocess.run(cmd, capture_output=True, check=False)
        if proc.returncode != 0 and not proc.stdout:
            raise RuntimeError(
                f"curl exit {proc.returncode}: "
                f"{proc.stderr.decode('utf-8', errors='replace').strip()}"
            )
        out = proc.stdout
        split_at = out.rfind(marker)
        if split_at < 0:
            body_bytes, status, final_url, ct = out, 0, url, ""
        else:
            body_bytes = out[:split_at]
            tail = out[split_at + len(marker) :].decode("utf-8", errors="replace").strip()
            parts = tail.split("\t", 2)
            status = int(parts[0]) if parts and parts[0].isdigit() else 0
            final_url = parts[1] if len(parts) > 1 else url
            ct = parts[2] if len(parts) > 2 else ""
        cf = _detect_cf_challenge(status, body_bytes)
        duration_ms = int((time.monotonic() - started) * 1000)
        return HttpResp(status, body_bytes, ct, duration_ms, final_url, cf)

    req = urllib.request.Request(url, method="GET", headers=headers)
    final_url = url
    ct = ""
    body_bytes = b""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ct = resp.headers.get("Content-Type") or ""
            final_url = resp.url
            body_bytes = resp.read(MAX_RESPONSE_SIZE_BYTES + 1)
            if len(body_bytes) > MAX_RESPONSE_SIZE_BYTES:
                raise RuntimeError(f"response exceeds {MAX_RESPONSE_SIZE_BYTES} bytes")
            status = resp.status
    except urllib.error.HTTPError as e:
        body_bytes = e.read() if hasattr(e, "read") else b""
        status = e.code
        ct = e.headers.get("Content-Type", "") if e.headers else ""
    cf = _detect_cf_challenge(status, body_bytes)
    duration_ms = int((time.monotonic() - started) * 1000)
    return HttpResp(status, body_bytes, ct, duration_ms, final_url, cf)


def accept_for(fmt: str) -> str:
    if fmt == "html":
        return "text/html;q=1.0, application/xhtml+xml;q=0.9, text/plain;q=0.8, */*;q=0.1"
    if fmt == "markdown":
        return "text/markdown;q=1.0, text/html;q=0.9, text/plain;q=0.8, */*;q=0.1"
    return "text/plain;q=1.0, text/markdown;q=0.9, text/html;q=0.8, */*;q=0.1"


_HTML_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
                   "meta", "param", "source", "track", "wbr"}
_HTML_DROP_TAGS = {"script", "style", "noscript", "iframe", "object", "head", "title",
                   "svg", "canvas", "form", "button", "select", "textarea", "label"}


class _MarkdownExtractor(html.parser.HTMLParser):
    """Stdlib-only HTML to Markdown converter. Covers headings, paragraphs, links,
    lists, code/pre, emphasis, line breaks, blockquotes. Tables degrade to pipes."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0
        self.list_stack: list[str] = []
        self.in_pre = 0
        self.in_code = 0
        self.in_a: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _HTML_VOID_TAGS:
            if self.skip_depth:
                return
            if tag == "br":
                self.parts.append("\n")
            elif tag == "hr":
                self.parts.append("\n\n---\n\n")
            elif tag == "img":
                d = dict(attrs)
                alt = d.get("alt") or ""
                src = d.get("src") or ""
                if src:
                    self.parts.append(f"![{alt}]({src})")
            return
        if tag in _HTML_DROP_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "p":
            self.parts.append("\n\n")
        elif tag in ("ul", "ol"):
            self.list_stack.append(tag)
            self.parts.append("\n")
        elif tag == "li":
            indent = "  " * (len(self.list_stack) - 1) if self.list_stack else ""
            marker = "1." if self.list_stack and self.list_stack[-1] == "ol" else "-"
            self.parts.append(f"\n{indent}{marker} ")
        elif tag == "blockquote":
            self.parts.append("\n\n> ")
        elif tag == "pre":
            self.in_pre += 1
            self.parts.append("\n\n```\n")
        elif tag == "code":
            if not self.in_pre:
                self.in_code += 1
                self.parts.append("`")
        elif tag in ("strong", "b"):
            self.parts.append("**")
        elif tag in ("em", "i"):
            self.parts.append("*")
        elif tag == "a":
            self.in_a.append(dict(attrs).get("href"))
            self.parts.append("[")
        elif tag == "tr":
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _HTML_DROP_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
            self.parts.append("\n\n")
        elif tag in ("ul", "ol"):
            if self.list_stack:
                self.list_stack.pop()
            self.parts.append("\n")
        elif tag == "pre":
            if self.in_pre:
                self.in_pre -= 1
            self.parts.append("\n```\n\n")
        elif tag == "code":
            if not self.in_pre and self.in_code:
                self.in_code -= 1
                self.parts.append("`")
        elif tag in ("strong", "b"):
            self.parts.append("**")
        elif tag in ("em", "i"):
            self.parts.append("*")
        elif tag == "a":
            href = self.in_a.pop() if self.in_a else None
            self.parts.append(f"]({href})" if href else "]")

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        self.parts.append(data)

    def output(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r" *\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def html_to_markdown(html_str: str) -> str:
    p = _MarkdownExtractor()
    try:
        p.feed(html_str)
        p.close()
    except Exception:
        return _html.unescape(re.sub(r"<[^>]+>", " ", html_str)).strip()
    return p.output()


def html_to_text(html_str: str) -> str:
    s = re.sub(r"<(script|style|noscript|iframe|object|embed)\b[^>]*>[\s\S]*?</\1>", "", html_str, flags=re.I)
    s = re.sub(r"</?(p|div|br|li|tr|h[1-6]|section|article|header|footer|nav|aside|main|blockquote|pre)\b[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = _html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ \t]+", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def render(body: bytes, content_type: str, fmt: str) -> str:
    raw = body.decode("utf-8", errors="replace")
    is_html = "text/html" in content_type.lower() or "application/xhtml" in content_type.lower()
    if fmt == "raw" or fmt == "html" or not is_html:
        return raw
    if fmt == "markdown":
        return html_to_markdown(raw)
    return html_to_text(raw)


def make_output_dir(explicit: str | None) -> pathlib.Path:
    if explicit:
        p = pathlib.Path(explicit).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p
    base = pathlib.Path(tempfile.gettempdir())
    run_id = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    p = base / f"web-fetch-{run_id}"
    p.mkdir(parents=True, exist_ok=True)
    return p


def fetch_with_cf_retry(
    url: str, *, fmt: str, timeout: int, use_curl: bool
) -> tuple[HttpResp, list[dict[str, Any]]]:
    """One real request with browser UA. If CF challenge, retry once with honest UA."""
    attempts: list[dict[str, Any]] = []
    headers = {
        "Accept": accept_for(fmt),
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": BROWSER_USER_AGENT,
    }
    trace(f"GET {url} (browser UA, timeout={timeout}s)")
    resp = http_get(url, headers=headers, timeout=timeout, use_curl=use_curl)
    attempts.append({
        "user_agent": "browser",
        "status": resp.status,
        "duration_ms": resp.duration_ms,
        "bytes": len(resp.body),
        "content_type": resp.content_type,
        "final_url": resp.final_url,
        "cf_challenge": resp.cf_challenge,
    })
    if resp.status == 403 and resp.cf_challenge:
        trace("Cloudflare challenge detected; retrying with honest UA")
        headers["User-Agent"] = HONEST_USER_AGENT
        resp = http_get(url, headers=headers, timeout=timeout, use_curl=use_curl)
        attempts.append({
            "user_agent": "honest",
            "status": resp.status,
            "duration_ms": resp.duration_ms,
            "bytes": len(resp.body),
            "content_type": resp.content_type,
            "final_url": resp.final_url,
            "cf_challenge": resp.cf_challenge,
        })
    return resp, attempts


def cmd_fetch(args: argparse.Namespace) -> int:
    if not (args.url.startswith("http://") or args.url.startswith("https://")):
        sys.exit("[web-fetch] URL must start with http:// or https://")

    timeout = min(args.timeout or DEFAULT_TIMEOUT_SECONDS, MAX_TIMEOUT_SECONDS)
    use_curl = True if args.use_curl else (False if args.use_urllib else have_curl())
    output_dir = make_output_dir(args.output_dir)

    started = time.monotonic()
    try:
        resp, attempts = fetch_with_cf_retry(
            args.url, fmt=args.format, timeout=timeout, use_curl=use_curl
        )
    except Exception as e:
        trace(f"FAIL: {e}")
        envelope = {
            "content": "",
            "_meta": {
                "version": VERSION,
                "url": args.url,
                "format": args.format,
                "ok": False,
                "error": str(e),
                "attempts": [],
                "duration_ms": int((time.monotonic() - started) * 1000),
                "output_dir": str(output_dir),
            },
        }
        (output_dir / "result.json").write_text(json.dumps(envelope, indent=2, ensure_ascii=False))
        (output_dir / "trace.json").write_text(json.dumps(envelope["_meta"], indent=2, ensure_ascii=False))
        sys.stdout.write(str(output_dir / "result.json") + "\n")
        return 2

    raw_ext = {"markdown": "html", "text": "html", "html": "html", "raw": "bin"}
    raw_path = output_dir / f"raw.{raw_ext[args.format]}"
    try:
        raw_path.write_bytes(resp.body)
    except Exception:
        pass

    ok = 200 <= resp.status < 400 and len(resp.body) > 0

    if not ok:
        snippet = resp.body[:500].decode("utf-8", errors="replace").replace("\n", " ")
        trace(f"HTTP {resp.status}: {snippet[:200]}")
        envelope = {
            "content": "",
            "_meta": {
                "version": VERSION,
                "url": args.url,
                "format": args.format,
                "ok": False,
                "http_status": resp.status,
                "content_type": resp.content_type,
                "final_url": resp.final_url,
                "error": snippet,
                "attempts": attempts,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "raw_path": str(raw_path),
                "output_dir": str(output_dir),
            },
        }
        (output_dir / "result.json").write_text(json.dumps(envelope, indent=2, ensure_ascii=False))
        (output_dir / "trace.json").write_text(json.dumps(envelope["_meta"], indent=2, ensure_ascii=False))
        sys.stdout.write(str(output_dir / "result.json") + "\n")
        return 2

    content = render(resp.body, resp.content_type, args.format)
    converted = "text/html" in resp.content_type.lower() and args.format in ("markdown", "text")

    ext = {"markdown": "md", "text": "txt", "html": "html", "raw": "txt"}[args.format]
    content_path = output_dir / f"result.{ext}"
    content_path.write_text(content)

    envelope = {
        "content": content,
        "_meta": {
            "version": VERSION,
            "url": args.url,
            "format": args.format,
            "ok": True,
            "http_status": resp.status,
            "content_type": resp.content_type,
            "final_url": resp.final_url,
            "converted": converted,
            "bytes": len(content.encode("utf-8")),
            "raw_bytes": len(resp.body),
            "attempts": attempts,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "started_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "raw_path": str(raw_path),
            "content_path": str(content_path),
            "output_dir": str(output_dir),
            "transport": "curl" if use_curl else "urllib",
        },
    }
    (output_dir / "result.json").write_text(json.dumps(envelope, indent=2, ensure_ascii=False))
    (output_dir / "trace.json").write_text(json.dumps(envelope["_meta"], indent=2, ensure_ascii=False))
    trace(
        f"OK {resp.status} {resp.content_type} "
        f"{len(content.encode('utf-8'))} bytes in {envelope['_meta']['duration_ms']}ms"
    )

    if args.print_path == "json":
        sys.stdout.write(str(output_dir / "result.json") + "\n")
    elif args.print_path == "content":
        sys.stdout.write(str(content_path) + "\n")
    else:
        sys.stdout.write(str(content_path) + "\n")
        sys.stdout.write(str(output_dir / "result.json") + "\n")

    if args.print_content:
        sys.stdout.write(content)
        if not content.endswith("\n"):
            sys.stdout.write("\n")

    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="web-fetch",
        description="Fetch a URL, save the body to a temp dir, print the path.",
    )
    p.add_argument("url", help="URL to fetch (must start with http:// or https://).")
    p.add_argument("--format", choices=["markdown", "text", "html", "raw"], default="markdown",
                   help="Output format. HTML responses are converted when 'markdown' or 'text'. Default: markdown.")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS,
                   help=f"HTTP timeout in seconds. Capped at {MAX_TIMEOUT_SECONDS}. Default: {DEFAULT_TIMEOUT_SECONDS}.")
    p.add_argument("--output-dir", help="Output directory. Default: $TMPDIR/web-fetch-<runid>.")
    p.add_argument("--use-curl", action="store_true", help="Force curl as HTTP transport.")
    p.add_argument("--use-urllib", action="store_true", help="Force urllib as HTTP transport.")
    p.add_argument("--print-path", choices=["all", "content", "json"], default="all",
                   help="Stdout: 'all' (default) prints content path then json path, "
                        "'content' prints only content file, 'json' prints only result.json.")
    p.add_argument("--print-content", action="store_true",
                   help="Also write the fetched content to stdout after the path lines.")
    p.add_argument("--quiet", action="store_true", help="Suppress trace logs on stderr.")
    p.add_argument("--verbose", action="store_true", help="Verbose trace.")
    p.add_argument("--version", action="version", version=f"web-fetch {VERSION}")
    return p.parse_args()


def main() -> int:
    global VERBOSE, QUIET
    args = parse_args()
    VERBOSE = bool(args.verbose)
    QUIET = bool(args.quiet)
    return cmd_fetch(args)


if __name__ == "__main__":
    sys.exit(main())
