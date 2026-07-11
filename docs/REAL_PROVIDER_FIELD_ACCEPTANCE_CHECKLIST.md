# Real Provider And Dual-Host Field Acceptance Checklist

Audit date: 2026-06-14

This checklist is for local real-provider rehearsal and dual-host LAN field acceptance after `FINAL-A` through `FINAL-D`. It does not claim that real hardware, LAN, microphone, speaker, camera, classroom noise, long-run stability, human listening quality, or model licenses have passed.

Use `docs/ACCEPTANCE_LOG_TEMPLATE.md` to record each run.

## 0. Preflight

- [ ] 当前事实: confirm Git history contains `aeef4d7`, `e4a285a`, `118e0b5`, and `66fa2b0`.
- [ ] 当前事实: run `git status --short` and record whether the worktree is clean.
- [ ] 当前事实: confirm `.runtime\models\vosk\vosk-model-small-cn-0.22` exists on the operator machine.
- [ ] 当前事实: confirm `.runtime\models\piper\zh_CN-huayan-medium.onnx` and `.runtime\models\piper\zh_CN-huayan-medium.onnx.json` exist.
- [ ] 当前事实: confirm `.runtime\demo.sqlite3` is the intended rehearsal database or set `DEMO_SQLITE_DB_PATH` to a host-specific runtime path.
- [ ] 当前事实: copy deployment templates outside Git-tracked paths before adding machine-specific values.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: verify microphone, speaker, and camera are connected to the target browser host.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: verify Vosk and Piper model license sources and redistribution constraints.

## 1. Start Local Real Providers On One Host

Use this for the local real voice and camera rehearsal.

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

Checklist:

- [ ] 当前事实: backend starts and writes `.runtime\logs\backend.pid`.
- [ ] 当前事实: frontend preview starts and writes `.runtime\logs\frontend.pid`.
- [ ] 当前事实: Python Voice Service starts and writes `.runtime\logs\voice-service.pid`.
- [ ] 当前事实: backend provider config reports `VOICE_STT_PROVIDER=local`, `VOICE_TTS_PROVIDER=local`, `ATTENTION_PROVIDER=local`, and `DEMO_STORAGE_PROVIDER=sqlite`.
- [ ] 当前事实: Python Voice Service `/health` reports `sttProvider=local-vosk` and `ttsProvider=local-piper`.
- [ ] 当前事实: backend `/api/health` is reachable.
- [ ] 当前事实: frontend `/child` and `/robot` are reachable.
- [ ] 当前事实: WebSocket `ws://127.0.0.1:3001/ws?sessionId=diagnostics&screenRole=operator&clientId=diagnostics` connects.

Run diagnostics:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ops\Collect-DemoDiagnostics.ps1 `
  -BackendOrigin http://127.0.0.1:3001 `
  -FrontendOrigin http://127.0.0.1:5173 `
  -VoiceServiceOrigin http://127.0.0.1:8765 `
  -WebSocketUrl "ws://127.0.0.1:3001/ws?sessionId=diagnostics&screenRole=operator&clientId=diagnostics"
```

## 2. Local Real Voice And Camera Rehearsal

- [ ] MANUAL_ACCEPTANCE_REQUIRED: open `http://127.0.0.1:5173/child`.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: open `http://127.0.0.1:5173/robot`.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: grant microphone permission and record browser, selected device, prompt wording, noise level, and whether transcript is usable.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: speak at least three short Mandarin utterances and record STT latency, transcript, confidence if shown, and any degradation state.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: verify Piper audio plays on `/robot` after a safe reply; record first-play autoplay behavior, audible glitches, and perceived child-facing tone.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: grant camera permission and record browser, selected device, lighting, face count, image quality, and degradation state.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: deny microphone once and confirm the system degrades without duplicate turn advancement.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: deny camera once and confirm the report treats it as device/data quality, not negative child behavior.
- [ ] 当前事实: generate a report and confirm provider summary distinguishes real, mock, degraded, and missing evidence.
- [ ] 当前事实: stop services with `scripts\ops\Stop-DemoProduction.ps1`.

## 3. Dual-Host LAN Rehearsal

Use one server host for backend, Python Voice Service, SQLite, and frontend preview. Use one browser/robot host for `/child` and `/robot`.

On the server host:

```powershell
$env:SERVER_LAN_IP="REPLACE_WITH_SERVER_IP"
$env:ROBOT_LAN_IP="REPLACE_WITH_ROBOT_IP"
npm run build
powershell -ExecutionPolicy Bypass -File scripts\ops\Start-DemoProduction.ps1 `
  -RealLocalProviders `
  -StartVoiceService `
  -StartFrontend `
  -BackendHost 0.0.0.0 `
  -PublicBackendOrigin "http://$env:SERVER_LAN_IP:3001" `
  -CorsOrigin "http://$env:SERVER_LAN_IP:5173,http://$env:ROBOT_LAN_IP:5173" `
  -FrontendHost 0.0.0.0 `
  -FrontendPort 5173 `
  -FrontendApiBaseUrl "http://$env:SERVER_LAN_IP:3001/api" `
  -FrontendWsUrl "ws://$env:SERVER_LAN_IP:3001/ws"
```

Checklist:

- [ ] MANUAL_ACCEPTANCE_REQUIRED: from the robot/browser host, open `http://SERVER_LAN_IP:5173/child`.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: from the robot/browser host, open `http://SERVER_LAN_IP:5173/robot`.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: from the robot/browser host, confirm Windows firewall allows backend `3001`, frontend `5173`, and WebSocket traffic.
- [ ] 当前事实: run diagnostics with LAN origins from the server host.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: record LAN round-trip behavior for `/api/health`, `/child`, `/robot`, and WebSocket reconnect.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: refresh `/robot` during a session and confirm no duplicate audio, duplicate ACK, or duplicate next-question advance.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: unplug or block network briefly, then restore and record whether snapshot/reconnect recovers.

## 4. 30-Minute And 2-Hour Stability

Before each run:

```powershell
npm test
npm run build
git diff --check
```

30-minute run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ops\Invoke-LongRunSmoke.ps1 `
  -BackendOrigin http://SERVER_LAN_IP:3001 `
  -DurationMinutes 30 `
  -IntervalSeconds 30
```

2-hour run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ops\Invoke-LongRunSmoke.ps1 `
  -BackendOrigin http://SERVER_LAN_IP:3001 `
  -DurationMinutes 120 `
  -IntervalSeconds 30
```

Checklist:

- [ ] MANUAL_ACCEPTANCE_REQUIRED: backend remains reachable for the full run.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: frontend tabs remain usable without manual restart.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: no raw audio, raw video, raw camera frame, API key, or full sensitive transcript appears in logs, screenshots, Git status, or reports.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: log size remains below the selected field limit.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: at least three sequential sessions complete with separate session ids.

## 5. Fault Recovery

- [ ] MANUAL_ACCEPTANCE_REQUIRED: restart backend during a session; record whether `/child` and `/robot` recover or show explicit unavailable state.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: refresh `/robot`; record snapshot recovery and duplicate ACK behavior.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: disconnect WebSocket; record reconnect timing and missing-event or snapshot behavior.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: stop Python Voice Service; record STT/TTS degradation and recovery after restart.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: rename or move one model path in a copy of the runtime environment; confirm diagnostics fail with a clear missing-model message.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: fill or lock the SQLite path in a disposable rehearsal copy; confirm failure is visible and no raw media is persisted.

## 6. Human Listening And License

- [ ] MANUAL_ACCEPTANCE_REQUIRED: Mandarin listener reviews Piper intelligibility, speed, pronunciation, loudness, and child-facing tone.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: project owner records whether Piper voice quality is acceptable, acceptable with caveats, or blocked.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: review Piper model license and deployment constraints.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: review Vosk model license and deployment constraints.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: confirm no formal scoring, percentile, diagnosis, clinical conclusion, or professional interpretation is released without approved rules.

## 7. Release Blockers To Close

- [ ] MANUAL_ACCEPTANCE_REQUIRED: dual-host LAN microphone, camera, speaker, browser autoplay, firewall, and WebSocket reconnect acceptance.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: 30-minute and 2-hour stability evidence.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: backup, retention, clear-runtime, and rollback rehearsal on the target Windows host.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: Vosk and Piper license review.
- [ ] MANUAL_ACCEPTANCE_REQUIRED: human listening review for Piper.
- [ ] OWNER_REQUIRED: child-facing safety fallback wording and escalation policy.
- [ ] OWNER_REQUIRED: any formal scoring or professional interpretation rules.
