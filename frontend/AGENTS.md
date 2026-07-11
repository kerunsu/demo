# Frontend Agent Rules

## Responsibilities

- Child interaction screen.
- Future robot display screen.
- Frontend API client and event subscription client.
- Voice UI state, subtitles, playback UI, and animation simulator UI.
- Report presentation only after report schema and safety language are approved.

## Default Read Directories

- `frontend/`
- `docs/`
- `PROJECT_CONTEXT.md`
- `matching/`
- `paixu/`

## Default Write Directories

- `frontend/src/**`
- `frontend/AGENTS.md`
- frontend test files once a test directory exists.

## Forbidden Changes

- Do not change backend scoring, session, or report rules.
- Do not hardcode real external API keys.
- Do not make the frontend the source of truth for dual-screen synchronization.
- Do not add professional/diagnostic report claims without approved rules.

## Must Read

- `docs/SYSTEM_ARCHITECTURE_V2.md`
- `docs/INTERACTION_STATE_MACHINE.md`
- `docs/DOMAIN_EVENTS.md`
- `docs/ROBOT_ANIMATION_INTEGRATION.md`
- `docs/AI_CHILD_SAFETY_SPEC.md`

## Output Format

Summaries must list changed files, validation commands, and any contract assumptions.

## Tests

Prefer build, typecheck, and browser/E2E checks for UI changes.

## Do Not Start Implementation When

- domain events are not stable for cross-screen features;
- animation manifest is not available for real robot resources;
- safety text has not been reviewed for child-facing LLM output.
