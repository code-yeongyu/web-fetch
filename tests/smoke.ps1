#Requires -Version 5.1
$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$SkillDir  = Split-Path -Parent $ScriptDir
$Script    = Join-Path $SkillDir 'scripts/web_fetch.py'
$Python    = if (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { 'python' }

$Output    = Join-Path $env:TEMP ("web-fetch-smoke-" + [guid]::NewGuid().ToString('N').Substring(0,8))
New-Item -ItemType Directory -Path $Output -Force | Out-Null

function Pass([string]$msg) { Write-Host "PASS: $msg" }
function Fail([string]$msg) { Write-Host "FAIL: $msg" -ForegroundColor Red; Remove-Item -Recurse -Force $Output; exit 1 }

try {
    $version = & $Python $Script --version 2>&1
    if ($version -notmatch 'web-fetch') { Fail '--version output missing' }
    Pass '--version'

    $run1 = Join-Path $Output 'run1'
    & $Python $Script https://example.com --output-dir $run1 --quiet | Out-Null
    foreach ($f in 'result.md','result.json','trace.json','raw.html') {
        if (-not (Test-Path (Join-Path $run1 $f))) { Fail "$f missing" }
    }
    $md = Get-Content (Join-Path $run1 'result.md') -Raw
    if ($md -notmatch '# Example Domain') { Fail 'markdown missing heading' }
    if ($md -notmatch 'Learn more')        { Fail 'markdown missing link text' }
    Pass 'fetch markdown writes all expected files'

    $meta = (Get-Content (Join-Path $run1 'result.json') -Raw | ConvertFrom-Json)._meta
    if (-not $meta.ok)                              { Fail 'ok should be True' }
    if ($meta.http_status -ne 200)                  { Fail "http_status was $($meta.http_status)" }
    if (-not $meta.converted)                       { Fail 'should be marked converted' }
    if ($meta.bytes -le 0)                          { Fail 'rendered bytes should be > 0' }
    if ($meta.raw_bytes -le 0)                      { Fail 'raw bytes should be > 0' }
    if ($meta.transport -notin 'curl','urllib')     { Fail "unexpected transport: $($meta.transport)" }
    if ($meta.attempts.Count -lt 1)                 { Fail 'attempts missing' }
    Pass 'envelope shape'

    $run2 = Join-Path $Output 'run2'
    & $Python $Script https://example.com --format text --output-dir $run2 --quiet | Out-Null
    if (-not (Test-Path (Join-Path $run2 'result.txt'))) { Fail 'result.txt missing' }
    $txt = Get-Content (Join-Path $run2 'result.txt') -Raw
    if ($txt -notmatch 'Example Domain') { Fail 'text format missing content' }
    if ($txt -match '<html')             { Fail 'text format leaked HTML' }
    Pass 'format=text strips tags'

    $run3 = Join-Path $Output 'run3'
    & $Python $Script https://example.com --format html --output-dir $run3 --quiet | Out-Null
    if (-not (Test-Path (Join-Path $run3 'result.html'))) { Fail 'result.html missing' }
    $html = Get-Content (Join-Path $run3 'result.html') -Raw
    if ($html -notmatch '<html') { Fail 'html format stripped tags' }
    Pass 'format=html preserves tags'

    $errOutput = & $Python $Script ftp://example.com --quiet 2>&1
    if ($LASTEXITCODE -eq 0) { Fail 'ftp:// URL should have errored' }
    Pass 'non-http(s) scheme rejected'

    $run4 = Join-Path $Output 'run4'
    $out = & $Python $Script https://example.com --print-path content --output-dir $run4 --quiet
    if (($out -split "`n" | Where-Object { $_ }).Count -ne 1) { Fail '--print-path content should print exactly 1 line' }
    Pass '--print-path content prints one line'

    $run5 = Join-Path $Output 'run5'
    $out = & $Python $Script https://example.com --print-path json --output-dir $run5 --quiet
    if (($out -split "`n" | Where-Object { $_ }).Count -ne 1) { Fail '--print-path json should print exactly 1 line' }
    Pass '--print-path json prints one line'

    $run6 = Join-Path $Output 'run6'
    & $Python $Script https://example.com --use-urllib --output-dir $run6 --quiet | Out-Null
    $md = Get-Content (Join-Path $run6 'result.md') -Raw
    if ($md -notmatch 'Example Domain') { Fail 'urllib fallback failed' }
    $meta = (Get-Content (Join-Path $run6 'result.json') -Raw | ConvertFrom-Json)._meta
    if ($meta.transport -ne 'urllib') { Fail "expected urllib transport, got $($meta.transport)" }
    Pass 'urllib transport'

    Write-Host ''
    Write-Host 'all smoke tests passed'
}
finally {
    Remove-Item -Recurse -Force $Output -ErrorAction SilentlyContinue
}
