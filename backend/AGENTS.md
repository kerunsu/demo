# Backend Agent Rules

## Responsibilities

- Express API.
- Session orchestration.
- Domain events.
- Provider interfaces and Mock providers.
- Behavior observation ingestion.
- Assessment engine boundaries.
- Safety gateway boundaries.

## Default Read Directories

- `backend/`
- `docs/`
- `PROJECT_CONTEXT.md`
- `matching/`
- `paixu/`

## Default Write Directories

- `backend/src/**`
- `backend/AGENTS.md`
- backend test files once a test directory exists.

## Forbidden Changes

- Do not enable real external providers without explicit approval.
- Do not log child raw names, chat text, audio base64, video frames, API keys, or full model error responses.
- Do not let LLM output bypass child safety review.
- Do not invent professional scoring rules.

## Must Read

- `docs/DOMAIN_EVENTS.md`
- `docs/SPEECH_LLM_PIPELINE.md`
- `docs/BEHAVIOR_ASSESSMENT_DATA_MODEL.md`
- `docs/AI_CHILD_SAFETY_SPEC.md`
- `docs/DECISIONS_REQUIRED.md`

## Output Format

Summaries must list changed files, APIs or schemas touched, validation commands, and safety implications.

## Tests

Backend work should include build validation and, once tests exist, API/provider/contract tests.

## Do Not Start Implementation When

- provider interfaces are unresolved;
- data retention or external service decisions are unresolved;
- formal scoring rules are needed but not provided;
- changes would require real paid external services.
