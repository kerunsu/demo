# M4 Automation Progress

## Overall Status

- Overall: `COMPLETE_CODE_WITH_ENVIRONMENT_PENDING`
- Current task: `M4-014 最终真实部署验收`
- Latest completed task: `M4-014 development acceptance preparation`
- Next task: real robot/LAN/site acceptance when environment is available
- Needs project owner intervention: no
- External API calls in this run: none
- Cloud provider state: `CLOUD_STT_CREDENTIALS_PENDING`, `CLOUD_TTS_CREDENTIALS_PENDING`

## Provider Decisions

- STT decision: `LOCAL_PRIMARY_CLOUD_OPTIONAL`
- Default STT provider: `local-vosk-small-cn`
- Default STT model: `vosk-model-small-cn-0.22`
- Default STT model path: `.runtime/models/vosk/vosk-model-small-cn-0.22`
- TTS decision: `LOCAL_PRIMARY_CLOUD_OPTIONAL`
- Default TTS provider: `local-piper-zh-huayan`
- Default TTS model: `zh_CN-huayan-medium`
- Default TTS model path: `.runtime/models/piper/zh_CN-huayan-medium.onnx`
- Default TTS config path: `.runtime/models/piper/zh_CN-huayan-medium.onnx.json`
- TTS human review: `HUMAN_REVIEW_PENDING`
- TTS production license review: `REQUIRED_BEFORE_PRODUCTION`
- Inference boundary: Node.js training orchestration backend -> Provider contract -> independent Python voice inference service

## Task Matrix

| Task | Status | Notes |
| -- | -- | -- |
| M4-001 开发服务器语音运行时与硬件能力探测 | `COMPLETE` | `COMPLETE_FOR_DEVELOPMENT`, `DEVELOPMENT_SERVER_BASELINE`. |
| M4-002 本地与云端 STT/TTS 技术 Spike 和横向 Benchmark | `COMPLETE` | Harness complete; cloud remains credentials pending. |
| M4-002B 真实 STT/TTS 候选验证与技术路线收口 | `COMPLETE` | `PROVISIONAL_PROVIDER_DECISION`; Vosk and Piper local candidates validated. |
| M4-003 固定 STT/TTS Provider 契约 | `COMPLETE` | Shared contract covers local/cloud/mock metadata, health, timeout, cancel, metrics, data safety, and fallback. |
| M4-004 浏览器音频采集 | `COMPLETE` | Browser microphone capture layer covers permission, device enumeration/change, audio levels, chunking, stop/cancel, max turn duration, and no raw-audio persistence. |
| M4-005 媒体传输 | `COMPLETE` | Shared media contract, HTTP binary chunk ingress, frontend media client, sequence/missing-chunk ACKs, and no raw-audio persistence are implemented. |
| M4-006 STT 集成 | `COMPLETE` | Media streams can trigger mock/local/cloud STT provider boundary; backend health exposes STT status; independent Python voice service provides health and mock/local Vosk STT endpoint. |
| M4-007 Transcript 处理 | `COMPLETE` | Final transcripts are normalized with empty-result handling, duplicate detection, low-confidence markers, and basic PII redaction. |
| M4-008 语音轮次控制 | `COMPLETE` | Backend half-duplex turn controller covers listening, transcribing, robot speaking pause, cancel, retry, completion, degradation, timeout deadline, and reserved barge-in fields. |
| M4-009 TTS 集成 | `COMPLETE` | Child-facing TTS synthesis runs through Safety Provider first, supports mock/local/cloud provider boundary, Python voice-service `/tts`, and cloud credentials pending behavior. |
| M4-010 机器人屏播放与动画同步 | `COMPLETE` | Robot screen requests backend TTS, plays returned audio or timed fallback, sends TTS started/finished ACKs, deduplicates feedback turns, defers speech until browser sound is enabled, and cleans up active playback. |
| M4-011 故障与降级 | `COMPLETE` | Central degradation plans cover microphone unavailable, media transport failure, STT/TTS provider unavailable, empty/low-confidence STT, WebSocket disconnect, robot playback failure, manual text, retry, fixed audio, and display-text fallback boundaries. |
| M4-012 可观测性和延迟指标 | `COMPLETE` | Backend voice observability service records bounded, deduplicated, privacy-preserving metrics for capture, first chunk, VAD placeholder, STT, transcript, rule reply, safety, TTS, robot playback, and total turn latency. |
| M4-013 E2E 与测试 Fixture | `COMPLETE` | Added non-child voice fixture manifest, mock STT/TTS/Safety fixture coverage, media-to-STT-to-TTS fixture chain checks, degradation assertions, duplicate metric guard, and dual-screen E2E duplicate ACK/metric assertions. |
| M4-014 最终真实部署验收 | `ENVIRONMENT_PENDING` | Development-machine validation and acceptance checklist are prepared in `docs/M4_DEPLOYMENT_ACCEPTANCE.md`; real robot browser terminal, LAN dual device, microphone, speaker, classroom noise, listening review, and license review remain pending. |

## Completed Tasks

- `M4-001`
- `M4-002`
- `M4-002B`
- `M4-003`
- `M4-004`
- `M4-005`
- `M4-006`
- `M4-007`
- `M4-008`
- `M4-009`
- `M4-010`
- `M4-011`
- `M4-012`
- `M4-013`
- `M4-014 development acceptance preparation`

## In Progress Tasks

- None.

## Task Blocked

- None.

## Commit Pending

- `M4-014` local commit pending until final validation and Git metadata write.

## Environment Pending

- `M4-014` real deployment acceptance.
- Real robot dual-screen environment.
- Actual microphone and speaker on target robot browser terminal.
- LAN dual-device validation.
- Classroom noise validation.
- Piper human listening review and production license review.
- Optional cloud provider comparison after credentials and explicit benchmark approval.

## Test Results

| Time | Command | Result | Notes |
| -- | -- | -- | -- |
| 2026-06-13 | `npm test` | PASS | Baseline before M4-003. |
| 2026-06-13 | `npm run build` | PASS | Baseline before M4-003. |
| 2026-06-13 | `npm run test:contracts` | PASS | M4-003 shared provider contract validation. |
| 2026-06-13 | `npm test` | PASS | M4-003 full validation. |
| 2026-06-13 | `npm run build` | PASS | M4-003 full validation. |
| 2026-06-13 | `git diff --check` | PASS | LF/CRLF warnings only. |
| 2026-06-13 | `npm --prefix frontend test` | PASS | M4-004 browser audio capture smoke validation. |
| 2026-06-13 | `npm --prefix frontend run build` | PASS | M4-004 browser audio capture type/build validation. |
| 2026-06-13 | `npm test` | PASS | M4-004 full validation. |
| 2026-06-13 | `npm run build` | PASS | M4-004 full validation; rerun sequentially after parallel Vite output race. |
| 2026-06-13 | `git diff --check` | PASS | LF/CRLF warnings only. |
| 2026-06-13 | `npm run test:contracts` | PASS | M4-005 shared media contract validation. |
| 2026-06-13 | `npm run test:backend` | PASS | M4-005 media ingress API validation. |
| 2026-06-13 | `npm run test:frontend` | PASS | M4-005 frontend media client smoke validation. |
| 2026-06-13 | `npm test` | PASS | M4-005 full validation. |
| 2026-06-13 | `npm run build` | PASS | M4-005 full validation. |
| 2026-06-13 | `git diff --check` | PASS | LF/CRLF warnings only. |
| 2026-06-13 | `npm run test:backend` | PASS | M4-006 STT media transcription and health validation. |
| 2026-06-13 | `npm run test:frontend` | PASS | M4-006 frontend transcription client validation. |
| 2026-06-13 | `python tools\voice-service\voice_service.test.py` | PASS | Python voice service health and mock STT validation. |
| 2026-06-13 | `python -m py_compile tools\voice-service\voice_service.py` | PASS | Python syntax validation. |
| 2026-06-13 | `npm run test:e2e` | PASS | Health schema updated for STT provider status. |
| 2026-06-13 | `npm test` | PASS | M4-006 full validation. |
| 2026-06-13 | `npm run build` | PASS | M4-006 full validation. |
| 2026-06-13 | `git diff --check` | PASS | LF/CRLF warnings only. |
| 2026-06-13 | `npm run test:backend` | PASS | M4-007 transcript normalization validation. |
| 2026-06-13 | `npm test` | PASS | M4-007 full validation. |
| 2026-06-13 | `npm run build` | PASS | M4-007 full validation. |
| 2026-06-13 | `git diff --check` | PASS | LF/CRLF warnings only. |
| 2026-06-13 | `npm run test:backend` | PASS | M4-008 voice turn controller validation. |
| 2026-06-13 | `npm test` | PASS | M4-008 full validation. |
| 2026-06-13 | `npm run build` | PASS | M4-008 full validation. |
| 2026-06-13 | `git diff --check` | PASS | LF/CRLF warnings only. |
| 2026-06-13 | `npm run test:backend` | PASS | M4-009 TTS provider and safety-gated synthesis validation. |
| 2026-06-13 | `python tools\voice-service\voice_service.test.py` | PASS | Python voice service TTS mock validation. |
| 2026-06-13 | `python -m py_compile tools\voice-service\voice_service.py` | PASS | Python syntax validation. |
| 2026-06-13 | `npm test` | PASS | M4-009 full validation. |
| 2026-06-13 | `npm run build` | PASS | M4-009 full validation. |
| 2026-06-13 | `git diff --check` | PASS | LF/CRLF warnings only. |
| 2026-06-13 | `npm run test:backend` | PASS | Resume validation for pending M4-007 through M4-009 backend changes. |
| 2026-06-13 | `npm run test:frontend` | PASS | M4-010 robot playback and ACK boundary smoke validation. |
| 2026-06-13 | `python tools\voice-service\voice_service.test.py` | PASS | Resume validation for Python STT/TTS service boundary. |
| 2026-06-13 | `npm run test:backend` | PASS | M4-011 degradation plan validation. |
| 2026-06-13 | `npm run test:frontend` | PASS | M4-011 microphone degradation boundary smoke validation. |
| 2026-06-13 | `npm test` | PASS | M4-011 full validation. |
| 2026-06-13 | `npm run build` | PASS | M4-011 full validation. |
| 2026-06-13 | `python tools\voice-service\voice_service.test.py` | PASS | M4-011 regression validation for Python voice service. |
| 2026-06-13 | `npm run test:backend` | PASS | M4-012 voice observability service, route, and metric privacy validation. |
| 2026-06-13 | `npm run test:backend` | PASS | M4-013 fixture manifest, mock provider, media/STT/TTS chain, degradation, and metric guard validation. |
| 2026-06-13 | `npm run test:e2e` | PASS | M4-013 dual-screen duplicate ACK, recovery snapshot, and voice metric single-record validation. |
| 2026-06-13 | `npm run test:backend` | PASS | M4-014 development-machine backend regression before acceptance packaging. |
| 2026-06-13 | `npm run test:frontend` | PASS | M4-014 development-machine frontend regression before acceptance packaging. |
| 2026-06-13 | `python tools\voice-service\voice_service.test.py` | PASS | M4-014 Python voice service regression before acceptance packaging. |
| 2026-06-13 | `python -m py_compile tools\voice-service\voice_service.py` | PASS | M4-014 Python syntax regression before acceptance packaging. |
| 2026-06-13 | `npm test` | PASS | M4-014 full automated development validation. |
| 2026-06-13 | `npm run build` | PASS | M4-014 full build validation. |

## Important Technical Decisions

- Business orchestration must not directly bind to Vosk, Piper, OpenAI, or a provider SDK.
- Cloud STT/TTS slots remain present but disabled without environment credentials and explicit enablement.
- Missing cloud credentials do not block local voice-chain development.
- M4 TTS output remains gated by Safety Provider review before synthesis.
- Raw audio is not persisted by default.
- Browser audio capture chunks are exposed to a callback for M4-005 media ingress; they are not mixed into ordinary JSON domain events.
- Media transport uses `application/octet-stream` chunk POSTs plus JSON start/finish control messages; backend stores metadata only.
- STT defaults to `mock-stt` for automated tests; local Vosk is routed through the independent Python voice service when explicitly configured.
- Transcript processing is separate from provider execution and stores only redacted normalized text in provider results.
- Voice turn control is backend-owned and half-duplex by default; barge-in remains reserved but not implemented.
- Child-facing TTS must use approved or fallback text from Safety Provider before synthesis; unreviewed text is not sent to TTS.
- Robot screen owns browser playback and sends `TTS_STARTED` / `TTS_FINISHED` ACKs after synthesized audio or fallback timed playback; repeated feedback events are deduplicated.
- Voice degradation plans centralize child-safe fallback text and keep raw audio persistence and external network requirements disabled for fallback paths.
- Voice observability keeps bounded in-memory metrics with stage/correlation/provider/model/timing/error/degradation fields and records only text length/hash, never raw audio or full sensitive transcript.
- M4-013 fixtures are descriptors only; committed fixtures do not contain real child voice, binary audio, cloud credentials, or generated model output.
- M4-014 cannot be marked field-complete until real robot terminal, LAN dual-device, classroom noise, human listening, and Piper production license checks are performed.

## Recent Commit

- `bf0c8b2 M4-014: add deployment acceptance checklist`
