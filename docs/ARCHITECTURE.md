# Architecture — six blocks

This is the current implementation boundary. It is a migration architecture:
legacy modules remain behind adapters until a contract-protected slice is
replaced.

| Block | Owns | Does not own |
|---|---|---|
| Frontend Web | `teacher_frontend`, `templates`, `static/js`, monitor/config/report/robot pages | DB, server paths, hardware implementations |
| Backend facade | Flask app/bootstrap, blueprints, Socket registration, auth/validation, DTO presentation | scoring, recording, file writes, LLM, hardware details |
| Acquisition | browser/Runtime uplink, server environment capture, device discovery, capture lifecycle | session filenames, report formulas, dialogue policy |
| Storage | SQLite, session layout, metadata/timeline, reports, asset/config catalog | Socket room decisions, device I/O, LLM |
| Computation | readiness, analysis/model plugins, scoring, progression, decisions, InteractionProfile resolver | Flask/Socket transport, recording codecs, dialogue provider |
| Dialogue | wake/ASR/context/LLM/TTS and speech orchestration | DB, recorder, direct robot implementation |

`app/contracts` is a framework-free shared kernel, not a seventh block. It
contains DTOs, Protocols, event envelopes, time points and error semantics only.

## Dependency rules

```text
frontend -> facade -> {acquisition, storage, computation, dialogue}
acquisition -> contracts + storage ports
computation -> contracts + storage/acquisition ports
dialogue -> contracts + speech/robot ports
storage -> contracts
```

Legacy `app.py`, `app/sockets`, `app/services`, `app/robot` and `app/recorder`
remain compatibility owners where the migration log says so. New modules must
be lazy on import: no thread, camera, microphone, file or DB mutation at import
time. The composition root is `app.py` plus `app/facade/bootstrap.py` until a
later release proves a complete application factory.

## Runtime invariants

`prepare_training` may reserve a session and legacy warmup remains compatible;
strict preflight is opt-in until the real Server/Runtime device broker is
connected. A successful strict path must check every enabled+required module,
reserve devices, start one continuous recording, verify each required first
sample, and roll back partial resources on failure. Course changes append
timeline segments and never restart the session recording.
