#Requires -Version 5.1
<#
.SYNOPSIS
  Convert MP4 to GIF with ffmpeg (palettegen / paletteuse).

.DESCRIPTION
  Two-pass GIF conversion. Optional -MaxSizeMB iteratively lowers colors,
  fps, then width until the output is within the size budget (quality-first).

.PARAMETER InputPath
  Source video path (.mp4 / other ffmpeg-readable formats).
  Aliases: -Input, -In (avoid bare $Input — it conflicts with PowerShell's automatic variable).

.PARAMETER Output
  Output .gif path. Default: same directory/name as InputPath with .gif extension.

.PARAMETER Width
  Output width in pixels (height keeps aspect). Default: 480. Ignored as a
  hard floor when -MaxSizeMB needs to shrink further (min 160).

.PARAMETER Fps
  Output frame rate. Default: 12. May be lowered when -MaxSizeMB is set (min 6).

.PARAMETER Colors
  Palette size 2..256. Default: 256. May be lowered when -MaxSizeMB is set (min 32).

.PARAMETER MaxSizeMB
  Optional size budget in megabytes. When set, the script retries with lower
  colors / fps / width until the GIF is <= this size, or fails with a clear
  message. Omit to keep a single encode (no size targeting).

.EXAMPLE
  .\scripts\mp4_to_gif.ps1 -InputPath .\clip.mp4

.EXAMPLE
  # Compress toward ~5MB (typical "keep it small" target)
  .\scripts\mp4_to_gif.ps1 -InputPath .\clip.mp4 -MaxSizeMB 5

.EXAMPLE
  .\scripts\mp4_to_gif.ps1 -InputPath .\clip.mp4 -Output .\out.gif -Width 640 -Fps 15 -Colors 128 -MaxSizeMB 5
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [Alias("Input", "In")]
    [string]$InputPath,

    [Parameter(Mandatory = $false)]
    [Alias("Out")]
    [string]$Output,

    [Parameter(Mandatory = $false)]
    [ValidateRange(16, 4096)]
    [int]$Width = 480,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 60)]
    [int]$Fps = 12,

    [Parameter(Mandatory = $false)]
    [ValidateRange(2, 256)]
    [int]$Colors = 256,

    [Parameter(Mandatory = $false)]
    [ValidateScript({
            if ($_ -eq 0) { return $true }
            if ($_ -lt 0.1 -or $_ -gt 500) {
                throw "MaxSizeMB must be 0 (disabled) or between 0.1 and 500."
            }
            return $true
        })]
    [double]$MaxSizeMB = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Test-CommandExists {
    param([string]$Name)
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Format-SizeMB {
    param([long]$Bytes)
    return ("{0:N2} MB" -f ($Bytes / 1MB))
}

function Invoke-GifEncode {
    param(
        [string]$InputPath,
        [string]$OutputPath,
        [int]$OutWidth,
        [int]$OutFps,
        [int]$OutColors,
        [string]$PalettePath
    )

    $filters = "fps=${OutFps},scale=${OutWidth}:-1:flags=lanczos"

    if (Test-Path -LiteralPath $PalettePath) {
        Remove-Item -LiteralPath $PalettePath -Force
    }
    if (Test-Path -LiteralPath $OutputPath) {
        Remove-Item -LiteralPath $OutputPath -Force
    }

    & ffmpeg -hide_banner -loglevel error -y -i $InputPath `
        -vf "$filters,palettegen=max_colors=${OutColors}:stats_mode=diff" `
        $PalettePath
    if ($LASTEXITCODE -ne 0) {
        throw "palettegen failed (exit $LASTEXITCODE)"
    }

    & ffmpeg -hide_banner -loglevel error -y -i $InputPath -i $PalettePath `
        -lavfi "$filters [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" `
        -loop 0 `
        $OutputPath
    if ($LASTEXITCODE -ne 0) {
        throw "paletteuse failed (exit $LASTEXITCODE)"
    }

    if (-not (Test-Path -LiteralPath $OutputPath)) {
        throw "Output GIF was not created: $OutputPath"
    }

    return (Get-Item -LiteralPath $OutputPath).Length
}

function Get-NextCompressSettings {
    <#
      Quality-first ladder for GIF (perceived quality):
        1) reduce width  — usually best size/quality tradeoff for shareable GIFs
        2) reduce fps    — motion becomes choppier
        3) reduce colors — banding becomes obvious
      When far over budget, width steps are larger to converge faster.
      Returns $null when no further reduction is possible.
    #>
    param(
        [int]$CurWidth,
        [int]$CurFps,
        [int]$CurColors,
        [long]$CurBytes = 0,
        [long]$MaxBytes = 0,
        [int]$MinWidth = 160,
        [int]$MinFps = 6,
        [int]$MinColors = 32
    )

    $ratio = 1.5
    if ($MaxBytes -gt 0 -and $CurBytes -gt 0) {
        $ratio = $CurBytes / [double]$MaxBytes
    }

    if ($CurWidth -gt $MinWidth) {
        # Size roughly scales with pixels; use stronger shrink when far over budget.
        $factor = 0.85
        if ($ratio -ge 4) { $factor = 0.55 }
        elseif ($ratio -ge 2.5) { $factor = 0.65 }
        elseif ($ratio -ge 1.6) { $factor = 0.75 }

        $nextWidth = [Math]::Max($MinWidth, [int][Math]::Floor($CurWidth * $factor))
        if ($nextWidth -ge $CurWidth) {
            $nextWidth = $CurWidth - 16
        }
        if ($nextWidth -lt $MinWidth) {
            $nextWidth = $MinWidth
        }
        if ($nextWidth -lt $CurWidth) {
            return @{
                Width  = $nextWidth
                Fps    = $CurFps
                Colors = $CurColors
                Reason = "width $($CurWidth)->$nextWidth"
            }
        }
    }

    if ($CurFps -gt $MinFps) {
        $step = 2
        if ($ratio -ge 2) { $step = 4 }
        $nextFps = [Math]::Max($MinFps, $CurFps - $step)
        if ($nextFps -lt $CurFps) {
            return @{
                Width  = $CurWidth
                Fps    = $nextFps
                Colors = $CurColors
                Reason = "fps $($CurFps)->$nextFps"
            }
        }
    }

    $colorSteps = @(256, 192, 128, 96, 64, 48, 32) | Where-Object { $_ -ge $MinColors }
    $nextColors = $colorSteps | Where-Object { $_ -lt $CurColors } | Select-Object -First 1
    if ($null -ne $nextColors) {
        return @{
            Width  = $CurWidth
            Fps    = $CurFps
            Colors = [int]$nextColors
            Reason = "colors $($CurColors)->$nextColors"
        }
    }

    return $null
}

if (-not (Test-CommandExists "ffmpeg")) {
    Write-Error "ffmpeg not found in PATH. Install ffmpeg and ensure it is available."
    exit 1
}

$resolvedInput = $InputPath
if (-not [System.IO.Path]::IsPathRooted($resolvedInput)) {
    $resolvedInput = Join-Path (Get-Location) $resolvedInput
}
$resolvedInput = [System.IO.Path]::GetFullPath($resolvedInput)

if (-not (Test-Path -LiteralPath $resolvedInput)) {
    Write-Error "Input file not found: $resolvedInput"
    exit 1
}

if ([string]::IsNullOrWhiteSpace($Output)) {
    $dir = [System.IO.Path]::GetDirectoryName($resolvedInput)
    $base = [System.IO.Path]::GetFileNameWithoutExtension($resolvedInput)
    $Output = Join-Path $dir ($base + ".gif")
}
elseif (-not [System.IO.Path]::IsPathRooted($Output)) {
    $Output = Join-Path (Get-Location) $Output
}
$Output = [System.IO.Path]::GetFullPath($Output)

$outDir = [System.IO.Path]::GetDirectoryName($Output)
if (-not (Test-Path -LiteralPath $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

$palette = Join-Path $outDir ("_palette_" + [guid]::NewGuid().ToString("N") + ".png")
$maxBytes = $null
if ($MaxSizeMB -gt 0) {
    $maxBytes = [long][Math]::Floor($MaxSizeMB * 1MB)
}

$curWidth = $Width
$curFps = $Fps
$curColors = $Colors
$attempt = 0
$lastBytes = [long]0
$succeeded = $false

try {
    Write-Host "Input : $resolvedInput"
    Write-Host "Output: $Output"
    if ($null -ne $maxBytes) {
        Write-Host ("Target: <= {0} ({1} bytes)" -f (Format-SizeMB $maxBytes), $maxBytes)
        Write-Host "Strategy: lower width, then fps, then colors (quality-first)"
    }
    else {
        Write-Host "Size cap: disabled (pass -MaxSizeMB 5 to target ~5MB)"
    }
    Write-Host ""

    while ($true) {
        $attempt++
        Write-Host ("[{0}] encoding width={1} fps={2} colors={3} ..." -f $attempt, $curWidth, $curFps, $curColors)

        $lastBytes = Invoke-GifEncode `
            -InputPath $resolvedInput `
            -OutputPath $Output `
            -OutWidth $curWidth `
            -OutFps $curFps `
            -OutColors $curColors `
            -PalettePath $palette

        $sizeText = Format-SizeMB $lastBytes
        Write-Host ("      size = {0} ({1} bytes)" -f $sizeText, $lastBytes)

        if ($null -eq $maxBytes) {
            $succeeded = $true
            break
        }

        if ($lastBytes -le $maxBytes) {
            $succeeded = $true
            Write-Host ("OK: within budget ({0} <= {1})" -f $sizeText, (Format-SizeMB $maxBytes))
            break
        }

        $next = Get-NextCompressSettings `
            -CurWidth $curWidth `
            -CurFps $curFps `
            -CurColors $curColors `
            -CurBytes $lastBytes `
            -MaxBytes $maxBytes
        if ($null -eq $next) {
            Write-Host ""
            Write-Host (
                ("ERROR: Failed to reach size budget. Current GIF is {0} ({1} bytes), target <= {2} ({3} bytes). " +
                 "Last settings: width={4} fps={5} colors={6}. " +
                 "Try a shorter clip, lower -Width/-Fps/-Colors manually, or raise -MaxSizeMB.") -f `
                    (Format-SizeMB $lastBytes), $lastBytes, (Format-SizeMB $maxBytes), $maxBytes, `
                    $curWidth, $curFps, $curColors
            )
            exit 2
        }

        Write-Host ("      over budget -> next: {0}" -f $next.Reason)
        $curWidth = [int]$next.Width
        $curFps = [int]$next.Fps
        $curColors = [int]$next.Colors
    }
}
finally {
    if (Test-Path -LiteralPath $palette) {
        Remove-Item -LiteralPath $palette -Force -ErrorAction SilentlyContinue
    }
}

if ($succeeded) {
    Write-Host ""
    Write-Host "Done."
    Write-Host ("  File   : {0}" -f $Output)
    Write-Host ("  Size   : {0} ({1} bytes)" -f (Format-SizeMB $lastBytes), $lastBytes)
    Write-Host ("  Params : width={0} fps={1} colors={2}" -f $curWidth, $curFps, $curColors)
    if ($attempt -gt 1) {
        Write-Host ("  Attempts: {0}" -f $attempt)
    }
}
