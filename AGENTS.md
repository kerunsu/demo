# Codex Agent Rules

## Scope

This repository is currently a runnable local Web Demo. Agents must preserve the existing demo unless a task explicitly asks for implementation changes.

## Default Rules

- Read `PROJECT_CONTEXT.md`, `docs/ONBOARDING.md`, `docs/ENVIRONMENT.md`, `docs/TARGET_PRODUCT_REQUIREMENTS.md`, `docs/SYSTEM_ARCHITECTURE_V2.md`, `docs/DOMAIN_EVENTS.md`, and `docs/MULTI_AGENT_DEVELOPMENT_PLAN_V2.md` before changing architecture, shared contracts, or workflow.
- Do not add real API keys, credentials, tokens, or paid external service calls.
- Do not enable real STT/TTS/LLM providers without explicit approval and a safety review.
- Do not modify existing business code during documentation-only tasks.
- Do not delete old prototypes, assets, or historical files unless explicitly requested.
- Treat `frontend/src/App.tsx`, `backend/src/index.ts`, and `backend/src/services/sessionService.ts` as hotspot files. Only one Agent may own each hotspot in a development wave.
- Shared contracts, domain events, schemas, and report metrics need a single Owner.
- Every implementation task needs an independent test or reviewer pass before it is considered complete.

## Fact Language

Use these labels in docs when relevant:

- `当前事实`: verified from repository code or existing docs.
- `建议`: architecture recommendation.
- `待确认`: product owner or expert decision required.

Do not describe future design as already implemented.

## Testing Expectations

At minimum, run the relevant build or validation command after edits. For this repository, the current baseline validation is:

```bash
npm run build
git diff --check
```

## When Not To Implement

Do not start implementation when:

- the event contract is not fixed and the task depends on cross-screen sync;
- the provider interface is not fixed and the task depends on real STT/TTS/LLM;
- safety review is required but not designed;
- professional scoring rules are required but not provided;
- the task would send child data to external services without approval.
