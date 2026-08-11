# Build RobotRuntime.exe with PyInstaller (run from repo root on Windows)
# Requires: pip install pyinstaller
#
# DollSer is NOT bundled here — use scripts/pack_robot_release.ps1 for the full zip.
# Prefer a clean venv with only robot_runtime/requirements.txt to keep the exe small.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$BuildPython = $env:ROBOT_BUILD_PYTHON

function Test-PythonCommand {
  param([string[]]$CommandParts)

  if (-not $CommandParts -or $CommandParts.Count -eq 0) { return $false }
  $command = Get-Command $CommandParts[0] -ErrorAction SilentlyContinue
  if (-not $command) { return $false }
  $prefixArgs = @()
  if ($CommandParts.Count -gt 1) {
    $prefixArgs = $CommandParts[1..($CommandParts.Count - 1)]
  }
  # A missing py-launcher runtime writes to stderr.  With the script-wide
  # ErrorActionPreference=Stop PowerShell would otherwise abort before trying
  # the next candidate.
  $previousErrorAction = $ErrorActionPreference
  $ErrorActionPreference = "SilentlyContinue"
  try {
    & $CommandParts[0] @prefixArgs -c "import sys; assert sys.version_info >= (3, 9)" 2>$null
    return $LASTEXITCODE -eq 0
  } finally {
    $ErrorActionPreference = $previousErrorAction
  }
}

if ([string]::IsNullOrWhiteSpace($BuildPython)) {
  # 3.9 was used by the original release machine, but is not a hard runtime
  # requirement.  Try it first for reproducibility, then use any installed
  # Python instead of failing on a machine that only has (for example) 3.12.
  $candidates = @(
    @("py", "-3.9"),
    @("py", "-3"),
    @("python"),
    @("python3")
  )
  foreach ($candidate in $candidates) {
    if (Test-PythonCommand $candidate) {
      $BuildPythonParts = $candidate
      break
    }
  }
  if (-not $BuildPythonParts) {
    throw "No usable Python 3.9+ runtime found. Install Python or set ROBOT_BUILD_PYTHON."
  }
} else {
  $BuildPythonParts = $BuildPython.Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)
  if (-not (Test-PythonCommand $BuildPythonParts)) {
    throw "ROBOT_BUILD_PYTHON is not a usable Python 3.9+ command: $BuildPython"
  }
}

Write-Host "[build_exe] Using Python: $($BuildPythonParts -join ' ')"
$BuildVenv = Join-Path $Root ".venv_robot_build_py39"
$PythonExe = Join-Path $BuildVenv "Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
  Write-Host "[build_exe] Creating clean build venv..."
  if ($BuildPythonParts.Length -gt 1) {
    & $BuildPythonParts[0] $BuildPythonParts[1..($BuildPythonParts.Length - 1)] -m venv $BuildVenv
  } else {
    & $BuildPythonParts[0] -m venv $BuildVenv
  }
  if ($LASTEXITCODE -ne 0) { throw "create build venv failed" }
}

Write-Host "[build_exe] Installing build dependencies..."
& $PythonExe -m pip install -q -U pip wheel setuptools
if ($LASTEXITCODE -ne 0) { throw "pip bootstrap failed" }
& $PythonExe -m pip install -q --upgrade --upgrade-strategy eager -r (Join-Path $Root "robot_runtime\requirements.txt") "pyinstaller==6.11.1"
if ($LASTEXITCODE -ne 0) { throw "pip install build dependencies failed" }
& $PythonExe -m pip uninstall -q -y charset-normalizer

Write-Host "[build_exe] Building RobotRuntime.exe (onefile)..."
& $PythonExe -m PyInstaller `
  --noconfirm `
  --clean `
  --name RobotRuntime `
  --onefile `
  --console `
  --add-data "robot_runtime/static;robot_runtime/static" `
  --add-data "robot_runtime/VERSION;robot_runtime" `
  --hidden-import robot_runtime `
  --hidden-import robot_runtime.osc_bridge `
  --hidden-import robot_runtime.register_client `
  --hidden-import robot_runtime.updater `
  --hidden-import flask `
  --hidden-import flask_cors `
  --hidden-import cv2 `
  --hidden-import numpy `
  --hidden-import requests `
  --hidden-import pythonosc `
  --hidden-import pythonosc.udp_client `
  --collect-submodules pythonosc `
  --exclude-module charset_normalizer `
  --exclude-module matplotlib `
  --exclude-module PyQt5 `
  --exclude-module PyQt6 `
  --exclude-module PySide2 `
  --exclude-module PySide6 `
  --exclude-module IPython `
  --exclude-module jupyter `
  --exclude-module notebook `
  --exclude-module sphinx `
  --exclude-module jieba `
  --exclude-module pandas `
  --exclude-module scipy `
  --exclude-module sklearn `
  --exclude-module torch `
  --exclude-module tensorflow `
  --exclude-module tkinter `
  --exclude-module _tkinter `
  --exclude-module PIL `
  --exclude-module pytest `
  robot_runtime/agent.py

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$Exe = Join-Path $Root "dist\RobotRuntime.exe"
if (-not (Test-Path $Exe)) { throw "Expected output missing: $Exe" }

Write-Host "[build_exe] OK: $Exe"
Write-Host "[build_exe] Next: scripts\pack_robot_release.ps1  (bundles DollSer + start.bat)"
