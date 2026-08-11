param(
    [string]$TargetHost = "127.0.0.1",
    [int]$Port = 12000,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-BigEndianIntBytes {
    param([int]$Value)

    $bytes = [System.BitConverter]::GetBytes([int]$Value)
    if ([System.BitConverter]::IsLittleEndian) {
        [Array]::Reverse($bytes)
    }

    return ,([byte[]]$bytes)
}

function Get-OscPaddedStringBytes {
    param([string]$Text)

    $raw = [System.Text.Encoding]::ASCII.GetBytes($Text)
    $buffer = New-Object System.Collections.Generic.List[byte]
    $buffer.AddRange($raw)
    $buffer.Add(0)

    while (($buffer.Count % 4) -ne 0) {
        $buffer.Add(0)
    }

    return ,([byte[]]$buffer.ToArray())
}

function New-OscMessageBytes {
    param(
        [string]$Address,
        [int]$Value,
        [int]$TimeMs
    )

    $buffer = New-Object System.Collections.Generic.List[byte]
    $buffer.AddRange((Get-OscPaddedStringBytes -Text $Address))
    $buffer.AddRange((Get-OscPaddedStringBytes -Text ",ii"))
    $buffer.AddRange((Get-BigEndianIntBytes -Value $Value))
    $buffer.AddRange((Get-BigEndianIntBytes -Value $TimeMs))
    return ,([byte[]]$buffer.ToArray())
}

function Send-OscAxis {
    param(
        [System.Net.Sockets.UdpClient]$Client,
        [string]$Axis,
        [int]$Value,
        [int]$TimeMs
    )

    $clampedValue = [Math]::Min(359, [Math]::Max(0, $Value))
    $clampedTime = [Math]::Min(5000, [Math]::Max(100, $TimeMs))
    Write-Host ("  {0,-6} -> {1,3}  time={2}ms" -f $Axis, $clampedValue, $clampedTime)

    if ($DryRun) {
        return
    }

    $payload = New-OscMessageBytes -Address "/$($Axis.ToLower())" -Value $clampedValue -TimeMs $clampedTime
    [void]$Client.Send($payload, $payload.Length, $TargetHost, $Port)
}

function Send-Pose {
    param(
        [System.Net.Sockets.UdpClient]$Client,
        [hashtable]$Pose,
        [int]$TimeMs,
        [int]$PauseMs
    )

    Write-Host ("Sending pose: Pitch={0} Yaw={1} ArmL={2} ArmR={3}" -f $Pose.Pitch, $Pose.Yaw, $Pose.ArmL, $Pose.ArmR)
    Send-OscAxis -Client $Client -Axis "pitch" -Value $Pose.Pitch -TimeMs $TimeMs
    Send-OscAxis -Client $Client -Axis "yaw" -Value $Pose.Yaw -TimeMs $TimeMs
    Send-OscAxis -Client $Client -Axis "arml" -Value $Pose.ArmL -TimeMs $TimeMs
    Send-OscAxis -Client $Client -Axis "armr" -Value $Pose.ArmR -TimeMs $TimeMs
    Start-Sleep -Milliseconds $PauseMs
}

function Ensure-ReceiverRunning {
    param([string]$ReceiverPath)

    $existing = Get-Process -Name "DollSer" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($existing) {
        Write-Host "Receiver already running."
        return
    }

    if (-not (Test-Path -LiteralPath $ReceiverPath)) {
        throw "Receiver not found: $ReceiverPath"
    }

    Write-Host "Starting receiver: $ReceiverPath"
    Start-Process -FilePath $ReceiverPath -WorkingDirectory $PSScriptRoot | Out-Null
    Start-Sleep -Seconds 2
}

$receiverPath = Join-Path $PSScriptRoot "DollSer.exe"
Ensure-ReceiverRunning -ReceiverPath $receiverPath

$motionTime = 900
$pauseTime = 1300
$client = [System.Net.Sockets.UdpClient]::new()

try {
    Write-Host "Quick gentle test"
    Write-Host "Target: $TargetHost`:$Port"
    if ($DryRun) {
        Write-Host "Dry run enabled. No OSC data will be sent."
    }

    $sequence = @(
        @{ Pitch = 180; Yaw = 180; ArmL = 270; ArmR = 270 },
        @{ Pitch = 186; Yaw = 180; ArmL = 270; ArmR = 270 },
        @{ Pitch = 174; Yaw = 180; ArmL = 270; ArmR = 270 },
        @{ Pitch = 180; Yaw = 180; ArmL = 270; ArmR = 270 },
        @{ Pitch = 180; Yaw = 186; ArmL = 270; ArmR = 270 },
        @{ Pitch = 180; Yaw = 174; ArmL = 270; ArmR = 270 },
        @{ Pitch = 180; Yaw = 180; ArmL = 270; ArmR = 270 },
        @{ Pitch = 180; Yaw = 180; ArmL = 276; ArmR = 276 },
        @{ Pitch = 180; Yaw = 180; ArmL = 264; ArmR = 264 },
        @{ Pitch = 180; Yaw = 180; ArmL = 270; ArmR = 270 }
    )

    foreach ($pose in $sequence) {
        Send-Pose -Client $client -Pose $pose -TimeMs $motionTime -PauseMs $pauseTime
    }

    Write-Host "Test sequence completed."
} finally {
    $client.Dispose()
}
