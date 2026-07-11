# M6/M7 Technical Decisions

This file records compact default decisions for the long-run M6/M7 execution. It does not override project owner decisions.

## M6 Defaults

- Deterministic metrics are computed from structured data and evidence references, not from free-form LLM output.
- LLM output may explain, encourage, or summarize only after input minimization and child-safety review.
- Missing cloud credentials produce `CREDENTIALS_PENDING`, not a global stop.
- Formal scoring weights, clinical interpretation, norms, and percentiles remain `OWNER_REQUIRED_BEFORE_SCORING`.
- Reports must say training performance or educational reference, not clinical diagnosis.
- No real API key, child raw audio, child raw video, or raw camera frames may be committed.

## M7 Defaults

- Deployment targets Windows robot browser terminals plus an independent backend/server host over LAN.
- Configuration must be environment-driven and secret-free in Git.
- Services must have health checks, restart scripts, logs with size bounds, backup, deletion, and rollback instructions.
- Real robot, classroom, dual-host LAN, microphone, speaker, camera, long-run stability, and human review can remain `ENVIRONMENT_PENDING` when unavailable.

## Stop Conditions

Stop globally only if implementation requires unauthorized child data, real secrets in Git, external upload of raw media, an unrecoverable data leak, violation of project owner decisions, unsafe Git state, or a system-wide architecture decision without a documented default.
