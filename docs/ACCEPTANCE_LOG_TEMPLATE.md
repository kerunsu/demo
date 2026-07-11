# Acceptance Log Template

Create one copy per rehearsal run. Do not paste real secrets, raw audio, raw video, raw camera frames, child identifiers, or full sensitive transcripts into the log.

## Run Metadata

| Field | Value |
| --- | --- |
| Run ID |  |
| Date/time |  |
| Operator |  |
| Git commit |  |
| Branch |  |
| Scenario | Local real provider / Dual-host LAN / 30-minute stability / 2-hour stability / Fault recovery / License-listening |
| Result | PASS / FAIL / BLOCKED / MANUAL_ACCEPTANCE_REQUIRED |

## Test Environment

| Field | Value |
| --- | --- |
| Server host OS |  |
| Server LAN IP |  |
| Browser or robot host OS |  |
| Browser or robot LAN IP |  |
| Browser name/version |  |
| Backend origin |  |
| Frontend origin |  |
| WebSocket URL |  |
| Python Voice Service URL |  |
| Microphone device | MANUAL_ACCEPTANCE_REQUIRED |
| Speaker device | MANUAL_ACCEPTANCE_REQUIRED |
| Camera device | MANUAL_ACCEPTANCE_REQUIRED |
| Classroom/noise/lighting notes | MANUAL_ACCEPTANCE_REQUIRED |

## Provider And Model Evidence

| Provider | Mode | Model | Version/path | Health/result | Degradation |
| --- | --- | --- | --- | --- | --- |
| STT | local-vosk / mock / cloud-disabled |  |  |  |  |
| TTS | local-piper / mock / cloud-disabled |  |  |  |  |
| LLM/chat | rule / cloud-disabled |  |  |  |  |
| Safety | deterministic/rule |  |  |  |  |
| Attention | local / mock |  |  |  |  |
| Storage | sqlite |  |  |  |  |

## Session Evidence

| Field | Value |
| --- | --- |
| Session ID |  |
| Course(s) |  |
| Child screen URL |  |
| Robot screen URL |  |
| Start time |  |
| End time |  |
| Report ID |  |
| SQLite DB path |  |

## Step Results

| Step | Success/failure | Latency | Degradation state | Evidence path or note |
| --- | --- | --- | --- | --- |
| Backend health |  |  |  |  |
| Python Voice Service health |  |  |  |  |
| SQLite available |  |  |  |  |
| Model files present |  |  |  |  |
| WebSocket connect/reconnect |  |  |  |  |
| Frontend `/child` accessible |  |  |  |  |
| Frontend `/robot` accessible |  |  |  |  |
| Microphone permission | MANUAL_ACCEPTANCE_REQUIRED |  |  |  |
| Camera permission | MANUAL_ACCEPTANCE_REQUIRED |  |  |  |
| Vosk transcript | MANUAL_ACCEPTANCE_REQUIRED |  |  |  |
| Piper playback | MANUAL_ACCEPTANCE_REQUIRED |  |  |  |
| Attention descriptors | MANUAL_ACCEPTANCE_REQUIRED |  |  |  |
| Report generation |  |  |  |  |
| Backup/rollback | MANUAL_ACCEPTANCE_REQUIRED |  |  |  |

## Latency Measurements

| Measurement | P50 | P95 | Max | Notes |
| --- | --- | --- | --- | --- |
| Mic capture to transcript |  |  |  |  |
| Transcript to reviewed reply |  |  |  |  |
| TTS request to audio ready |  |  |  |  |
| Audio ready to robot playback |  |  |  |  |
| WebSocket reconnect |  |  |  |  |
| Report generation |  |  |  |  |

## Failure Or Blocker Record

| Field | Value |
| --- | --- |
| Issue ID |  |
| Status | OPEN / MITIGATED / CLOSED |
| Severity | P0 / P1 / P2 / P3 |
| Reproduction steps |  |
| Expected result |  |
| Actual result |  |
| Logs/diagnostics path |  |
| Degradation observed |  |
| Owner |  |
| Next action |  |

## Manual Review

| Review | Status | Notes |
| --- | --- | --- |
| Human listening quality | MANUAL_ACCEPTANCE_REQUIRED |  |
| Piper license | MANUAL_ACCEPTANCE_REQUIRED |  |
| Vosk license | MANUAL_ACCEPTANCE_REQUIRED |  |
| Child safety fallback wording | OWNER_REQUIRED |  |
| Formal scoring/professional rules | OWNER_REQUIRED |  |

