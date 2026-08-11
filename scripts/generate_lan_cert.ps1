# Generate a self-signed TLS cert for LAN HTTPS (getUserMedia / secure context).
# Usage:
#   .\scripts\generate_lan_cert.ps1
#   .\scripts\generate_lan_cert.ps1 -ExtraIps 192.168.1.113,10.0.0.5
#   .\scripts\generate_lan_cert.ps1 -OutDir .runtime\certs
#
# Requires openssl on PATH (or Anaconda's openssl).

[CmdletBinding()]
param(
    [string]$OutDir = "",
    [string[]]$ExtraIps = @(),
    [int]$Days = 825,
    [string]$CommonName = "server-demo-lan"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
if (-not $OutDir) {
    $OutDir = Join-Path $Root ".runtime\certs"
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function Find-OpenSsl {
    $cmd = Get-Command openssl -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        "D:\Anaconda\Library\bin\openssl.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python*\Scripts\openssl.exe",
        "C:\Program Files\Git\usr\bin\openssl.exe",
        "C:\Program Files\OpenSSL-Win64\bin\openssl.exe"
    )
    foreach ($c in $candidates) {
        $resolved = Resolve-Path $c -ErrorAction SilentlyContinue
        if ($resolved) { return $resolved[0].Path }
    }
    throw "openssl not found. Install OpenSSL or Git for Windows, or add openssl to PATH."
}

function Get-LanIpv4 {
    $ips = @()
    try {
        $ips += Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object {
                $_.IPAddress -and
                $_.IPAddress -notlike "127.*" -and
                $_.IPAddress -ne "0.0.0.0" -and
                $_.PrefixOrigin -ne "WellKnown"
            } |
            Select-Object -ExpandProperty IPAddress
    } catch {}
    # Fallback: ipconfig parse
    if (-not $ips) {
        $ipconfig = ipconfig | Out-String
        [regex]::Matches($ipconfig, "IPv4[\s\S]*?:\s*([\d\.]+)") | ForEach-Object {
            $ips += $_.Groups[1].Value
        }
    }
    $ips |
        Where-Object { $_ -and $_ -notlike "127.*" -and $_ -notlike "169.254.*" } |
        Select-Object -Unique
}

$openssl = Find-OpenSsl
Write-Host "[cert] openssl: $openssl"

$lanIps = @(Get-LanIpv4)
foreach ($extra in $ExtraIps) {
    if ($extra) { $lanIps += $extra.Trim() }
}
$lanIps = $lanIps | Where-Object { $_ } | Select-Object -Unique
Write-Host "[cert] SAN IPs: $($lanIps -join ', ')"

$certPath = Join-Path $OutDir "cert.pem"
$keyPath = Join-Path $OutDir "key.pem"
$configPath = Join-Path $OutDir "openssl-san.cnf"

$altNames = @(
    "DNS.1 = localhost",
    "DNS.2 = $CommonName",
    "IP.1 = 127.0.0.1"
)
$dnsIdx = 3
$ipIdx = 2
foreach ($ip in $lanIps) {
    $altNames += "IP.$ipIdx = $ip"
    $ipIdx++
}
# Also keep a DNS entry for convenience when hosts file is used
$altNames += "DNS.$dnsIdx = $CommonName.local"

$cnf = @"
[req]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_req

[dn]
C = CN
ST = Local
L = LAN
O = server_demo
CN = $CommonName

[v3_req]
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
$($altNames -join "`n")
"@

Set-Content -Path $configPath -Value $cnf -Encoding ASCII

& $openssl req -x509 -newkey rsa:2048 -nodes `
    -keyout $keyPath `
    -out $certPath `
    -days $Days `
    -config $configPath `
    -extensions v3_req

if ($LASTEXITCODE -ne 0) {
    throw "openssl failed with exit code $LASTEXITCODE"
}

Write-Host ""
Write-Host "[cert] OK  cert: $certPath"
Write-Host "[cert] OK  key:  $keyPath"
Write-Host ""
Write-Host "Enable HTTPS (PowerShell):"
Write-Host '  $env:ENABLE_HTTPS="true"'
Write-Host "  # or set SSL_CERTFILE / SSL_KEYFILE to the paths above"
Write-Host "  .\.venv\Scripts\python.exe app.py"
Write-Host ""
Write-Host "Then open (accept the browser warning once):"
Write-Host "  https://127.0.0.1:8080/child"
foreach ($ip in $lanIps) {
    if ($ip -like "192.168.*" -or $ip -like "10.*" -or $ip -like "172.*") {
        Write-Host "  https://${ip}:8080/child"
    }
}
Write-Host ""
Write-Host "Chrome tip: click Advanced → Proceed to 127.0.0.1 (unsafe)."
Write-Host "Or import cert.pem into Trusted Root Certification Authorities (local machine / current user)."
