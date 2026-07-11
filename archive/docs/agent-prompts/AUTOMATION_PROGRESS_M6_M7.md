# Automation Progress: M6/M7

## Overall Status

- M6: `COMPLETE_CODE_WITH_ENVIRONMENT_PENDING`
- M7: `COMPLETE_CODE_WITH_ENVIRONMENT_PENDING`
- Current batch: `M6_M7_CODE_COMPLETE_ENVIRONMENT_PENDING`
- Latest completed batch: `M7-B stability and field acceptance`
- Latest commit: pending `M7-B: complete deployment acceptance preparation`
- External API calls: none
- Credentials: `CREDENTIALS_PENDING` for real cloud LLM smoke tests
- Professional scoring rules: `OWNER_REQUIRED_BEFORE_SCORING`
- Environment pending: real robot, LAN dual-screen, classroom, long-run validation

## Batch Status

| Batch | Status | Notes |
| -- | -- | -- |
| M6-A deterministic assessment engine and persistence | `COMPLETE_CODE` | Deterministic metrics, evidence references, in-memory repository, report attachment, and assessment query route. |
| M6-B LLM provider and child safety gateway | `COMPLETE_CODE` | Input minimization, redaction, child-visible output review, mock/rule fallback, credentials-pending fallback, and audit metadata. |
| M6-C expanded reports | `COMPLETE_CODE` | Expanded report schema, deterministic metric display data, evidence/version metadata, safe explanations, export boundary, and degradation status. |
| M6-D complete product E2E | `COMPLETE_CODE` | Integrated local E2E covers behavior descriptor, safety fallback/audit, voice turn degradation, mock TTS, robot ACK flow, expanded report boundaries, and voice metrics. |
| M7-A deployment and operations | `COMPLETE_CODE` | Secret-free production config templates, Windows start/stop/health/backup/delete/diagnostics scripts, deployment runbook, and static safety tests. |
| M7-B stability and field acceptance | `COMPLETE_CODE` | Long-run smoke script, recovery drills, multi-session checks, privacy/retention, license/human review, release checklist, rollback drill references, and stop conditions. |

## Validation

| Command | Result | Notes |
| -- | -- | -- |
| `npm run test:backend` | PASS | M6-A deterministic assessment and API route tests. |
| `npm test` | PASS | Contracts, backend, frontend, and E2E. |
| `npm run build` | PASS | Shared, backend, and frontend build. |
| `git diff --check` | PASS | LF/CRLF warnings only. |
| `npm run test:backend` | PASS | M6-B safety gateway, redaction, audit route, prompt injection, and unsafe output tests. |
| `npm test` | PASS | M6-B full local gate. |
| `npm test` | PASS | M6-C expanded report schema, export boundary, frontend type boundary, and E2E report regression. |
| `npm run build` | PASS | M6-C shared, backend, and frontend build. |
| `npm run test:e2e` | PASS | M6-D integrated local product path and degradation boundary. |
| `npm run test:backend` | PASS | M7-A deployment operations artifacts and secret-free defaults. |
| `npm run test:backend` | PASS | M7-B long-run, recovery, privacy, retention, license, release, and stop-condition artifacts. |

## Safety Notes

- Current fact: M6-A does not use LLM output for core metrics.
- Current fact: Missing behavior summaries remain data-quality limitations.
- Current fact: Report generation persists deterministic assessment results in repository boundaries.
- Current fact: M6-B keeps default chat on rule/mock paths and performs no external API calls.
- Current fact: M6-B audit records do not store raw child text.
- Current fact: M6-C expanded reports are derived from deterministic assessment data and do not include diagnosis, norms, percentiles, raw audio, raw video, or raw child chat text.
- Current fact: M6-C safe report explanations are rule-reviewed display text and do not modify core metrics.
- Current fact: M6-D validates the complete local code path with mock/rule providers and keeps real robot, LAN, classroom, and hardware acceptance as environment pending.
- Current fact: M7-A provides deployment templates, operations scripts, health/diagnostic/backup/delete boundaries, rollback instructions, and static tests without enabling real external providers.
- Current fact: M7-B provides long-run smoke tooling, recovery/field acceptance checklists, privacy/retention boundaries, license/human review checklist, release gates, and stop conditions.
- Pending: real cloud LLM smoke tests require credentials and explicit provider enablement.

## Next Recovery Point

M6/M7 code-side work is complete. Resume only for field/environment execution or new product-owner decisions.
