# Current state baseline — Stage 5 audit

Audit date: 2026-08-06  |  branch: `add_voice`  |  HEAD:
`6836cbffa882e768912cb96e9d2f7bcd01f13d4c`

The worktree was already dirty before this audit. Existing user changes,
`database/app.db`, recordings, logs, releases, `__pycache__`, frontend
`node_modules`/Vite cache and `temp_clone/` were not reset, cleaned, deleted or
used as test collection roots.

## Current command evidence

| Command | Result | Interpretation |
|---|---|---|
| `python -m pytest tests -q` before Stage 5 additions | 243 passed, warnings only | root `tests/` only; pre-change baseline green |
| `python -m pytest tests -q` after Stage 5 additions | 250 passed, warnings only | 7 new `test_phase5_*` tests; final automated baseline green |
| Stage 5 additions + Phase 4 regressions | 15 passed | read-only quality and ZIP import contracts green |
| `python -m py_compile app.py` | passed | startup entry compiles |
| `npm run build` in `teacher_frontend` | must be rerun in final gate | existing `node_modules` was preserved |
| `python scripts/bootstrap.py --check-only` | expected fail if `.env` absent | `.env` is local-only; not a code regression |

The earlier Phase 1 document value of 170/194 and earlier Phase 3/4 values are
historical, not the current count. The pre-change root baseline was 243 passed;
the final Stage 5 tree is 250 passed after seven additive tests.

## Runtime facts

`app.py` remains the real startup/composition compatibility entry. It registers
Flask, SocketIO, database, legacy and V2 blueprints, dialogue/audio handlers,
analysis and Robot Runtime adapters. `app/facade/bootstrap.py` is a lazy
composition skeleton, not yet the sole production composition root.

The current inventory is 171 source routes, 172 runtime URL rules including
Flask's implicit static rule, 67 Socket handlers and 65 literal server emit
names. The machine-readable snapshot and runtime cross-check are authoritative;
the earlier Stage 5 counts above remain historical baseline evidence.

## Known gaps that block a full release declaration

1. `InMemoryDeviceRegistry` persists 0..N configuration, but the registry is
   not connected to a real per-device Server/Runtime capture broker. Physical
   self-check, reservation, first frame/audio block and multi-track recording
   still require hardware integration.
2. Strict preflight exists behind an opt-in path and fake tests, but the
   production default remains legacy-compatible. It must not be described as
   “all devices passed before every production capture” until the broker is
   connected.
3. The existing control center now has an additive “设备与交付” surface for
   registry, read-only session quality, batch files/ZIP and V2 resolution
   preview. It has not received browser visual acceptance, and it does not
   claim to provide physical device self-check or full V2 authoring/publish UI.
4. Real browser permissions, Robot Runtime/DollSer, ambient camera/microphone,
   ASR/LLM/TTS and long-run resource-release checks are not executable in this
   no-hardware audit.

## Historical test files

Commit `8bfba1f7` (2026-04-21) removed `tests/test_analysis_integration.py`
(521 lines), `tests/test_mediapipe_pose.py` (330) and
`tests/test_real_pose_integration.py` (358), 1209 lines total. They depend on
`mediapipe`/`torch` unavailable in the current environment. This audit did not
delete them; each can be restored from Git history when those dependencies are
available. `bootstrap --check-only` missing `.env` is handled as an environment
precondition, not hidden as a pass.

## Next exact entry

Before enabling strict preflight or changing production defaults, implement a
real `DeviceBroker` adapter for Server and Runtime, wire it through the
composition root, and add fake + hardware evidence for every required track.
Then add browser acceptance for the additive control-center panels. Until those
two gates pass, keep legacy capture and InteractionProfile fallback enabled.
