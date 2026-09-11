# Self-starts the IndianKanoon Docs add-on backend: api_server.py + a
# Cloudflare Quick Tunnel, then rewrites Code.gs's baked-in defaults and
# pushes them via clasp -- so the Quick Tunnel's per-restart URL never needs
# manually re-pasting into Apps Script Properties. Registered to run at
# Windows logon (see register-startup.ps1); safe to run by hand too.
#
# ponytail: Quick Tunnel URLs aren't stable across cloudflared restarts (only
# this script's own tunnel process, started fresh below, needs re-pushing) --
# switch to a named Cloudflare Tunnel with a real domain to drop the clasp
# push step entirely.

$ErrorActionPreference = 'Stop'
$root = 'C:\Users\HP-LT\scratchbrief-ind-mcp'
$tokenFile = Join-Path $root '.ik_proxy_token'
$logFile = Join-Path $root 'cloudflared.log'
$localConfigGs = Join-Path $root 'docs-addon\LocalConfig.gs'

if (Test-Path $tokenFile) {
    $token = (Get-Content $tokenFile -Raw).Trim()
} else {
    $token = [guid]::NewGuid().ToString('N')
    Set-Content -Path $tokenFile -Value $token -NoNewline
}

# Kill any leftovers from a previous run of this script (e.g. a prior logon).
Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -eq (Join-Path $root '.venv\Scripts\python.exe')
} | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# A Chrome instance orphaned by killing python.exe above (rather than letting
# it shut down cleanly) holds this project's .chrome-profile lock and makes
# the next api_server.py's browser.py fail with "Failed to connect to
# browser" -- confirmed live. Safe to kill: isolated to this project's own
# profile dir (per README), never the user's real Chrome windows.
#
# Matches on the backend's own profile dir specifically, NOT just "*$root*"
# -- the Claude Desktop MCP server (indiankanoon_mcp.py) runs its own
# separate, concurrently-running Chrome against .chrome-profile-mcp (see
# browser.py's IK_CHROME_PROFILE_DIR), which also lives under $root and must
# survive this backend restarting.
$backendProfileDir = Join-Path $root '.chrome-profile'
Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*$backendProfileDir*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Remove-Item $logFile -ErrorAction SilentlyContinue

$env:IK_PROXY_TOKEN = $token
Start-Process -FilePath (Join-Path $root '.venv\Scripts\python.exe') `
    -ArgumentList (Join-Path $root 'api_server.py') `
    -WorkingDirectory $root `
    -WindowStyle Hidden

Start-Process -FilePath 'cloudflared' `
    -ArgumentList 'tunnel', '--url', 'http://127.0.0.1:8791' `
    -RedirectStandardError $logFile `
    -WindowStyle Hidden

$tunnelUrl = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path $logFile) {
        $match = Select-String -Path $logFile -Pattern 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($match) {
            $tunnelUrl = $match.Matches[0].Value
            break
        }
    }
}
if (-not $tunnelUrl) {
    throw "cloudflared didn't print a tunnel URL within 30s -- check $logFile"
}

$localConfig = @"
// Gitignored -- rewritten automatically by start-backend.ps1 on every
// restart. See the note above DEFAULT_BACKEND_URL's use in Code.gs.
const DEFAULT_BACKEND_URL = '$tunnelUrl';
const DEFAULT_BACKEND_TOKEN = '$token';
"@
Set-Content -Path $localConfigGs -Value $localConfig -NoNewline

Push-Location (Join-Path $root 'docs-addon')
try {
    & clasp.cmd push --force
} finally {
    Pop-Location
}

Write-Output "Backend up at http://127.0.0.1:8791, tunneled at $tunnelUrl, Code.gs pushed."
