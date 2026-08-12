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
- batch files/ZIP, malformed entries, duplicates, conflicts, rollback and
  asset-reference protection.

Required manual gates remain separate: real browser permissions and three-page
visual comparison; Robot Runtime/DollSer; 0/1/N physical ambient cameras and
microphones; unplug/busy/unwritable disk/Runtime restart; long-run resource
release; real ASR/LLM/TTS. A source test or fake protocol cannot substitute for
these gates.

Current 2026-08-10 evidence: `python -m pytest tests -q` passes 355 tests;
teacher `npm.cmd run build` succeeds; the 8080 teacher entry and hashed assets
return HTTP 200. The in-app browser passed the real `djt` session, student and
course selection, one normal prepare and one double-click prepare. Both reached
course selection without a dialog; Back cancelled each prepared workflow, and
the final lease file contained no lease. Browser console warnings/errors were
empty. This is not a full class or hardware pass: the child and Runtime were
offline, so start-course, COM3 motion, speech/expression/child synchronization,
finish, reconnect, Runtime restart and soak scenarios remain manual gates.
