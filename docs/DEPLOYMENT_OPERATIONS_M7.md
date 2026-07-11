# M7-A Deployment And Operations Runbook

This runbook prepares deployment operations for the local dual-screen robot demo. It does not enable real cloud STT, TTS, LLM, safety-review providers, or child raw-media persistence.

## Current Fact

- The backend serves HTTP APIs under `/api` and WebSocket events under `/ws`.
- The frontend supports `/child` and `/robot` paths and reads `VITE_API_BASE_URL` plus `VITE_WS_URL`.
- Default M7-A provider settings are rule/mock/offline-safe: `AI_CHAT_PROVIDER=rule`, `AI_TTS_PROVIDER=none`, `VOICE_STT_PROVIDER=mock`, `VOICE_TTS_PROVIDER=mock`.
- Real robot, LAN dual-host, microphone, speaker, camera, classroom noise, and long-run field acceptance remain `ENVIRONMENT_PENDING`.

## Files

- `deploy/production.env.example`: backend production environment template without real secrets.
- `deploy/frontend.env.example`: frontend runtime template for LAN backend and WebSocket URLs.
- `scripts/ops/Start-DemoProduction.ps1`: starts the built backend and can also start frontend preview plus Python Voice Service for approved local real-provider rehearsal; writes logs plus pid files under `.runtime/logs`.
- `scripts/ops/Stop-DemoProduction.ps1`: stops backend, frontend preview, and Python Voice Service pids recorded by the start script.
- `scripts/ops/Test-DemoHealth.ps1`: checks backend `/api/health` and optional frontend reachability.
- `scripts/ops/Backup-DemoRuntime.ps1`: creates a zip of deployment templates and progress anchors.
- `scripts/ops/Clear-DemoRuntimeData.ps1`: confirms before deleting runtime log/backup folders and refuses paths outside the project root.
- `scripts/ops/Collect-DemoDiagnostics.ps1`: writes backend, Python Voice Service, SQLite, WebSocket, model-file, frontend, git, Node, npm, and manual permission diagnostics.
- `docs/REAL_PROVIDER_FIELD_ACCEPTANCE_CHECKLIST.md`: step-by-step local real-provider and dual-host LAN field checklist.
- `docs/ACCEPTANCE_LOG_TEMPLATE.md`: unified acceptance log template for environment, providers, models, session, latency, degradation, and reproduction steps.

## Build

```powershell
npm install
npm --prefix backend install
npm --prefix frontend install
npm run build
```

## Backend Start

Copy `deploy/production.env.example` outside Git-tracked paths and set host-specific values. For LAN rehearsal, keep providers on rule/mock defaults unless a separate safety review approves real providers.

```powershell
$env:BACKEND_HOST="0.0.0.0"
$env:BACKEND_PORT="3001"
$env:PUBLIC_BACKEND_ORIGIN="http://SERVER_LAN_IP:3001"
$env:CORS_ORIGIN="http://ROBOT_LAN_IP:5173"
$env:AI_CHAT_PROVIDER="rule"
$env:AI_TTS_PROVIDER="none"
$env:VOICE_STT_PROVIDER="mock"
$env:VOICE_TTS_PROVIDER="mock"
powershell -ExecutionPolicy Bypass -File scripts\ops\Start-DemoProduction.ps1 -PublicBackendOrigin $env:PUBLIC_BACKEND_ORIGIN -CorsOrigin $env:CORS_ORIGIN
```

## Frontend Build And Launch

Set frontend LAN URLs before building the frontend:

```powershell
$env:VITE_API_BASE_URL="http://SERVER_LAN_IP:3001/api"
$env:VITE_WS_URL="ws://SERVER_LAN_IP:3001/ws"
npm --prefix frontend run build
```

Serve `frontend/dist` with the selected static-file host, then open:

- Child screen: `http://ROBOT_LAN_IP:5173/child`
- Robot screen: `http://ROBOT_LAN_IP:5173/robot`

## Local Real-Provider Rehearsal Start

Use only after the operator confirms the local Vosk/Piper model files exist and the rehearsal is approved. This starts backend, frontend preview, Python Voice Service, SQLite config, local Vosk, local Piper, and local attention provider configuration together; it does not claim microphone, speaker, camera, or LAN acceptance.

```powershell
npm run build
powershell -ExecutionPolicy Bypass -File scripts\ops\Start-DemoProduction.ps1 `
  -RealLocalProviders `
  -StartVoiceService `
  -StartFrontend `
  -BackendHost 127.0.0.1 `
  -PublicBackendOrigin http://127.0.0.1:3001 `
  -CorsOrigin http://127.0.0.1:5173 `
  -FrontendHost 127.0.0.1 `
  -FrontendPort 5173
```

Stop all started processes:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ops\Stop-DemoProduction.ps1
```

## Health Checks

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ops\Test-DemoHealth.ps1 -BackendOrigin http://SERVER_LAN_IP:3001 -FrontendOrigin http://ROBOT_LAN_IP:5173
```

Expected backend health facts:

- `voice.chatProvider` is `rule` unless explicitly approved otherwise.
- `voice.ttsProvider` is `none` for chat TTS.
- `voice.sttProvider.externalNetworkCalled` is `false` for mock/local rehearsal.
- `voice.speechTtsProvider.externalNetworkCalled` is `false` for mock/local rehearsal.

## Logs

- Backend stdout: `.runtime/logs/backend-*.out.log`
- Backend stderr: `.runtime/logs/backend-*.err.log`
- Backend pid: `.runtime/logs/backend.pid`

Log files are ignored by Git. Do not paste child raw text, API keys, raw audio, raw video, or full provider errors into issue trackers or commits.

## Backup And Delete

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ops\Backup-DemoRuntime.ps1
powershell -ExecutionPolicy Bypass -File scripts\ops\Clear-DemoRuntimeData.ps1 -Confirm
```

The clear script is intentionally confirmable and refuses to remove paths outside the project root.

## Diagnostics

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ops\Collect-DemoDiagnostics.ps1 -BackendOrigin http://SERVER_LAN_IP:3001
```

For local real-provider rehearsal:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ops\Collect-DemoDiagnostics.ps1 `
  -BackendOrigin http://127.0.0.1:3001 `
  -FrontendOrigin http://127.0.0.1:5173 `
  -VoiceServiceOrigin http://127.0.0.1:8765 `
  -WebSocketUrl "ws://127.0.0.1:3001/ws?sessionId=diagnostics&screenRole=operator&clientId=diagnostics"
```

Microphone and camera permission checks are always reported as `MANUAL_ACCEPTANCE_REQUIRED` because browser/device permission prompts cannot be accepted as automated proof.

Attach only reviewed diagnostic output. Remove local usernames, IPs, secrets, and any child-identifying data before sharing.

## Rollback

1. Stop the backend with `Stop-DemoProduction.ps1`.
2. Restore the previous Git commit or deployed artifact.
3. Re-run `npm run build`.
4. Start the backend with the previous environment values.
5. Run `Test-DemoHealth.ps1`.

## Environment Pending

- Real robot browser terminal.
- Dual-host LAN and firewall validation.
- Microphone, speaker, and camera device validation.
- Classroom noise and lighting validation.
- Local TTS human listening review and production license review.
- Long-run stability, crash recovery, retention, and release checklist coverage in M7-B.
