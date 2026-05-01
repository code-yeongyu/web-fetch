#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
WEB_FETCH="python3 $SKILL_DIR/scripts/web_fetch.py"

OUTPUT_DIR="$(mktemp -d -t web-fetch-smoke-XXXXXX)"
trap 'rm -rf "$OUTPUT_DIR"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

$WEB_FETCH --version | grep -q "web-fetch" || fail "--version output missing"
pass "--version"

$WEB_FETCH https://example.com --output-dir "$OUTPUT_DIR/run1" --quiet >/dev/null
[ -f "$OUTPUT_DIR/run1/result.md" ]   || fail "result.md missing"
[ -f "$OUTPUT_DIR/run1/result.json" ] || fail "result.json missing"
[ -f "$OUTPUT_DIR/run1/trace.json" ]  || fail "trace.json missing"
[ -f "$OUTPUT_DIR/run1/raw.html" ]    || fail "raw.html missing"
grep -q "# Example Domain" "$OUTPUT_DIR/run1/result.md" || fail "markdown conversion missing heading"
grep -q "Learn more"        "$OUTPUT_DIR/run1/result.md" || fail "markdown conversion missing link text"
pass "fetch markdown writes all expected files"

python3 - <<PY
import json
m = json.load(open("$OUTPUT_DIR/run1/result.json"))["_meta"]
assert m["ok"] is True, "ok should be True"
assert m["http_status"] == 200, f"http_status was {m['http_status']}"
assert m["converted"] is True, "should be marked converted"
assert m["bytes"] > 0, "rendered bytes should be > 0"
assert m["raw_bytes"] > 0, "raw bytes should be > 0"
assert m["transport"] in ("curl", "urllib"), "transport must be set"
assert isinstance(m["attempts"], list) and len(m["attempts"]) >= 1, "attempts missing"
PY
pass "envelope shape"

$WEB_FETCH https://example.com --format text --output-dir "$OUTPUT_DIR/run2" --quiet >/dev/null
[ -f "$OUTPUT_DIR/run2/result.txt" ] || fail "result.txt missing for text format"
grep -q "Example Domain" "$OUTPUT_DIR/run2/result.txt" || fail "text format missing content"
! grep -q "<html" "$OUTPUT_DIR/run2/result.txt" || fail "text format leaked HTML"
pass "format=text strips tags"

$WEB_FETCH https://example.com --format html --output-dir "$OUTPUT_DIR/run3" --quiet >/dev/null
[ -f "$OUTPUT_DIR/run3/result.html" ] || fail "result.html missing for html format"
grep -q "<html" "$OUTPUT_DIR/run3/result.html" || fail "html format stripped tags"
pass "format=html preserves tags"

if $WEB_FETCH ftp://example.com --quiet 2>/dev/null; then
  fail "ftp:// URL should have errored"
fi
pass "non-http(s) scheme rejected"

LINES=$($WEB_FETCH https://example.com --print-path content --output-dir "$OUTPUT_DIR/run4" --quiet | wc -l)
[ "$LINES" -eq 1 ] || fail "--print-path content should print exactly 1 line, got $LINES"
pass "--print-path content prints one line"

LINES=$($WEB_FETCH https://example.com --print-path json --output-dir "$OUTPUT_DIR/run5" --quiet | wc -l)
[ "$LINES" -eq 1 ] || fail "--print-path json should print exactly 1 line, got $LINES"
pass "--print-path json prints one line"

$WEB_FETCH https://example.com --use-urllib --output-dir "$OUTPUT_DIR/run6" --quiet >/dev/null
grep -q "Example Domain" "$OUTPUT_DIR/run6/result.md" || fail "urllib fallback failed"
python3 -c "
import json
m = json.load(open('$OUTPUT_DIR/run6/result.json'))['_meta']
assert m['transport'] == 'urllib', f'expected urllib transport, got {m[\"transport\"]}'
"
pass "urllib transport"

echo ""
echo "all smoke tests passed"
