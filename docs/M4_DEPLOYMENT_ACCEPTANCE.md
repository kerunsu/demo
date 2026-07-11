# M4 Deployment Acceptance

## Status

- 当前事实：M4 code and automated development-environment validation are complete through `M4-013`.
- 当前事实：this Codex run cannot access the real robot browser terminal, target microphone, target speaker, LAN dual-device site, classroom noise, or long-running field setup.
- M4-014 status: `ENVIRONMENT_PENDING`.
- Code status before field validation: `COMPLETE_CODE`.

## Development Machine Validation Completed

These checks can be repeated on the development server:

```bash
npm run test:backend
npm run test:frontend
npm test
npm run build
python tools\voice-service\voice_service.test.py
python -m py_compile tools\voice-service\voice_service.py
git diff --check
```

Expected result: all commands pass. `git diff --check` may print Windows LF/CRLF warnings, but must not report whitespace errors.

## Deployment Topology To Validate

```text
Robot browser terminal
  /child microphone and camera capture
  /robot GIF animation and audio playback
        |
        | LAN
        v
High-performance server
  backend media ingress
  STT Provider
  dialogue/rule orchestration
  TTS Provider
  WebSocket/domain events
  Python voice service for local Vosk/Piper
```

当前事实：the robot terminal must not run VAD, STT, TTS, visual analysis, or model inference in the current M4 route.

## Start Commands

Backend server on the high-performance server:

```bash
BACKEND_HOST=0.0.0.0 BACKEND_PORT=3001 PUBLIC_BACKEND_ORIGIN=http://<server-lan-ip>:3001 CORS_ORIGIN=http://<robot-lan-origin> npm --prefix backend run dev
```

Frontend on the robot browser terminal or development browser:

```bash
VITE_API_BASE_URL=http://<server-lan-ip>:3001/api VITE_WS_URL=ws://<server-lan-ip>:3001/ws npm --prefix frontend run dev -- --host 0.0.0.0
```

Optional local voice service on the high-performance server:

```bash
python tools\voice-service\voice_service.py
```

Health checks:

```bash
curl http://<server-lan-ip>:3001/api/health
curl http://<server-lan-ip>:3001/api/voice-metrics/<sessionId>
```

## Manual Acceptance Checklist

Record each item as `PASS`, `FAIL`, `BLOCKED`, or `NOT_TESTED`.

| Area | Check | Result | Evidence |
| -- | -- | -- | -- |
| Server startup | Backend starts on LAN host/port and `/api/health` is reachable from robot terminal. |  |  |
| Frontend startup | `/child` opens on the child display and `/robot` opens on the robot display. |  |  |
| Browser permissions | `/child` can request microphone permission without browser or OS denial. |  |  |
| Audio capture | Developer-authorized test speech produces media stream start/chunk/finish metrics. |  |  |
| STT local | Local Vosk provider returns transcript or explicit degradation. |  |  |
| STT cloud optional | Cloud STT runs only when credentials and explicit test approval exist; otherwise remains `CLOUD_CREDENTIALS_PENDING`. |  |  |
| Reply orchestration | Transcript leads to exactly one rule/chat reply for a turn. |  |  |
| TTS local | Local Piper provider returns playable audio or explicit degradation. |  |  |
| TTS cloud optional | Cloud TTS runs only when credentials and explicit test approval exist; otherwise remains `CLOUD_CREDENTIALS_PENDING`. |  |  |
| Robot playback | `/robot` plays audio after the operator enables browser sound. |  |  |
| GIF sync | GIF animation starts with feedback and returns to idle or next state after playback. |  |  |
| Duplicate guard | Refresh, duplicate ACK, or repeated event does not duplicate reply, playback, metrics, or training state advancement. |  |  |
| WebSocket recovery | Disconnect and reconnect restore session snapshot without losing current turn. |  |  |
| LAN resilience | Temporary LAN interruption degrades safely and can resume. |  |  |
| Classroom noise | Test speech remains acceptable or degrades clearly in representative classroom noise. |  |  |
| Long run | 30-minute repeated session run has no residual backend/frontend/voice-service process or port leak. |  |  |
| Privacy | No raw audio, full sensitive transcript, real key, model cache, `.runtime`, or generated audio is committed. |  |  |
| Observability | Metrics include stage, provider, model, status, duration, error code, network flag, degraded flag, and no raw content. |  |  |
| Human listening | Piper `zh_CN-huayan-medium` Mandarin intelligibility and child-facing tone reviewed by human listener. |  |  |
| License review | Piper model and voice license reviewed before production use. |  |  |

## Acceptance Record Template

```text
Date:
Operator:
Server hostname/IP:
Robot terminal hostname:
Browser and version:
Microphone model:
Speaker model:
Display count and resolution:
Network type:
STT provider/model:
TTS provider/model:
Cloud providers enabled: yes/no
Test data type: synthetic / developer_authorized / authorized_non_child
Real child voice used: no
External API calls: none / STT only / TTS only / STT+TTS

Summary:

Failed checks:

Observed latency:
- capture to transcript:
- transcript to reply:
- reply to playable audio:
- full turn:

Artifacts reviewed:
- metrics endpoint:
- browser console:
- backend log:
- voice service log:

Production blockers:
- human listening review:
- Piper license review:
- cloud privacy approval:
- site/network issue:
```

## Troubleshooting

- If the robot terminal cannot reach backend health, verify `BACKEND_HOST=0.0.0.0`, firewall rules, LAN IP, and `PUBLIC_BACKEND_ORIGIN`.
- If `/robot` does not play audio, click the browser sound enable control first and verify output device selection.
- If microphone capture fails, verify browser permission, Windows privacy settings, selected input device, and sample-rate compatibility.
- If WebSocket reconnect fails, compare `VITE_WS_URL`, backend `/ws` availability, and session snapshot response.
- If STT/TTS fail locally, verify `VOICE_PYTHON_SERVICE_URL`, Python service health, and model paths under `.runtime/models`.
- If cloud providers are configured, verify keys are environment variables only and that test data is not real child audio.

## Remaining Environment Pending Items

- Real robot browser terminal validation.
- Real dual-display validation.
- Target microphone and speaker validation.
- LAN dual-device validation.
- Classroom noise validation.
- Long-running field stability validation.
- Piper human listening review.
- Piper production license review.
- Optional cloud STT/TTS comparison after credentials and explicit approval.
