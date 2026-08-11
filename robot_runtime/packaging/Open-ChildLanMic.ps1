# Open /child over LAN HTTP with mic permission (Chrome/Edge insecure-origin flag).
#
# Why: getUserMedia needs a "secure context". http://127.0.0.1 is secure;
# http://LAN-IP is not. This launches Edge (prefer) or Chrome with
# --unsafely-treat-insecure-origin-as-secure so the child page can use the mic
# while Runtime stays on plain HTTP (ENABLE_HTTPS=false).
#
# -LanHost must be the BACKEND / Flask host (server machine), NOT the robot's
# own IP when app.py runs on another PC. Runtime「打开 /child」passes this.
#
# Usage:
#   .\scripts\Open-ChildLanMic.ps1
#   .\scripts\Open-ChildLanMic.ps1 -LanHost 192.168.1.113
#   .\scripts\Open-ChildLanMic.ps1 -Port 8080
#
# Runtime / teacher on backend PC: http://127.0.0.1:8080 (no flag needed).
# Child tablet/PC on LAN: run this script (or copy the URL + flags) → http://IP:8080/child

[CmdletBinding()]
param(
    [string]$LanHost = "",
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"

function Get-LanIpv4 {
    # Prefer a private IPv4 that is Up and not a virtual adapter when possible.
    $candidates = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object {
            $_.IPAddress -notlike "127.*" -and
            $_.PrefixOrigin -ne "WellKnown" -and
            $_.IPAddress -match '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[0-1])\.)'
        } |
        Sort-Object -Property InterfaceIndex

    foreach ($addr in $candidates) {
        $if = Get-NetIPInterface -InterfaceIndex $addr.InterfaceIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue
        if ($if -and $if.ConnectionState -eq "Connected") {
            return $addr.IPAddress
        }
    }
    if ($candidates) { return $candidates[0].IPAddress }
    return $null
}

function Get-BackendHostFromRuntimeConfig {
    # Robot Runtime persists backend URL after /ui register.
    $cfgPath = Join-Path $env:LOCALAPPDATA "EIArt\robot_runtime\config.json"
    if (-not (Test-Path -LiteralPath $cfgPath)) { return $null }
    try {
        $cfg = Get-Content -LiteralPath $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $url = [string]$cfg.backendUrl
        if (-not $url) { return $null }
        if ($url -notmatch '://') { $url = "http://$url" }
        $uri = [Uri]$url
        if (-not $uri.Host) { return $null }
        return @{
            Host = $uri.Host
            Port = if ($uri.IsDefaultPort) { 0 } else { $uri.Port }
        }
    } catch {
        return $null
    }
}

$portExplicit = $PSBoundParameters.ContainsKey("Port")

if (-not $LanHost) {
    $fromCfg = Get-BackendHostFromRuntimeConfig
    if ($fromCfg -and $fromCfg.Host -and $fromCfg.Host -notmatch '^(localhost|127\.0\.0\.1)$') {
        $LanHost = $fromCfg.Host
        if (-not $portExplicit -and $fromCfg.Port -gt 0) {
            $Port = [int]$fromCfg.Port
        }
        Write-Host "Using backend host from Runtime config: ${LanHost}:${Port}"
    }
}

if (-not $LanHost) {
    $LanHost = Get-LanIpv4
    if (-not $LanHost) {
        $LanHost = "192.168.1.113"
        Write-Warning "Could not detect LAN IP; using default $LanHost. Pass -LanHost <后端IP> if wrong."
    } else {
        Write-Warning "No Runtime backendUrl; using this machine's LAN IP $LanHost. Cross-machine: pass -LanHost <后端服务器IP>."
    }
}

$origin = "http://${LanHost}:${Port}"
$url = "$origin/child"
$userDataDir = Join-Path $env:TEMP "eiart-child-lan"
New-Item -ItemType Directory -Force -Path $userDataDir | Out-Null

$browserCandidates = @(
    "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)

$browser = $null
foreach ($path in $browserCandidates) {
    if (Test-Path -LiteralPath $path) {
        $browser = $path
        break
    }
}

if (-not $browser) {
    throw "Neither Edge nor Chrome found. Install one, or open $url manually with the insecure-origin flag."
}

# Do not use $args — automatic/read-only in PowerShell 7+.
$browserArgs = @(
    "--unsafely-treat-insecure-origin-as-secure=$origin",
    "--user-data-dir=$userDataDir",
    "--no-first-run",
    "--no-default-browser-check",
    $url
)

Write-Host "Launching: $browser"
Write-Host "  origin flag: $origin"
Write-Host "  user-data:   $userDataDir"
Write-Host "  open:        $url"
Start-Process -FilePath $browser -ArgumentList $browserArgs
