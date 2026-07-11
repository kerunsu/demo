# Test Fixtures

Current fact: M1/M2 tests must be deterministic, local-only, and safe to run without real external providers.

## Root Commands

- `npm run test:contracts`: compile and run shared contract/runtime tests.
- `npm run test:backend`: run backend API tests through the backend package.
- `npm run test:frontend`: run frontend build and page smoke tests through the frontend package.
- `npm run test:e2e`: run the current local training-loop E2E baseline.
- `npm test`: run the full local test gate in dependency order: contracts, backend, frontend, E2E.

## Fixture Locations

Use the nearest test boundary for fixtures:

- `backend/test/fixtures/` for backend API and service fixtures.
- `frontend/test/fixtures/` for frontend smoke or UI fixtures.
- `shared/test/fixtures/` for shared contract fixtures.
- `e2e/fixtures/` for end-to-end scenario fixtures.

Only create a fixture directory when a task adds committed fixture files for that boundary.

## Fixture Rules

- Fixtures must use synthetic demo data only.
- Do not commit real child data, real names, API keys, audio, video, camera frames, or raw transcripts from real users.
- Keep fixture ordering deterministic. Tests must not depend on random question order or local machine paths.
- Prefer small JSON or TypeScript/JavaScript modules that can be reviewed directly.
- Generated outputs belong in temporary test directories and must be removed by the test before exit.
- Mock provider fixtures must keep chat, TTS, STT, safety, attention, language, and animation behavior local-only.

## M5 Behavior Fixture Rules

- Attention fixtures may describe `face_present`, `no_face`, `multiple_faces`, `looking_away`, `occluded`, `low_confidence`, and `camera_unavailable` as synthetic descriptors only.
- Camera fixtures must use frame descriptors with `rawFramePersisted: false`; committed fixtures must not include image base64, videos, screenshots, or downloaded model outputs.
- Language fixtures may use short synthetic or redacted transcript strings, transcript lengths, hashes, confidence values, empty speech, duplicate speech, and prompt counts.
- Data quality fixtures must keep device failures, low confidence, missing observations, and provider failures separate from child performance.
- Aggregation fixtures must not include final scores, diagnosis, norms, or percentiles.

## Environment Rules

- Backend and E2E tests must force mock or rule/noop providers when provider behavior matters.
- Tests must not require network access beyond local loopback processes started by the test itself.
- Tests must leave no background server, frontend preview, or watcher process running after completion.
