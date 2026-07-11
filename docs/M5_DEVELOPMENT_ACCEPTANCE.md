# M5 Development Acceptance

## Status

- Overall: `COMPLETE_CODE_WITH_ENVIRONMENT_PENDING`
- Validation date: 2026-06-14
- Real child data used: no
- External cloud vision/STT/TTS/LLM calls: none
- Raw camera frame persistence: no
- Raw audio persistence added by M5: no
- Model downloads: none

## Completed Development Scope

- Shared behavior observation contracts.
- Attention and language observation event payloads.
- Bounded behavior repository interface.
- Browser camera permission/device/low-fps sampling boundary.
- Camera frame descriptor client and backend ingress.
- Mock Attention Provider scenarios.
- Deterministic language feature extraction.
- Question timeline alignment.
- Question behavior summary.
- Session behavior summary.
- Data quality states and quality-preserving aggregation.
- Behavior observability metrics.
- M5 fixture rules and automated tests.

## Automated Validation

| Command | Result | Notes |
| -- | -- | -- |
| `npm run test:contracts` | PASS | Shared behavior contract/runtime fixtures. |
| `npm run test:backend` | PASS | Repository, frame ingress, language features, timeline, aggregation, observability, API smoke. |
| `npm run test:frontend` | PASS | Camera capture/client boundary and existing frontend smoke tests. |
| `npm run test:e2e` | PASS | Existing training loop and dual-screen realtime regression. |
| `npm test` | PASS | Full local gate. |
| `npm run build` | PASS | Shared, backend, and frontend build. |
| `git diff --check` | PASS | LF/CRLF warnings only. |

## Acceptance Notes

- 当前事实: M5 code can run with mock/descriptor behavior observations in the current development environment.
- 当前事实: M5 does not produce formal attention or language ability scores.
- 当前事实: Missing camera, low confidence, provider failure, and missing observations remain data-quality facts, not negative child behavior.
- 待确认: Professional scoring rules, thresholds, norms, percentiles, and clinical/professional interpretation remain outside M5.

## Environment Pending

- Real robot browser terminal camera permission.
- Real LAN dual-screen setup.
- Classroom lighting and occlusion.
- Multiple people in camera view.
- Long-running camera stability.
- Real local vision model accuracy and latency.
- Human annotation comparison.

## Recovery Point

After the M5-D commit, continue with M6-A deterministic assessment engine. Do not rework M5 unless tests fail or the project owner changes M5 scope.
