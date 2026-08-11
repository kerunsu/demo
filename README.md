# E.I.Art server_demo

Flask + Flask-SocketIO + SQLAlchemy/SQLite training system with teacher, child,
monitor/configuration and Robot Runtime clients. The application keeps the
legacy HTTP/Socket contracts and session filenames; the V2 control APIs are
additive and can fall back to the legacy path.

## Quick start

```powershell
.\start_server.ps1
```

`start_server.ps1` verifies requirement versions and imports, installs missing
Python/npm dependencies, and starts exactly one backend instance. Use
`.\start_server.ps1 -CheckOnly` for a read-only environment report. Direct
`python app.py` launches are also protected by the same single-instance lock.

Default endpoints: backend `http://127.0.0.1:8080`, teacher SPA
`http://127.0.0.1:8080/teacher/`, child `/child`, monitor/config `/server`, and Robot
Runtime `http://127.0.0.1:19091/ui`. `START_TEACHER_FRONTEND=0` and
`START_VOICE_SERVICE=0` retain the existing startup controls.

## Logs and diagnostics

- `logs/app.log` — all module logs (socket events, recording, robot service)
  append here since 2026-08-10; console shows `INFO`, file keeps `DEBUG`.
- `static/recordings/sessions/<course>/full_interaction_timeline.jsonl` — full
  audit stream of teacher/child clicks, robot modality events and every
  `play_resource_ack` (see [Operations](docs/OPERATIONS.md#application-logs)).
- For "clicked but nothing happened" incidents: search `app.log` for
  `play_resource 收到` / `行为繁忙拒绝` / `回执` and cross-check the timeline
  by `requestId`.

## Single sources of truth

- [Documentation index](docs/README.md) — current guides versus archived design history.
- [Architecture](docs/ARCHITECTURE.md) — six blocks and allowed dependencies.
- [Collaboration workspaces](docs/COLLABORATION.md) — frontend/backend/voice/model ownership and interface rules.
- [Contract](docs/CONTRACT.md) — HTTP, Socket, Runtime and compatibility rules.
- [Data schema](docs/DATA_SCHEMA.md) — SQLite, sessions, tracks and timeline.
- [Configuration](docs/CONFIGURATION.md) — environment, device profiles and assets.
- [Operations](docs/OPERATIONS.md) — health checks, backup, upgrade and rollback.
- [Extending](docs/EXTENDING.md) — devices, models, dialogue and interaction profiles.
- [Testing](docs/TESTING.md) — fake hardware, contract tests and release gates.
- [Stage 5 acceptance](docs/refactor/FINAL_ACCEPTANCE.md) — evidence and blockers.
- [Teacher lock fix 2026-08-10](docs/教师端Windows控制锁修复与验收记录-20260810.md)
  — Windows `Errno 22` root cause, recovery behavior and browser evidence.
- [Three-terminal stability work](docs/current/三端协同稳定性根因与分阶段整改方案.md)
  — root causes, implemented changes, field evidence and remaining soak tests.

Historical documents are retained under `docs/archive/` and are not normative.
Robot motion format references live with the workbench under `doll/DollSer/docs/`.
Never reset or clean a deployment containing `database/app.db`, recordings,
logs, release packages or course assets.
