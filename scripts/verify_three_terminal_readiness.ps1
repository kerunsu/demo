[CmdletBinding()]
param(
    [string]$ServerUrl = 'http://192.168.1.110:8080',
    [string]$TeacherUrl = 'http://192.168.1.110:8080/teacher',
    [string]$RuntimeUrl = 'http://192.168.1.106:19091',
    [switch]$RunDeviceCheck
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$checks = New-Object System.Collections.Generic.List[object]
$evidence = [ordered]@{
    schemaVersion = 1
    checkedAt = [DateTimeOffset]::UtcNow.ToString('o')
    endpoints = [ordered]@{
        server = $ServerUrl.TrimEnd('/')
        teacher = $TeacherUrl.TrimEnd('/')
        runtime = $RuntimeUrl.TrimEnd('/')
    }
    checks = $checks
}

function Add-Check {
    param(
        [string]$Name,
        [bool]$Passed,
        [string]$Detail,
        $Data = $null
    )
    $checks.Add([ordered]@{
        name = $Name
        passed = $Passed
        detail = $Detail
        data = $Data
    })
}

function Get-JsonBodyFromFailure {
    param($Failure)
    try {
        $stream = $Failure.Exception.Response.GetResponseStream()
        $reader = New-Object System.IO.StreamReader($stream)
        return ($reader.ReadToEnd() | ConvertFrom-Json)
    } catch {
        return $null
    }
}

try {
    $teacher = Invoke-WebRequest -UseBasicParsing -Uri "$($TeacherUrl.TrimEnd('/'))/" -TimeoutSec 5
    Add-Check 'teacher_http' ($teacher.StatusCode -eq 200) "HTTP $($teacher.StatusCode)"
} catch {
    Add-Check 'teacher_http' $false $_.Exception.Message
}

$serverStatus = $null
try {
    $serverStatus = Invoke-RestMethod -Uri "$($ServerUrl.TrimEnd('/'))/api/server/status" -TimeoutSec 5
    Add-Check 'server_status' ([bool]$serverStatus.success) 'Server status endpoint' $serverStatus
} catch {
    Add-Check 'server_status' $false $_.Exception.Message
}

$runtimeHealth = $null
try {
    $runtimeHealth = Invoke-RestMethod -Uri "$($RuntimeUrl.TrimEnd('/'))/health" -TimeoutSec 5
    $healthOk = [bool]$runtimeHealth.ok -and [string]$runtimeHealth.protocolVersion -eq '1'
    Add-Check 'runtime_health' $healthOk 'Runtime health and protocol' $runtimeHealth
} catch {
    Add-Check 'runtime_health' $false $_.Exception.Message
}

$runtimeReady = $null
try {
    $runtimeReady = Invoke-RestMethod -Uri "$($RuntimeUrl.TrimEnd('/'))/ready" -TimeoutSec 8
    Add-Check 'runtime_ready' ([bool]$runtimeReady.ready) 'Runtime ready endpoint' $runtimeReady
} catch {
    $runtimeReady = Get-JsonBodyFromFailure $_
    Add-Check 'runtime_ready' $false $_.Exception.Message $runtimeReady
}

if ($serverStatus) {
    $primary = $serverStatus.robotRuntime.primary
    $caps = @($primary.capabilities)
    $matrixOk = (
        $null -ne $primary -and
        $primary.compatible -eq $true -and
        [string]$primary.protocolVersion -eq '1' -and
        $caps -contains 'behavior-sync-v1' -and
        $caps -contains 'device-preflight-v1' -and
        $caps -contains 'multi-track-media-v1'
    )
    Add-Check 'version_matrix' $matrixOk 'Compatible primary Runtime with required capabilities' $serverStatus.robotRuntime.versionMatrix
}

if ($RunDeviceCheck) {
    try {
        $device = Invoke-RestMethod `
            -Method Post `
            -Uri "$($ServerUrl.TrimEnd('/'))/api/v2/control/devices/check" `
            -ContentType 'application/json' `
            -Body '{}' `
            -TimeoutSec 30
        Add-Check 'real_device_first_samples' ([bool]$device.allConnected) 'Camera and microphone first-sample check' $device
    } catch {
        Add-Check 'real_device_first_samples' $false $_.Exception.Message
    }
}

$passed = @($checks | Where-Object { -not $_.passed }).Count -eq 0
$evidence.passed = $passed
$reportDir = Join-Path $root 'logs\acceptance'
New-Item -ItemType Directory -Path $reportDir -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$reportPath = Join-Path $reportDir "three-terminal-readiness-$stamp.json"
$evidence | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host "[verify] report=$reportPath"
Write-Host "[verify] passed=$passed"
$checks | ForEach-Object {
    Write-Host ("[verify] {0}: {1} ({2})" -f $_.name, $_.passed, $_.detail)
}

if (-not $passed) { exit 1 }
exit 0
