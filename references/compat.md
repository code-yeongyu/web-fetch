# Compatibility - Python and OS support matrix

This skill is designed to run on macOS, Linux (modern + older LTS), and Windows. The script is single-file Python 3 stdlib, so the surface area is small. This file documents the exact requirements per platform.

## Supported platforms

| OS | Tested | Notes |
|---|---|---|
| macOS 12+ | Yes | System Python 3.9 + Homebrew curl works |
| Ubuntu 22.04+ / Debian 12+ | Yes | Default Python 3.10/3.11 + curl 7.81+ |
| Ubuntu 20.04 / Debian 11 | Yes | Default Python 3.8 needs upgrade; install python3.9 from PPA |
| RHEL 8 / Rocky 8 / AlmaLinux 8 | Yes | `dnf install python3.9` |
| RHEL 7 / CentOS 7 | Limited | EOL; install python3.9 from EPEL/SCL or build from source |
| Windows 11 | Yes | Native via `python.exe` + bundled `curl.exe` |
| Windows 10 (1803+) | Yes | Same as 11 |
| Windows 10 (older) | Limited | `curl.exe` not bundled before 1803; install via winget/scoop, or use `--use-urllib` |
| WSL2 | Yes | Treated as Linux |
| Alpine Linux | Yes | `apk add python3 curl` |
| FreeBSD / OpenBSD | Likely | Untested in CI but uses only POSIX features |

## Python version floor

**Minimum supported: Python 3.9** (released October 2020).

Why 3.9 and not older:

- The script uses `from __future__ import annotations`, so PEP 585 generic syntax (`dict[str, str]` etc.) works at parse time on 3.7+.
- `subprocess.run(capture_output=True)` requires 3.7+.
- We never call `eval()` on annotations, so type-hint shape is irrelevant at runtime.
- 3.9 reached upstream end-of-life in 2025-10. It remains the floor only because it is still what ships on older LTS distros; prefer 3.10+ wherever you can choose.

For older Pythons, you have two options:

1. **Install a newer Python alongside system Python.** This is the recommended path on RHEL 7 / Ubuntu 18.04 / etc.
   - Ubuntu/Debian: `sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python3.9`
   - RHEL/CentOS 7: `sudo yum install -y python39` (from EPEL or IUS)
   - Alpine: `apk add python3` (already 3.9+ on alpine 3.13+)
   - Then invoke explicitly: `python3.9 scripts/web_fetch.py ...`

2. **Force urllib transport.** The Python `urllib` fallback works on any Python 3.6+ in practice, even if our test matrix only certifies 3.9. Pass `--use-urllib`:
   ```bash
   python3 scripts/web_fetch.py <URL> --use-urllib
   ```
   This avoids any curl-related issues on older systems.

## curl version floor

**Minimum supported: curl 7.40+** (released January 2015).

The script's curl invocation uses these flags:

| Flag | Required curl version |
|---|---|
| `-sS` (silent + show errors) | ancient |
| `-L` (follow redirects) | ancient |
| `-o -` (write to stdout) | ancient |
| `-X GET` | ancient |
| `-H "header: value"` | ancient |
| `--max-time SEC` | ancient |
| `--max-filesize BYTES` | curl 7.10 (2002) |
| `--data-binary @-` | ancient |
| `-w "%{http_code}\t%{url_effective}\t%{content_type}"` | curl 7.40 (Jan 2015) - `%{content_type}` was added then |

If your distro ships an older curl, the `-w` template will print empty values for `%{content_type}` and HTML→markdown conversion will not auto-trigger. Workaround: use `--use-urllib`.

Verify with:

```bash
curl --version | head -1
```

## OS-specific gotchas

### macOS

- System Python 3 may be 3.9 (old macOS) or absent on newer macOS where `python3` opens the App Store. Use Homebrew Python: `brew install python@3.12`.
- System curl uses Secure Transport (Apple's TLS) which can lag behind OpenSSL. If you hit "SSL CA bundle problem" (curl exit 60), install Homebrew curl: `brew install curl` and prepend `/opt/homebrew/opt/curl/bin` to PATH.

### Modern Linux (Ubuntu 22.04+, Debian 12+, Fedora 38+)

Ships with everything needed out of the box. No setup required beyond:

```bash
sudo apt install python3 curl   # or dnf, or pacman
```

### Old Linux (RHEL 7, Ubuntu 18.04, CentOS 7)

Default Python is 3.6, which fails because of `from __future__ import annotations` + parsing of generic syntax in `.pyi` style. Install Python 3.9 from EPEL / deadsnakes / SCL:

```bash
# RHEL 7 / CentOS 7
sudo yum install -y centos-release-scl
sudo yum install -y rh-python39
scl enable rh-python39 bash
# Then 'python3 --version' shows 3.9.x

# Ubuntu 18.04 / 20.04
sudo apt install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update && sudo apt install python3.9
```

Run explicitly:

```bash
python3.9 scripts/web_fetch.py https://example.com
```

If you cannot install a newer Python, you can patch the script: remove `from __future__ import annotations` and replace generic syntax with `typing.Dict[str, str]` etc. We do not maintain a 3.6-compatible branch.

### Windows 10 / 11

Out of the box on 1803+:

```powershell
python --version       # if missing: winget install Python.Python.3.12
curl --version         # bundled
.\scripts\web_fetch.py https://example.com    # works as-is
```

The shebang `#!/usr/bin/env python3` is ignored on Windows; invoke with `python` or `py` explicitly. Path separators are handled by `pathlib` so output paths use `\` correctly.

### WSL / WSL2

Treated as Linux. No special config. Output paths inside WSL use `/tmp/web-fetch-...` (the Linux temp dir, not the Windows one). If you want Windows tools to see them, use `--output-dir /mnt/c/Users/you/Downloads/web-fetch`.

### Alpine / Docker

```dockerfile
FROM alpine:3.18
RUN apk add --no-cache python3 curl ripgrep jq
COPY scripts/web_fetch.py /usr/local/bin/web-fetch.py
ENTRYPOINT ["python3", "/usr/local/bin/web-fetch.py"]
```

This image is ~50 MB and works as a drop-in fetch sidecar.

## Verifying your environment

Run the smoke test:

```bash
bash tests/smoke.sh
```

It exits non-zero on any failure and reports which step broke. The test fetches `https://example.com` so it requires outbound HTTPS to that host.

For Windows PowerShell, equivalents:

```powershell
.\tests\smoke.ps1
```

Both test scripts cover: version flag, markdown fetch, envelope shape, format=text, format=html, scheme rejection, --print-path modes, urllib fallback.

## Reporting compatibility issues

If something fails on a platform listed as supported, the trace will tell you what broke:

```bash
python3 scripts/web_fetch.py <URL> --verbose 2>trace.log
cat trace.log
cat /tmp/web-fetch-*/trace.json | python3 -m json.tool
```

Open an issue with:

- Your OS + version (`uname -a` or `winver`)
- `python3 --version`
- `curl --version | head -1`
- The trace log
- The `_meta.attempts[]` from `trace.json`
