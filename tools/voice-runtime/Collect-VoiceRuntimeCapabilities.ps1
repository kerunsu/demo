param(
  [string]$OutputDir = ".runtime",
  [switch]$SelfTest
)

$ErrorActionPreference = "Continue"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function New-CheckResult {
  param(
    [string]$Name,
    [scriptblock]$Body
  )
  try {
    & $Body
  } catch {
    [ordered]@{
      name = $Name
      status = "error"
      error = $_.Exception.Message
    }
  }
}

function Get-CommandInfo {
  param(
    [string]$Name,
    [string[]]$VersionArgs = @("--version")
  )
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  if (-not $cmd) {
    return [ordered]@{
      name = $Name
      present = $false
      path = $null
      version = $null
      error = "command not found"
    }
  }

  $versionText = $null
  $versionError = $null
  try {
    $output = & $cmd.Source @VersionArgs 2>&1 | Select-Object -First 3
    $versionText = ($output -join " ").Trim()
  } catch {
    $versionError = $_.Exception.Message
  }

  [ordered]@{
    name = $Name
    present = $true
    path = $cmd.Source
    version = $versionText
    error = $versionError
  }
}

function Convert-Bytes {
  param([Nullable[double]]$Bytes)
  if ($null -eq $Bytes) { return $null }
  [math]::Round(($Bytes / 1GB), 2)
}

function Get-ValueCount {
  param($Value)
  if ($null -eq $Value) { return 0 }
  @($Value).Count
}

function Get-RegistryValueSafe {
  param(
    [string]$Path,
    [string]$Name
  )
  try {
    $value = Get-ItemProperty -Path $Path -Name $Name -ErrorAction Stop
    return $value.$Name
  } catch {
    return $null
  }
}

function Get-BrowserInfo {
  param(
    [string]$Name,
    [string]$RegistryPath
  )
  $path = Get-RegistryValueSafe -Path $RegistryPath -Name "(default)"
  if (-not $path) {
    $path = Get-RegistryValueSafe -Path $RegistryPath -Name "Path"
  }
  if (-not $path -or -not (Test-Path -LiteralPath $path)) {
    return [ordered]@{
      name = $Name
      present = $false
      path = $path
      version = $null
    }
  }
  $item = Get-Item -LiteralPath $path -ErrorAction SilentlyContinue
  [ordered]@{
    name = $Name
    present = $true
    path = $path
    version = if ($item) { $item.VersionInfo.ProductVersion } else { $null }
  }
}

function Get-AudioEndpointRegistry {
  param([string]$Kind)
  $base = "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\$Kind"
  if (-not (Test-Path $base)) { return @() }
  $endpoints = @()
  foreach ($endpoint in Get-ChildItem -Path $base -ErrorAction SilentlyContinue) {
    $state = Get-RegistryValueSafe -Path $endpoint.PSPath -Name "DeviceState"
    $propsPath = Join-Path $endpoint.PSPath "Properties"
    $friendlyName = Get-RegistryValueSafe -Path $propsPath -Name "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
    $deviceDesc = Get-RegistryValueSafe -Path $propsPath -Name "{b3f8fa53-0004-438e-9003-51a46e139bfc4},6"
    $endpoints += [ordered]@{
      id = $endpoint.PSChildName
      name = if ($friendlyName) { $friendlyName } else { $deviceDesc }
      deviceDescription = $deviceDesc
      stateCode = $state
      state = if ($state -eq 1) { "active" } elseif ($null -eq $state) { "unknown" } else { "not_active_or_unknown" }
      sampleRates = "unknown"
      channels = "unknown"
    }
  }
  $endpoints
}

function Collect-Capabilities {
  param([string]$OutputDir)

  $repoPath = (Get-Location).Path
  $hostIdentity = [ordered]@{
    classification = "DEVELOPMENT_SERVER_BASELINE"
    reason = "Current development-stage host is treated as the high-performance server baseline. It is not a final robot endpoint benchmark."
    hostname = $env:COMPUTERNAME
    repositoryPath = $repoPath
    robotHostCriteriaFromDocs = "Windows robot host with microphone, speaker, and two displays; backend runs on another LAN host."
  }

  $os = New-CheckResult "os" {
    $computer = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
    $operatingSystem = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    $drives = Get-CimInstance Win32_LogicalDisk -Filter "DriveType=3" -ErrorAction Stop | ForEach-Object {
      [ordered]@{
        name = $_.DeviceID
        sizeGB = Convert-Bytes $_.Size
        freeGB = Convert-Bytes $_.FreeSpace
      }
    }
    [ordered]@{
      windowsCaption = $operatingSystem.Caption
      windowsVersion = $operatingSystem.Version
      buildNumber = $operatingSystem.BuildNumber
      architecture = $operatingSystem.OSArchitecture
      hostname = $env:COMPUTERNAME
      powershellVersion = $PSVersionTable.PSVersion.ToString()
      timezone = (Get-TimeZone).Id
      disks = @($drives)
      manufacturer = $computer.Manufacturer
      model = $computer.Model
    }
  }

  $cpuMemory = New-CheckResult "cpuMemory" {
    $cpu = Get-CimInstance Win32_Processor -ErrorAction Stop | Select-Object -First 1
    $computer = Get-CimInstance Win32_ComputerSystem -ErrorAction Stop
    $operatingSystem = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
    [ordered]@{
      cpuName = $cpu.Name
      physicalCores = $cpu.NumberOfCores
      logicalCores = $cpu.NumberOfLogicalProcessors
      totalMemoryGB = Convert-Bytes ([double]$computer.TotalPhysicalMemory)
      availableMemoryGB = Convert-Bytes ([double]$operatingSystem.FreePhysicalMemory * 1KB)
    }
  }

  $gpu = New-CheckResult "gpu" {
    $controllers = Get-CimInstance Win32_VideoController -ErrorAction Stop | ForEach-Object {
      $name = if ($_.Name) { $_.Name } else { "" }
      [ordered]@{
        name = $_.Name
        vendor = if ($_.AdapterCompatibility) { $_.AdapterCompatibility } else { "unknown" }
        driverVersion = $_.DriverVersion
        adapterRAMGB = Convert-Bytes ([double]$_.AdapterRAM)
        currentResolution = if ($_.CurrentHorizontalResolution -and $_.CurrentVerticalResolution) { "$($_.CurrentHorizontalResolution)x$($_.CurrentVerticalResolution)" } else { "unknown" }
        isVirtualDisplay = ($name -match "Virtual|Idd|Indirect|Mirror")
        isIntegratedGpu = if ($name -match "Intel|Radeon\(TM\) Graphics|AMD Radeon Graphics|Iris|UHD|Arc\(TM\) 140T") { "likely" } else { "unknown" }
        isDiscreteGpu = if ($name -match "NVIDIA|GeForce|RTX|GTX|Quadro|Radeon RX|Radeon Pro|Arc\(TM\) A") { "likely" } else { "unknown" }
      }
    }
    $nvidiaSmi = Get-CommandInfo "nvidia-smi"
    $nvcc = Get-CommandInfo "nvcc"
    [ordered]@{
      controllers = @($controllers)
      cuda = [ordered]@{
        nvidiaSmi = $nvidiaSmi
        nvcc = $nvcc
        available = ($nvidiaSmi.present -or $nvcc.present)
        note = "CUDA availability is based only on local tool presence; no inference benchmark was run."
      }
      directML = [ordered]@{
        status = "unknown"
        note = "DirectML cannot be confirmed by GPU name alone. Verify in M4-002 with ONNX Runtime DirectML or a minimal DirectML probe."
      }
      discreteGpuAvailable = (($controllers | Where-Object { -not $_.isVirtualDisplay -and $_.isDiscreteGpu -eq "likely" }).Count -gt 0)
      integratedGpuAvailable = (($controllers | Where-Object { -not $_.isVirtualDisplay -and $_.isIntegratedGpu -eq "likely" }).Count -gt 0)
    }
  }

  $audio = New-CheckResult "audio" {
    $soundDevices = Get-CimInstance Win32_SoundDevice -ErrorAction Stop | ForEach-Object {
      [ordered]@{
        name = $_.Name
        manufacturer = $_.Manufacturer
        status = $_.Status
        pnpDeviceId = $_.PNPDeviceID
      }
    }
    $captureEndpoints = Get-AudioEndpointRegistry "Capture"
    $renderEndpoints = Get-AudioEndpointRegistry "Render"
    [ordered]@{
      inputDevices = @($captureEndpoints)
      outputDevices = @($renderEndpoints)
      defaultMicrophone = "unknown"
      defaultSpeaker = "unknown"
      soundDevices = @($soundDevices)
      note = "No recording was started. Default endpoint and exact sample rate/channel support may require an interactive Windows audio API check."
    }
  }

  $displayBrowser = New-CheckResult "displayBrowser" {
    $videoControllers = Get-CimInstance Win32_VideoController -ErrorAction Stop | ForEach-Object {
      [ordered]@{
        name = $_.Name
        resolution = if ($_.CurrentHorizontalResolution -and $_.CurrentVerticalResolution) { "$($_.CurrentHorizontalResolution)x$($_.CurrentVerticalResolution)" } else { "unknown" }
      }
    }
    $desktopMonitors = Get-CimInstance Win32_DesktopMonitor -ErrorAction Stop | ForEach-Object {
      [ordered]@{
        name = $_.Name
        screenWidth = $_.ScreenWidth
        screenHeight = $_.ScreenHeight
        status = $_.Status
      }
    }
    $defaultBrowserProgId = Get-RegistryValueSafe -Path "HKCU:\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice" -Name "ProgId"
    [ordered]@{
      displayCount = @($desktopMonitors).Count
      displays = @($desktopMonitors)
      videoControllerResolutions = @($videoControllers)
      defaultBrowserProgId = if ($defaultBrowserProgId) { $defaultBrowserProgId } else { "unknown" }
      edge = Get-BrowserInfo "Microsoft Edge" "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"
      chrome = Get-BrowserInfo "Google Chrome" "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe"
      webPlatformSupport = [ordered]@{
        webAudio = "expected in current Edge/Chrome; manual browser permission test still required"
        mediaDevices = "requires HTTPS or localhost and user permission; not exercised by this script"
        webSocket = "expected in current Edge/Chrome; app-level connectivity covered by npm tests"
      }
    }
  }

  $runtime = New-CheckResult "runtime" {
    $python = Get-CommandInfo "python" @("--version")
    $pip = Get-CommandInfo "pip" @("--version")
    $node = Get-CommandInfo "node" @("--version")
    $npm = Get-CommandInfo "npm" @("--version")
    $ffmpeg = Get-CommandInfo "ffmpeg" @("-version")
    $git = Get-CommandInfo "git" @("--version")
    $vcRuntime64 = Get-RegistryValueSafe -Path "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64" -Name "Version"
    $vcRuntime86 = Get-RegistryValueSafe -Path "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x86" -Name "Version"
    $onnxRuntime = [ordered]@{ pythonImport = "unknown"; version = $null; error = $null }
    if ($python.present) {
      try {
        $onnxOutput = & $python.path -c "import onnxruntime as ort; print(ort.__version__); print(','.join(ort.get_available_providers()))" 2>&1
        if ($LASTEXITCODE -eq 0) {
          $onnxRuntime.pythonImport = "present"
          $onnxRuntime.version = $onnxOutput[0]
          $onnxRuntime.providers = if ($onnxOutput.Count -gt 1) { $onnxOutput[1] } else { "unknown" }
        } else {
          $onnxRuntime.pythonImport = "not_present_or_failed"
          $onnxRuntime.error = ($onnxOutput -join " ").Trim()
        }
      } catch {
        $onnxRuntime.pythonImport = "not_present_or_failed"
        $onnxRuntime.error = $_.Exception.Message
      }
    }
    [ordered]@{
      node = $node
      npm = $npm
      python = $python
      pip = $pip
      ffmpeg = $ffmpeg
      git = $git
      visualCppRuntime = [ordered]@{
        x64 = if ($vcRuntime64) { $vcRuntime64 } else { "unknown" }
        x86 = if ($vcRuntime86) { $vcRuntime86 } else { "unknown" }
      }
      cuda = [ordered]@{
        nvidiaSmiPresent = (Get-CommandInfo "nvidia-smi").present
        nvccPresent = (Get-CommandInfo "nvcc").present
      }
      onnxRuntime = $onnxRuntime
      directML = [ordered]@{
        status = "unknown"
        note = "No DirectML package or benchmark was installed or executed."
      }
    }
  }

  $levels = @()
  if ($gpu.discreteGpuAvailable) { $levels += "DISCRETE_GPU_AVAILABLE" }
  if ($gpu.integratedGpuAvailable) { $levels += "INTEGRATED_GPU_AVAILABLE" }
  if (-not $gpu.discreteGpuAvailable -and -not $gpu.integratedGpuAvailable) { $levels += "CPU_ONLY_BASELINE" }
  $inputDeviceCount = Get-ValueCount $audio.inputDevices
  $outputDeviceCount = Get-ValueCount $audio.outputDevices
  if ($inputDeviceCount -eq 0 -or $outputDeviceCount -eq 0) { $levels += "AUDIO_DEVICE_INCOMPLETE" }
  if ($inputDeviceCount -gt 0 -and $outputDeviceCount -gt 0 -and $runtime.node.present -and $runtime.npm.present) { $levels += "READY_FOR_M4_SPIKE" }
  if ($levels.Count -eq 0) { $levels += "UNKNOWN" }

  $result = [ordered]@{
    schemaVersion = "m4.voiceRuntimeCapabilities.v1"
    generatedAt = (Get-Date).ToString("o")
    safety = [ordered]@{
      noRecording = $true
      noExternalNetwork = $true
      noModelDownload = $true
      noApiKeysRead = $true
      noSystemSettingsChanged = $true
    }
    hostIdentity = $hostIdentity
    os = $os
    cpuMemory = $cpuMemory
    gpu = $gpu
    audio = $audio
    displayBrowser = $displayBrowser
    runtime = $runtime
    capabilityLevels = @($levels)
    m4_002_inputs = [ordered]@{
      canStartSpikeOnThisHost = ($levels -contains "READY_FOR_M4_SPIKE")
      benchmarkStillRequired = @("VAD latency and false triggers", "STT accuracy and real-time factor", "TTS latency and intelligibility", "DirectML/CUDA/CPU provider viability", "browser permission/autoplay behavior")
      robotHostStillRequired = ($hostIdentity.classification -ne "ROBOT_HOST_MEASURED")
    }
  }

  New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
  $jsonPath = Join-Path $OutputDir "voice-capabilities.json"
  $txtPath = Join-Path $OutputDir "voice-capabilities.txt"
  $json = $result | ConvertTo-Json -Depth 12
  Set-Content -LiteralPath $jsonPath -Value $json -Encoding UTF8

  $summary = @()
  $summary += "M4-001 Voice Runtime Capability Summary"
  $summary += "Generated: $($result.generatedAt)"
  $summary += "Host classification: $($result.hostIdentity.classification)"
  $summary += "Windows: $($result.os.windowsCaption) $($result.os.windowsVersion) $($result.os.architecture)"
  $summary += "CPU: $($result.cpuMemory.cpuName); cores physical/logical $($result.cpuMemory.physicalCores)/$($result.cpuMemory.logicalCores)"
  $summary += "Memory: total $($result.cpuMemory.totalMemoryGB) GB; available $($result.cpuMemory.availableMemoryGB) GB"
  $summary += "GPU: $((@($result.gpu.controllers) | ForEach-Object { $_.name }) -join '; ')"
  $summary += "Audio inputs: $(@($result.audio.inputDevices).Count); outputs: $(@($result.audio.outputDevices).Count)"
  $summary += "Displays: $($result.displayBrowser.displayCount)"
  $summary += "Runtime: node=$($result.runtime.node.version); npm=$($result.runtime.npm.version); python=$($result.runtime.python.version); ffmpegPresent=$($result.runtime.ffmpeg.present)"
  $summary += "Capability levels: $($result.capabilityLevels -join ', ')"
  $summary += "Safety: no recording, no external API, no model download."
  Set-Content -LiteralPath $txtPath -Value $summary -Encoding UTF8

  [ordered]@{
    result = $result
    jsonPath = $jsonPath
    textPath = $txtPath
  }
}

function Invoke-SelfTest {
  $testDir = Join-Path ([System.IO.Path]::GetTempPath()) ("voice-runtime-selftest-" + [Guid]::NewGuid().ToString("N"))
  $first = Collect-Capabilities -OutputDir $testDir
  $second = Collect-Capabilities -OutputDir $testDir
  $parsed = Get-Content -LiteralPath $first.jsonPath -Encoding UTF8 -Raw | ConvertFrom-Json
  $missingCommand = Get-CommandInfo "__codex_missing_ffmpeg_probe__"
  $checks = @(
    [ordered]@{ name = "json_parse"; passed = ($null -ne $parsed.schemaVersion) },
    [ordered]@{ name = "output_directory_created"; passed = (Test-Path -LiteralPath $testDir) },
    [ordered]@{ name = "repeat_execution_safe"; passed = ((Test-Path -LiteralPath $second.jsonPath) -and (Test-Path -LiteralPath $second.textPath)) },
    [ordered]@{ name = "missing_tool_degrades"; passed = (-not $missingCommand.present) },
    [ordered]@{ name = "audio_failure_field_available"; passed = ($null -ne $parsed.audio.note -or $null -ne $parsed.audio.status) },
    [ordered]@{ name = "gpu_tool_absence_nonfatal"; passed = (($null -ne $parsed.gpu.cuda.nvidiaSmi.present) -or ($parsed.gpu.status -eq "error")) }
  )
  $failed = @($checks | Where-Object { -not $_.passed })
  [ordered]@{
    status = if ($failed.Count -eq 0) { "PASS" } else { "FAIL" }
    outputDir = $testDir
    checks = $checks
  }
}

if ($SelfTest) {
  $selfTestResult = Invoke-SelfTest
  $selfTestResult | ConvertTo-Json -Depth 8
  if ($selfTestResult.status -ne "PASS") { exit 1 }
  exit 0
}

$collection = Collect-Capabilities -OutputDir $OutputDir
$collection.result | ConvertTo-Json -Depth 12
Write-Host ""
Write-Host "Summary written to $($collection.textPath)"
Write-Host "JSON written to $($collection.jsonPath)"
