# Pack EIArt-Robot release zip: RobotRuntime.exe + DollSer + start.bat + README
# + Open-ChildLanMic.ps1 (LAN mic helper for /ui "打开 /child")
# Run on Windows from repo root (or any cwd; script resolves repo root).
#
# Optional:
#   $env:ROBOT_RELEASE_VERSION = "1.0.0"
#   $env:SKIP_BUILD_EXE = "1"   # reuse existing dist\RobotRuntime.exe

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
Set-Location $Root

$DistExe = Join-Path $Root "dist\RobotRuntime.exe"
$DollSerSrc = Join-Path $Root "doll\DollSer"
$PackagingDir = Join-Path $Root "robot_runtime\packaging"
$EmotionsSrc = Join-Path $Root "static\resources\Emotions"
$OutDir = Join-Path $Root "releases\robot"
$StageRoot = Join-Path $Root "releases\_stage_robot"
$Stage = Join-Path $StageRoot "EIArt-Robot"
$VersionFile = Join-Path $Root "robot_runtime\VERSION"

if (-not (Test-Path (Join-Path $DollSerSrc "bin\DollSer.exe"))) {
    throw "DollSer missing: $DollSerSrc\bin\DollSer.exe"
}
if (-not (Test-Path (Join-Path $PackagingDir "start.bat"))) {
    throw "Packaging template missing: $PackagingDir\start.bat"
}
if (-not (Test-Path (Join-Path $PackagingDir "start_robot_runtime.ps1"))) {
    throw "Packaging template missing: $PackagingDir\start_robot_runtime.ps1"
}
if (-not (Test-Path $EmotionsSrc)) {
    throw "Emotions directory missing: $EmotionsSrc"
}

# Version
$gitHash = ""
try {
    $gitHash = (git -C $Root rev-parse --short HEAD 2>$null).Trim()
} catch { }
$PreviousVersion = ""
if (Test-Path $VersionFile) {
    $PreviousVersion = (Get-Content -LiteralPath $VersionFile -Raw -Encoding UTF8).Trim()
}
$Version = $env:ROBOT_RELEASE_VERSION
if (-not $Version) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmm"
    if ($gitHash) { $Version = "$stamp-$gitHash" } else { $Version = $stamp }
}

if ($env:SKIP_BUILD_EXE -eq "1" -and $PreviousVersion -ne $Version) {
    throw "SKIP_BUILD_EXE cannot publish a new version ($Version) from an EXE built as $PreviousVersion. Rebuild the EXE."
}

Write-Host "[pack] version=$Version"

# Bake version into source tree BEFORE PyInstaller so exe embeds it
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($VersionFile, ($Version.Trim() + "`n"), $Utf8NoBom)
Write-Host "[pack] wrote $VersionFile"

# Build exe unless skipped
if ($env:SKIP_BUILD_EXE -eq "1") {
    if (-not (Test-Path $DistExe)) { throw "SKIP_BUILD_EXE=1 but missing $DistExe" }
    Write-Host "[pack] Skipping build; using $DistExe"
} else {
    & (Join-Path $Root "robot_runtime\build_exe.ps1")
    if ($LASTEXITCODE -ne 0) { throw "build_exe.ps1 failed" }
    if (-not (Test-Path $DistExe)) { throw "Build did not produce $DistExe" }
}

# Stage
if (Test-Path $StageRoot) { Remove-Item -Recurse -Force $StageRoot }
New-Item -ItemType Directory -Path $Stage -Force | Out-Null
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

$OpenChildScript = Join-Path $Root "scripts\Open-ChildLanMic.ps1"
if (-not (Test-Path $OpenChildScript)) {
    throw "Missing LAN mic helper: $OpenChildScript"
}
# Keep packaging mirror in sync for source-mode resolve path
Copy-Item -Force $OpenChildScript (Join-Path $PackagingDir "Open-ChildLanMic.ps1")

Copy-Item -Force $DistExe (Join-Path $Stage "RobotRuntime.exe")
Copy-Item -Force (Join-Path $PackagingDir "start.bat") (Join-Path $Stage "start.bat")
Copy-Item -Force (Join-Path $PackagingDir "start_robot_runtime.ps1") (Join-Path $Stage "start_robot_runtime.ps1")
Copy-Item -Force (Join-Path $PackagingDir "restart.bat") (Join-Path $Stage "restart.bat")
Copy-Item -Force (Join-Path $PackagingDir "restart_robot_runtime.ps1") (Join-Path $Stage "restart_robot_runtime.ps1")
Copy-Item -Force (Join-Path $PackagingDir "README.txt") (Join-Path $Stage "README.txt")
Copy-Item -Force $VersionFile (Join-Path $Stage "VERSION")
Copy-Item -Force $OpenChildScript (Join-Path $Stage "Open-ChildLanMic.ps1")
Copy-Item -Recurse -Force $EmotionsSrc (Join-Path $Stage "Emotions")
Copy-Item -Recurse -Force $DollSerSrc (Join-Path $Stage "DollSer")

$BackendUrl = $env:ROBOT_RUNTIME_BACKEND_URL
if (-not $BackendUrl) {
    $LanAddress = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' -and $_.PrefixOrigin -ne 'WellKnown' } |
        Sort-Object InterfaceMetric |
        Select-Object -First 1 -ExpandProperty IPAddress
    if ($LanAddress) { $BackendUrl = "http://${LanAddress}:8080" }
}
if (-not $BackendUrl) {
    throw "Unable to determine backend URL. Set ROBOT_RUNTIME_BACKEND_URL before packaging."
}
$RuntimeConfig = [ordered]@{
    backendUrl = $BackendUrl.TrimEnd('/')
    runtimeKey = [string]$env:ROBOT_RUNTIME_KEY
    protocolVersion = "1"
    dollSerOscPort = 12000
}
$RuntimeConfig | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $Stage "runtime-config.json") -Encoding UTF8
Write-Host "[pack] baked backendUrl=$($RuntimeConfig.backendUrl)"

$ZipName = "EIArt-Robot-$Version.zip"
$ZipPath = Join-Path $OutDir $ZipName
$LatestPath = Join-Path $OutDir "EIArt-Robot-latest.zip"

if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
if (Test-Path $LatestPath) { Remove-Item -Force $LatestPath }

Write-Host "[pack] Compressing $ZipName ..."
# Prefer Python zipfile: Compress-Archive often fails with "file in use" on freshly built exe
$PyZip = @"
import hashlib, json, shutil, zipfile
from pathlib import Path
from datetime import datetime, timezone
stage = Path(r'$Stage')
outdir = Path(r'$OutDir')
zip_path = outdir / '$ZipName'
latest = outdir / 'EIArt-Robot-latest.zip'
if zip_path.exists():
    zip_path.unlink()
if latest.exists():
    latest.unlink()
with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    for p in stage.rglob('*'):
        if p.is_file():
            zf.write(p, arcname=str(Path('EIArt-Robot') / p.relative_to(stage)))
shutil.copy2(zip_path, latest)
h = hashlib.sha256(zip_path.read_bytes()).hexdigest()
manifest = {
    'available': True,
    'version': r'''$Version''',
    'buildVersion': r'''$Version''',
    'protocolVersion': '1',
    'sourceCommit': r'''$gitHash''',
    'filename': '$ZipName',
    'latest': 'EIArt-Robot-latest.zip',
    'sha256': h,
    'sizeBytes': zip_path.stat().st_size,
    'builtAt': datetime.now(timezone.utc).isoformat(),
}
(outdir / 'manifest.json').write_text(json.dumps(manifest, indent=2) + chr(10), encoding='utf-8')
print(h)
print(zip_path.stat().st_size)
"@
$PyOut = python -c $PyZip
if ($LASTEXITCODE -ne 0) { throw "python zip failed" }
$Hash = ($PyOut | Select-Object -First 1).Trim()
$Size = [int64](($PyOut | Select-Object -Skip 1 -First 1).Trim())
$BuiltAt = (Get-Date).ToUniversalTime().ToString("o")

# Cleanup stage
Remove-Item -Recurse -Force $StageRoot

Write-Host "[pack] OK: $ZipPath"
Write-Host "[pack]     $LatestPath"
Write-Host "[pack]     $(Join-Path $OutDir 'manifest.json')"
Write-Host "[pack] sha256=$Hash size=$Size"
