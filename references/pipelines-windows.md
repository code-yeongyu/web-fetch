# Pipeline patterns - Windows (PowerShell + cmd)

This file covers native Windows shells. If you have Git Bash, WSL, or Cygwin, follow `pipelines-posix.md` instead - the bash patterns there work unchanged.

## Prerequisites on Windows

The Python script itself only needs:

- **Python 3.9+** (https://www.python.org/downloads/, or `winget install Python.Python.3.12`)
- **`curl.exe`** (bundled with Windows 10 1803+ / Server 2019+; verify with `curl --version`)

For piping/grepping, you will want:

- **ripgrep** (`winget install BurntSushi.ripgrep.MSVC` or `scoop install ripgrep`)
- **jq** (`winget install jqlang.jq` or `scoop install jq`)

PowerShell has built-in equivalents (`Select-String`, `ConvertFrom-Json`) so external tools are optional.

## PowerShell

### Capture paths into variables

```powershell
# Default --print-path=all returns two lines: content, then json
$paths   = python web_fetch.py https://example.com --quiet
$content = $paths[0]
$json    = $paths[1]

# Or grab one path directly
$content = python web_fetch.py https://example.com --print-path content --quiet
$json    = python web_fetch.py https://example.com --print-path json    --quiet
```

### Search inside the page

```powershell
# Built-in (no rg required)
Select-String -Path $content -Pattern 'TaskGroup'
Select-String -Path $content -Pattern 'asyncio.run' -Context 2,6
Select-String -Path $content -Pattern 'deprecated|removed since' -CaseSensitive:$false

# Count matches
(Select-String -Path $content -Pattern 'TaskGroup').Count

# Extract URLs (regex)
Get-Content $content | Select-String -Pattern 'https?://[A-Za-z0-9./_-]+' -AllMatches |
    ForEach-Object { $_.Matches.Value } | Sort-Object -Unique
```

If you have `rg.exe` installed, the POSIX `rg` examples in `pipelines-posix.md` work in PowerShell too:

```powershell
rg -in "TaskGroup" $content
rg -B2 -A6 "asyncio.run" $content
```

### Section extraction (markdown)

PowerShell does not have `awk` natively. Either install `gawk` (scoop/chocolatey) or use this pattern:

```powershell
# Everything between "## TaskGroup" and the next "## " heading
$lines = Get-Content $content
$inSection = $false
foreach ($line in $lines) {
    if ($line -match '^## TaskGroup') { $inSection = $true; $line; continue }
    if ($inSection -and $line -match '^## ' -and $line -notmatch '^## TaskGroup') { break }
    if ($inSection) { $line }
}
```

### Inspect metadata

```powershell
# Built-in JSON parsing
$meta = (Get-Content $json -Raw | ConvertFrom-Json)._meta
$meta.final_url
$meta.content_type
$meta.bytes
$meta.attempts | ForEach-Object {
    "$($_.user_agent)`t$($_.status)`t$($_.duration_ms)ms`t$($_.bytes)B"
}
```

If you have `jq.exe`:

```powershell
jq -r '._meta.final_url' $json
jq -r '._meta.attempts[] | "\(.user_agent)\t\(.status)\t\(.duration_ms)ms"' $json
```

### Compose - fetch + filter + format

```powershell
# All GitHub issue links from a project README
$content = python web_fetch.py https://github.com/anthropics/anthropic-sdk-python --print-path content --quiet
Get-Content $content | Select-String -Pattern 'https://github\.com/[^\)]+/issues/\d+' -AllMatches |
    ForEach-Object { $_.Matches.Value } | Sort-Object -Unique
```

### Batch fetch many URLs in parallel

PowerShell 7+ has `ForEach-Object -Parallel`:

```powershell
# urls.txt with one URL per line
$urls = Get-Content urls.txt
$paths = $urls | ForEach-Object -Parallel {
    python web_fetch.py $_ --print-path content --quiet
} -ThrottleLimit 8

$paths | Set-Content paths.txt

# Grep across all
Get-Content paths.txt | ForEach-Object {
    Select-String -Path $_ -Pattern 'deprecated'
}
```

Windows PowerShell 5.1 (the default on Windows 10/11) does NOT have `-Parallel`. Use background jobs:

```powershell
$jobs = @()
foreach ($url in (Get-Content urls.txt)) {
    $jobs += Start-Job -ScriptBlock {
        param($u) python web_fetch.py $u --print-path content --quiet
    } -ArgumentList $url
}
$paths = $jobs | Receive-Job -Wait | Where-Object { $_ }
$jobs | Remove-Job
```

### Stable output dir

```powershell
python web_fetch.py https://example.com --output-dir .\scratch\example-com --quiet
Get-ChildItem .\scratch\example-com\
```

## cmd.exe (legacy)

Modern Windows ships PowerShell as the default. cmd.exe still works:

```cmd
REM Capture content path
for /f "delims=" %p in ('python web_fetch.py https://example.com --print-path content --quiet') do set CONTENT=%p

REM Display the file
type %CONTENT%

REM Search with findstr (very limited compared to rg / Select-String)
findstr /i "TaskGroup" %CONTENT%
```

If you can use cmd.exe at all, you can use PowerShell. Prefer PowerShell.

## Anti-patterns

- **`type %FILE% | findstr ...` for big files** - findstr is slow and limited. Install ripgrep.
- **Manual JSON parsing in cmd.exe** - install jq, or use PowerShell's `ConvertFrom-Json`.
- **Calling `python3` instead of `python`** - on Windows, the launcher is `python` (and optionally `py`). The Python script itself is named the same; only the invocation differs.
- **Relying on `\` vs `/` path separators** - the Python script uses `pathlib`, so paths it produces work either way. Just quote them.

## Path quoting gotcha

Output paths from `web_fetch.py` on Windows look like:

```
C:\Users\you\AppData\Local\Temp\web-fetch-20260501-171120-abc123\result.md
```

The backslashes are fine in PowerShell strings, but in cmd.exe variable expansion they sometimes need escaping. When in doubt, wrap the path in double quotes:

```powershell
Select-String -Path "$content" -Pattern 'TaskGroup'
```

```cmd
findstr /i "TaskGroup" "%CONTENT%"
```
