# Architecture — six blocks

This is the current implementation boundary. It is a migration architecture:
legacy modules remain behind adapters until a contract-protected slice is
replaced.

| Block | Owns | Does not own |
|---|---|---|
| Frontend Web | `teacher_frontend`, `templates`, `static/js`, monitor/config/report/child-animation pages | DB, server paths, hardware implementations |
| Backend facade | Flask app/bootstrap, blueprints, Socket registration, auth/validation, DTO presentation | scoring, recording, file writes, LLM, hardware details |
| Acquisition | browser uplink, server environment capture, device discovery, capture lifecycle | session filenames, report formulas, dialogue policy |
| Storage | SQLite, session layout, metadata/timeline, reports, asset/config catalog | Socket room decisions, device I/O, LLM |
| Computation | readiness, analysis/model plugins, scoring, progression, decisions, InteractionProfile resolver | Flask/Socket transport, recording codecs, dialogue provider |
| Dialogue | wake/ASR/context/LLM/TTS and speech orchestration | DB, recorder, mechanical or expression output |

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
remain compatibility owners. In Demo, `app/robot` is only a historical name for
speech/child-animation coordination; the hard capability policy prevents any
mechanical, Runtime or full-version expression output. New modules must
be lazy on import: no thread, camera, microphone, file or DB mutation at import
time. The composition root is `app.py` plus `app/facade/bootstrap.py` until a
later release proves a complete application factory.

## Runtime invariants

`prepare_training` reserves a session and verifies browser permission/device
readiness. A successful path starts one continuous recording, verifies required
first samples and rolls back partial resources on failure. Course changes append
timeline segments and never restart the session recording. Only pairing and
ordering can enter this flow; reports project the same fixed course scope.
