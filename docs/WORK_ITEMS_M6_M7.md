# Compact Work Items: M6 and M7

This file is a compact execution plan. It is not a claim that M6 or M7 has been implemented.

## M6: Core Product Capability

### M6-A: Deterministic Assessment Engine And Persistence

- Compute evidence-based question/session metrics from answers, response time, prompts, attention summaries, language summaries, and data quality.
- Persist assessment results and history through repository boundaries.
- Keep formal weights, thresholds, norms, and percentiles as `OWNER_REQUIRED_BEFORE_SCORING`.
- Commit: `M6-A: implement deterministic assessment engine`

### M6-B: LLM Provider And Child Safety Gateway

- Add replaceable LLM Provider, rule/mock fallback, input minimization, redaction, output review, timeout/retry, audit metadata, and prompt-injection guard.
- If credentials are absent, mark `CREDENTIALS_PENDING`; do not stop implementation.
- Child-visible LLM content must pass safety review before UI or TTS.
- Commit: `M6-B: add LLM and child safety gateway`

### M6-C: Expanded Reports

- Add report schema for answer metrics, attention metrics, language metrics, data quality, evidence, versions, history, trends, safety-reviewed explanations, export, and fallback.
- Do not create diagnosis, invented norms, invented percentiles, or LLM-modified core scores.
- Commit: `M6-C: implement expanded assessment reports`

### M6-D: Complete Product E2E

- Validate answer/speech -> STT -> behavior observation -> deterministic metrics -> safe LLM/rule reply -> TTS -> robot animation -> session summary -> expanded report.
- Cover provider failures, safety rejection, reconnection, duplicate events, data missing, and report degradation.
- Commit: `M6-D: complete core product integration`

## M7: Deployment, Stability, And Field Acceptance Preparation

### M7-A: Deployment And Operations

- Prepare production configuration templates, frontend/backend/Python service deployment, database migration boundary, start/stop scripts, health checks, log rotation, model paths, secret management, LAN/CORS/WebSocket configuration, browser launch scripts, backup/delete, diagnostics, and rollback.
- Commit: `M7-A: prepare production deployment and operations`

### M7-B: Stability, Safety, And Field Acceptance

- Add long-run test tooling, crash/network/device recovery, model failure handling, disk/log bounds, multi-session checks, privacy checks, retention/deletion verification, license checklist, field acceptance checklist, release checklist, and rollback drill template.
- Mark unavailable real robot/server/classroom items as `ENVIRONMENT_PENDING`.
- Commit: `M7-B: complete deployment acceptance preparation`
