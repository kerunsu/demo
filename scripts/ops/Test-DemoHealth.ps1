param(
  [string]$BackendOrigin = "http://127.0.0.1:3001",
  [string]$FrontendOrigin = "",
  [int]$TimeoutSec = 5
)

$ErrorActionPreference = "Stop"
$healthUrl = $BackendOrigin.TrimEnd("/") + "/api/health"
$backend = Invoke-RestMethod -Uri $healthUrl -TimeoutSec $TimeoutSec
if ($backend.success -ne $true) {
  throw "Backend health failed at $healthUrl"
}

Write-Output "Backend health OK: $healthUrl"
Write-Output ("Providers: chat={0} tts={1}" -f $backend.data.voice.chatProvider, $backend.data.voice.ttsProvider)

if ($FrontendOrigin -ne "") {
  $frontend = Invoke-WebRequest -Uri $FrontendOrigin -TimeoutSec $TimeoutSec
  if ($frontend.StatusCode -lt 200 -or $frontend.StatusCode -ge 400) {
    throw "Frontend health failed at $FrontendOrigin"
  }
  Write-Output "Frontend health OK: $FrontendOrigin"
}
