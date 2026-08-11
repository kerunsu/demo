# Stage 5 final acceptance and handoff

Audit scope: final traceability, compatibility, deliverability and evidence;
not a permission to hide failed hardware or browser gates.

## Verdict

**Conditional handoff — not a full production acceptance.** Automated software
gates are green for the current environment, but the release cannot be called
“fully complete” because real 0/1/N environment capture, strict first-sample
barrier, three-page browser acceptance, Robot/DollSer and real ASR/LLM/TTS have
not been executed. Legacy behavior remains the safe default.

## Automated evidence

| Gate | Evidence | Status |
|---|---|---|
| Python root tests | `python -m pytest tests -q` — 355 passed, warnings only | PASS |
| Stage 5 tests | seven `test_phase5_*` tests passed | PASS |
| Phase 4 regressions | asset/profile/gap tests — 12 passed in the focused run | PASS |

Historical Stage 5 baseline: 250 passed before the voice and encouragement-animation additions.
| Python entry compile | `python -m py_compile app.py` | PASS |
| HTTP/Socket snapshot | 171 source / 172 runtime / 67 events / 65 emits | PASS, `/teacher/` same-origin routes included |
| session quality | opt-in, read-only, legacy filenames and track metadata | PASS, fake/temp |
| ZIP asset import | bounded, safe names, per-item result/progress, commit rollback | PASS, fake/temp |
| browser `npm run build` | Vite production build completed and served by 8080 `/teacher/` | PASS |
| teacher browser smoke | real `djt` login and course selection at 1024×768; no console error/warn | PASS, no class start |
| Robot release integrity | build `20260809-2304-6836cbff`, SHA-256 and packaged COM3 verified | PASS, physical motion pending |
| bootstrap check | `.env` absent causes explicit non-zero | ENVIRONMENTAL, not masked |

## Required manual blockers

- Configure 0, 1 and N environment cameras/microphones from the control side;
  enumerate across Server/Runtime, set primary/required, preview and self-check.
- Unplug or occupy each required device and verify no formal recording starts,
  with exact `deviceId`/`trackId` error in the teacher UI.
- Verify primary compatibility files and all dynamic track manifests against a
  real session and common monotonic timeline.
- Complete browser start/finish, child/monitor permissions, reconnect and
  visual comparison; run the latest Robot Runtime/DollSer package and real
  voice providers. Login/student/course selection alone is not a class pass.
- Measure startup, idle resources, queues, analysis/report latency, stop/flush,
  reconnect and long-run thread/resource release.

Any failed manual gate keeps this verdict conditional and leaves the legacy
path enabled. No test may be deleted, weakened or skipped to change it.

## Deliverables

- `traceability.matrix.json`: every snapshot HTTP/Socket route, page, Runtime
  port, session file, configuration, interaction extension point and failure
  scenario with owner and evidence state.
- `FINAL_DEPENDENCY_MAP.md`, `CONTRACT_DIFF_REPORT.md`,
  `DEVICE_TRACK_ACCEPTANCE.md`, `INTERACTION_PROFILE_COMPATIBILITY.md`,
  `PERFORMANCE_COMPARISON.md`, `DEPRECATION_AND_CLEANUP.md` and
  `DEPLOYMENT_ROLLBACK.md`.
- Canonical root docs: `docs/ARCHITECTURE.md`, `CONTRACT.md`,
  `DATA_SCHEMA.md`, `CONFIGURATION.md`, `OPERATIONS.md`, `EXTENDING.md` and
  `TESTING.md`; previous versions are archived under
  `docs/archive/stage5-legacy/`.
- Additive control surface: `templates/server/config.html` plus
  `static/js/config_phase5.js`; it is deliberately separate from the existing
  teacher/child presentation and uses facade APIs only.

## Release decision

Release to fake/legacy-compatible staging is acceptable after rerunning the
frontend build. Release as the promised strict multi-hardware production
system is blocked by the manual items above.
