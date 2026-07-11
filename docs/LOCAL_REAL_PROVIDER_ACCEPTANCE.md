# Local Real Provider Acceptance

Audit date: 2026-06-14

This acceptance record covers the final real-capability sprint through `FINAL-A`, `FINAL-B`, `FINAL-C`, and `FINAL-D`. Tests used synthetic or non-child fixtures only. No real keys, paid external services, raw audio/video/frame persistence, generated audio commits, real child data, or scoring-rule changes were introduced.

## Environment And Defaults Checked

| Item | Result |
| --- | --- |
| Git baseline | Current sprint history includes `aeef4d7 FINAL-A`, `e4a285a FINAL-B`, `118e0b5 FINAL-C`; Batch D updates this document and the capability matrix. |
| Development defaults | `backend/.env.example` sets `VOICE_STT_PROVIDER=local`, `VOICE_TTS_PROVIDER=local`, `ATTENTION_PROVIDER=local`, `DEMO_STORAGE_PROVIDER=sqlite`. |
| Safe runtime fallback | `backend/src/config/runtime.ts` still falls back to mock voice/attention and rule/no AI TTS when env is absent. |
| Production template | `deploy/production.env.example` remains safe: rule chat, no AI TTS, mock voice until explicit operator enablement. |
| Local Vosk | Python Voice Service `/stt` supports local Vosk; model path remains `.runtime/models/vosk/vosk-model-small-cn-0.22`. |
| Local Piper | Python Voice Service `/tts` supports Piper `zh_CN-huayan-medium` with in-memory WAV/base64 response. |
| Local attention | Browser descriptors and `LocalAttentionObservationProvider` support face presence/count, rough orientation, screen-facing flag, image quality, provider/version/confidence only. |
| SQLite | Schema migration v1 persists sessions, domain event indexes, behavior, assessment, report, provider/algorithm/rule versions; default does not persist raw media. |
| LLM credentials | No LLM key used. Rule Provider is accepted for local flow; real LLM remains `CREDENTIALS_PENDING`. |

## Commands Executed Or Required For Final Acceptance

```powershell
tools\voice-benchmark\.venv\Scripts\python.exe tools\voice-service\voice_service.test.py
node --test backend\test\sqlitePersistence.test.mjs
node --test backend\test\behaviorFrameIngressService.test.mjs backend\test\behaviorTimelineAggregation.test.mjs backend\test\assessmentService.test.mjs backend\test\api.test.mjs
npm run test:backend
npm run test:frontend
npm run test:e2e
npm test
npm run build
git diff --check
```

## Product Flow Acceptance

| Flow item | 默认配置 | 真实 Provider | 主流程接入 | 当前开发机实测 | 双主机待验收 | Risk and command |
| --- | --- | --- | --- | --- | --- | --- |
| `/child` real microphone capture | `VOICE_STT_PROVIDER=local` in `.env.example` | Browser MediaRecorder plus backend media ingress | 当前事实: primary hook sends chunks to backend STT path; SpeechRecognition is compatibility fallback | PASS through frontend static/smoke and backend media API tests | Manual hardware permission/noise test pending | Run `npm run test:frontend`, `npm run test:backend`; then manual `/child` mic |
| Vosk STT | Local when Python service is running | `local-vosk-small-cn` | 当前事实: backend media transcribe calls Python `/stt` | PASS Python voice tests and backend media tests | LAN service startup/port pending | Run `tools\voice-benchmark\.venv\Scripts\python.exe tools\voice-service\voice_service.test.py` |
| Rule or configured LLM | `AI_CHAT_PROVIDER=rule` | Rule Provider accepted; LLM pending credentials | 当前事实: safety gateway wraps assistant turn | PASS safety/chat tests | Cloud LLM intentionally not accepted | Run `npm run test:backend`; OpenAI remains `CREDENTIALS_PENDING` without key |
| Safety Gateway | Rule safety/minimization | Deterministic local safety | 当前事实: unsafe/professional outputs degrade before TTS/report | PASS LLM safety tests | Human policy review pending | Run `node --test backend/test/llmSafetyGatewayService.test.mjs` |
| Piper TTS | `VOICE_TTS_PROVIDER=local` in `.env.example` | Piper `zh_CN-huayan-medium` through Python `/tts` | 当前事实: Node local TTS requests real Piper audio; mock remains fallback | PASS Python voice tests; E2E covers robot ACK path | Speaker/autoplay/listening/license review pending | Run Python voice test and `npm run test:e2e` |
| `/robot` playback and GIF | `/robot` screen role | Browser audio element plus GIF animation manifest | 当前事实: TTS start/finish/failure ACK and animation ACK gate turn completion | PASS realtime/E2E tests | Real speaker/display dual-host pending | Run `npm run test:e2e`; manual robot screen audio |
| Camera attention | `ATTENTION_PROVIDER=local` in `.env.example` | Local descriptor provider | 当前事实: `/child` posts low-FPS descriptors; backend saves observations | PASS local attention and API tests | Camera permission, low light, multi-person manual validation pending | Run behavior/assessment tests; manual camera checklist |
| Behavior aggregation | Always local deterministic | Aggregation algorithms v1 | 当前事实: question/session summaries feed assessment/report | PASS aggregation tests | Real data distributions pending | Run `backend/test/behaviorTimelineAggregation.test.mjs` |
| Deterministic assessment | Always local deterministic | `m6-deterministic-assessment-v1` | 当前事实: includes evidence, data quality, provider versions, `OWNER_REQUIRED_BEFORE_SCORING` | PASS assessment/report tests | Professional rules pending | No formal score/diagnosis; run `npm run test:backend` |
| Extended report | Local deterministic | Report policy v1 | 当前事实: distinguishes real/mock/degraded/missing via provider summary and data quality | PASS API/frontend/E2E | Real dual-host session report pending | Run `npm run test:e2e` |
| SQLite persistence | `DEMO_STORAGE_PROVIDER=sqlite` | Python stdlib SQLite bridge | 当前事实: restart restores historical session/report/assessment/events; raw media not saved | PASS temp DB restart test | Backup/retention on target host pending | Run `node --test backend/test/sqlitePersistence.test.mjs` |

## Required Scenario Coverage

| Scenario | Current status | Evidence |
| --- | --- | --- |
| Normal speech | ACCEPTED with synthetic/local service tests and product path wiring | Python voice tests, backend media tests |
| Silence | ACCEPTED as degradation path | Voice fixture/degradation tests |
| STT failure | ACCEPTED as degradation path | Voice provider/degradation tests |
| Piper failure | ACCEPTED as fallback/degradation path | Python voice tests and TTS fallback tests |
| Camera permission denied | ACCEPTED as data-quality path | Local attention/mock scenario tests |
| No face | ACCEPTED as data-quality/observation state, not inattentive label | Attention tests |
| Multiple people | ACCEPTED as coarse face-count state | Attention tests |
| Low image quality | ACCEPTED as data-quality issue | Attention tests |
| WebSocket reconnect | ACCEPTED in automated realtime/snapshot coverage; field timing pending | E2E/realtime tests |
| Page refresh | ACCEPTED through snapshot/session restore coverage; manual browser pending | E2E plus SQLite persistence test |
| Duplicate ACK | ACCEPTED | Domain event/realtime tests |
| Backend restart | ACCEPTED for persisted session/report/assessment/events | SQLite temp DB restart test |
| Historical report recovery | ACCEPTED | SQLite persistence test |
| Mock fallback | ACCEPTED | Voice/attention/provider tests |
| No duplicate reply or advance | ACCEPTED | Realtime ACK-gated E2E |
| No raw media saved | ACCEPTED | Media ingress, camera descriptor, report boundary, SQLite tests |

## Field Readiness Decision

当前事实: the repository is ready for controlled local real-provider rehearsal with local Vosk, local Piper, local attention descriptors, deterministic safety/assessment/report, and SQLite persistence.

待确认: full field acceptance still requires `/child` and `/robot` on separate LAN hosts, real microphone/camera permission prompts, robot speaker/display playback, lighting/noise checks, firewall/CORS/WebSocket reconnect checks, retention/backup drill on the target Windows host, Piper license/listening review, and owner-approved scoring rules before any formal score or professional interpretation.
