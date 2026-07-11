# Product Completion Progress

## Overall Status

- Current phase: `M7`
- Current batch: `M6_M7_CODE_COMPLETE_ENVIRONMENT_PENDING`
- M5: `COMPLETE_CODE_WITH_ENVIRONMENT_PENDING`
- M6: `COMPLETE_CODE_WITH_ENVIRONMENT_PENDING`
- M7: `COMPLETE_CODE_WITH_ENVIRONMENT_PENDING`
- Latest commit: pending `M7-B: complete deployment acceptance preparation`
- External services: no external provider call required for M7-B
- Credentials: `CREDENTIALS_PENDING` for future cloud LLM/STT/TTS smoke tests
- Environment pending: real robot, LAN dual-screen, camera, microphone, speaker, classroom light/noise
- Professional rules pending: `OWNER_REQUIRED_BEFORE_SCORING`

## Current Batch

M6/M7 code-side deliverables are complete. Real robot, LAN, classroom, hardware, long-run field execution, human listening, license, and optional cloud-provider checks remain environment or owner pending.

## Completed Batches

- `M5-A behavior observation foundation`
- `M5-B attention observation pipeline`
- `M5-C behavior timeline and aggregation`
- `M5-D behavior validation and acceptance`
- `M6-A deterministic assessment engine and persistence`
- `M6-B LLM provider and child safety gateway`
- `M6-C expanded assessment reports`
- `M6-D complete product E2E`
- `M7-A deployment and operations`
- `M7-B stability and field acceptance`

## Current Validation

| Command | Result | Notes |
| -- | -- | -- |
| `npm run test:contracts` | PASS | M5 behavior contract and runtime fixtures. |
| `npm run test:backend` | PASS | M5 repository, language feature, behavior frame, timeline, aggregation, acceptance docs, and M6-A deterministic assessment tests. |
| `npm run test:frontend` | PASS | Frontend smoke and camera capture/client boundary tests. |
| `npm run test:e2e` | PASS | Training loop and dual-screen realtime regression. |
| `npm test` | PASS | Contracts, backend, frontend, and E2E pass. |
| `npm run build` | PASS | Shared, backend, and frontend build pass. |
| `git diff --check` | PASS | LF/CRLF warnings only. |
| `npm run test:backend` | PASS | M6-B child safety gateway, redaction, audit metadata, chat route audit, and fallback tests. |
| `npm test` | PASS | M6-B full local gate: contracts, backend, frontend, and E2E. |
| `npm run build` | PASS | M6-B shared, backend, and frontend build. |
| `npm test` | PASS | M6-C expanded report schema, export boundary, safe explanations, frontend type boundary, and E2E report regression. |
| `npm run build` | PASS | M6-C shared, backend, and frontend build. |
| `npm run test:e2e` | PASS | M6-D integrated local path: behavior frame descriptor, unsafe chat safety fallback, audit redaction, voice turn degradation, mock TTS, robot animation ACK, expanded report boundaries, and voice metrics. |
| `npm run test:backend` | PASS | M7-A deployment operation templates, scripts, runbook, and secret-free safe defaults. |
| `npm run test:backend` | PASS | M7-B long-run smoke script, recovery checklist, privacy/retention, license review, release checklist, and stop conditions. |

## M6-A Notes

- Current fact: M6-A computes deterministic metrics only; no LLM-generated core scores are allowed.
- Current fact: Missing behavior summaries are represented as data-quality limitations, not negative child behavior.
- Current fact: M6-A exposes stored assessment results through report generation and `GET /api/assessment/:sessionId`.
- Pending owner decision: formal weights, thresholds, norms, percentiles, and professional interpretations remain `OWNER_REQUIRED_BEFORE_SCORING`.

## M6-B Notes

- Current fact: child chat input is minimized and redacted before LLM/rule processing.
- Current fact: child-visible assistant output is reviewed before returning to UI or TTS.
- Current fact: prompt injection, unsafe professional claims, safety-provider failure, and missing credentials degrade to fixed safe fallback paths.
- Current fact: audit records store provider/status/actions/lengths/reason codes, not raw child text.

## M6-C Notes

- Current fact: reports include `expandedReport` with answer metrics, attention metrics, language metrics, data quality, evidence counts, version metadata, history, trend baseline, safe explanations, export boundaries, and degradation reason codes.
- Current fact: expanded reports are derived from deterministic M6-A assessment data and do not create diagnosis, norms, percentiles, or LLM-modified core scores.
- Current fact: export boundaries explicitly mark raw audio, raw video, and raw child chat text as absent.
- Current fact: mixed-course frontend reports preserve per-course expanded report data where available and mark the merge as having no single assessment id.

## M6-D Notes

- Current fact: M6-D E2E validates the local core product path without real external providers.
- Current fact: the integrated test covers behavior frame descriptors, child-safe chat fallback and audit redaction, voice turn degradation, mock TTS synthesis, robot animation/TTS ACK flow, expanded report data-quality degradation, and voice metrics without raw audio persistence.
- Current fact: unavailable real robot, LAN dual-screen, classroom, microphone, speaker, and camera field checks remain environment pending.

## M7-A Notes

- Current fact: M7-A adds secret-free backend and frontend deployment templates under `deploy/`.
- Current fact: M7-A adds Windows PowerShell operations scripts for backend start/stop, health checks, backup, confirmed runtime cleanup, and diagnostics under `scripts/ops/`.
- Current fact: M7-A documents deployment, LAN/WebSocket configuration, logs, backup/delete, diagnostics, and rollback in `docs/DEPLOYMENT_OPERATIONS_M7.md`.
- Current fact: M7-A static tests verify safe rule/mock defaults and reject real API key patterns in deployment artifacts.

## M7-B Notes

- Current fact: M7-B adds `scripts/ops/Invoke-LongRunSmoke.ps1` for bounded health/log-size long-run checks.
- Current fact: M7-B adds `docs/STABILITY_FIELD_ACCEPTANCE_M7.md` covering long-run gates, recovery drills, multi-session checks, privacy/retention, license/human review, release checklist, and stop conditions.
- Current fact: M7-B static tests verify long-run, recovery, privacy, retention, license, release, environment-pending, and secret-free boundaries.
- Environment pending: real robot, LAN dual-screen, classroom noise/light, microphone, speaker, camera, 30-minute field run, human listening, license review, and optional cloud provider smoke tests.

## Technical Decisions

- M5 behavior observations use `m5-behavior-v1` schema.
- M6-A deterministic assessments use `m6-assessment-v1` schema and `deterministic-assessment-v1` metric version.
- M6-C expanded reports use `m6-expanded-report-v1` schema and `m6-expanded-report-metrics-v1` metric version.
- Data quality states are distinct from child behavior.
- Raw camera frames, raw video, raw audio, model files, and credentials are not persisted or committed.
- M6 and M7 use compact batch plans in `docs/WORK_ITEMS_M6_M7.md`.

## Next Recovery Point

Resume from the M7-B commit or await field/environment execution:

1. Verify the latest commit is `M7-B: complete deployment acceptance preparation`.
2. Run field acceptance only with the required robot/LAN/hardware environment and approved test data.
3. Preserve the safety boundary: do not add secrets, real external provider calls, or raw child media persistence.
