# Open /child over LAN HTTP with mic permission (Chrome/Edge insecure-origin flag).
#
# Why: getUserMedia needs a "secure context". http://127.0.0.1 is secure;
# http://LAN-IP is not. This launches Edge (prefer) or Chrome with
# --unsafely-treat-insecure-origin-as-secure so the child page can use the mic
# while the Demo Server stays on plain HTTP (ENABLE_HTTPS=false).
#
# -LanHost must be the backend/Flask host. When the child device is separate
# from the server, always pass the server's LAN address explicitly.
#
# Usage:
#   .\scripts\Open-ChildLanMic.ps1
#   .\scripts\Open-ChildLanMic.ps1 -LanHost 192.168.1.113
#   .\scripts\Open-ChildLanMic.ps1 -Port 8080
#
# Server/teacher on backend PC: http://127.0.0.1:8080 (no flag needed).
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

if (-not $LanHost) {
    $LanHost = Get-LanIpv4
    if (-not $LanHost) {
        $LanHost = "192.168.1.113"
        Write-Warning "Could not detect LAN IP; using default $LanHost. Pass -LanHost <后端IP> if wrong."
    } else {
        Write-Warning "Using this machine's LAN IP $LanHost. Cross-machine: pass -LanHost <后端服务器IP>."
    }
}

$origin = "http://${LanHost}:${Port}"
$url = "$origin/child"
$userDataDir = Join-Path $env:TEMP "eiart-child-kiosk"
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
    "--new-window",
    # Kiosk removes tabs/address bar and is the browser-level boundary that
    # page JavaScript cannot provide on a touch screen.
    "--kiosk",
    "--edge-kiosk-type=fullscreen",
    "--disable-pinch",
    "--overscroll-history-navigation=0",
    "--disable-features=OverscrollHistoryNavigation,TouchpadOverscrollHistoryNavigation,TouchscreenOverscrollHistoryNavigation",
    "--disable-session-crashed-bubble",
    "--noerrdialogs",
    "--unsafely-treat-insecure-origin-as-secure=$origin",
    "--user-data-dir=$userDataDir",
    "--no-first-run",
    "--no-default-browser-check",
    $url
)

Write-Host "Launching child touch kiosk: $browser"
Write-Host "  origin flag: $origin"
Write-Host "  user-data:   $userDataDir"
Write-Host "  open:        $url"
Start-Process -FilePath $browser -ArgumentList $browserArgs
