# Testing and acceptance

The canonical collection is explicitly `python -m pytest tests -q`; it must not
discover `temp_clone/` or adjacent workspaces. No-hardware CI uses fake clock,
fake camera/microphone/Runtime, temporary session roots and monkeypatches. It
must not skip a real required-device assertion or alter product defaults.

Required automated gates:

- route/Socket snapshot and field-level fixture regression;
- golden training flow, cancel, idempotency, rooms, busy mutex and continuous
  recording;
- upload checksum/archive metadata and late Runtime upload;
- 0/1/N registry, stable track filenames, validator/timebase and read-only
  quality report;
- model mock/real selection, dialogue pause/health/fallback and V2
  profile publish/deploy/resolve/fallback;
- realtime phrase library selection, custom additions, per-course isolation,
  non-empty slots and ordering rule variants;
- Server-managed course preset create/edit/delete, ordered course expansion,
  default promotion, corrupt-file fail-closed behavior, invalid/empty-course
  rejection, and teacher/Server UI wiring to the shared API;
- naming/onomatopoeia keyword re-arm after hints and course-answer routing that
  cannot fall through into a blocking general-dialogue behavior, while an
  explicit wake-with-remainder course miss still reaches the dialogue reply;
- pairing/ordering assessment versus intervention policies, teacher “下一题”
  separation and repeat-click suppression, committed-frame-only question
  readiness, centred prompt focus, correlated speech-ended input gating and
  reduced-motion support;
- global attention/reward behavior ownership, Server phrase/action/expression/
  lower-screen configuration, playable-MP4 filtering, automatic-praise
  animation barriers and per-child teacher selection persistence;
- Robot Runtime release consistency (manifest size/SHA-256/embedded VERSION),
  rejection of a stale `latest` alias, lightweight-update selection, downgrade
  prevention, interrupted-download resume, verified executable staging and
  verified `/child` browser recovery after packaged startup/update;
- batch files/ZIP, malformed entries, duplicates, conflicts, rollback and
  asset-reference protection.

Required manual gates remain separate: real browser permissions and three-page
visual comparison; Robot Runtime/DollSer; 0/1/N physical ambient cameras and
microphones; unplug/busy/unwritable disk/Runtime restart; long-run resource
release; real ASR/LLM/TTS. A source test or fake protocol cannot substitute for
these gates.

Current 2026-08-24 evidence: `python -m pytest tests -q` passes 440 tests;
teacher `npm.cmd run build` succeeds; the 8080 teacher entry and hashed assets
return HTTP 200. The in-app browser passed the real `djt` session, student and
course selection, one normal prepare and one double-click prepare. Both reached
course selection without a dialog; Back cancelled each prepared workflow, and
the final lease file contained no lease. Browser console warnings/errors were
empty. This is not a full class or hardware pass: the child and Runtime were
offline, so start-course, COM3 motion, speech/expression/child synchronization,
finish, reconnect, Runtime restart and soak scenarios remain manual gates.

The Server-managed course preset addition passed real-browser checks against
8080: the preset editor loaded the seeded five-course default, exposed ordered
add/remove controls, and opened a new unsaved preset without mutating the
configuration. The teacher assessment selector displayed that default in its
dropdown and expanded the five courses to eight current items. The Vite-only
ControlPage preview verified the revised attention/reward cards and nested
reward-animation selector without starting a training session.

The interaction-latency addition is covered by deterministic correlation,
percentile, Markdown export, exact modality callback and Server console wiring
tests, including reused-training media isolation and safe recovery of old
misplaced rows. JavaScript syntax checks pass for the child timing fields and
latency dashboard. A Flask read-only request verified the Server page and the
real `djt-2-20260823-4` catalog/report path; the report recovered 881 legacy
rows by exact media ID without mixing the other retries. The page was not
driven through a live browser, and real cross-machine RTT, microphone/VAD,
media decode and Robot Runtime latency remain explicit manual measurements
described in `INTERACTION_LATENCY.md`.

Robot release evidence for `20260824-0036-DJT823`: the full-install and
lightweight-update ZIPs both pass central-directory/CRC checks, SHA-256, exact
size, embedded VERSION and child-recovery sidecar validation. The prior package
passed an isolated packaged-EXE start; live Flask requests advertise this exact
version and return HTTP 206 for both full and update packages. This build's
process launch was not repeated because the local execution policy rejected the
bounded cleanup step.
Physical in-place replacement of a running classroom Robot Runtime remains a
robot-machine manual gate.
