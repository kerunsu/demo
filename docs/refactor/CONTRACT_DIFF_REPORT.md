# Contract difference report

## Frozen surface

`contracts.snapshot.json` currently records 171 source routes, 172 runtime rules
(including `/static/<path:filename>`), 67 registered Socket events and 65
literal server emits. Runtime URL and Socket registration cross-checks are
green. No legacy route, event, room, session filename or default was renamed.

## Approved additive changes

1. `POST /api/v2/interaction/profiles/<course_id>/deploy` adds explicit rollout
   stage selection; unpublished or invalid profiles remain off runtime.
2. `GET /api/media/<session_id>/status?includeQuality=1` adds an opt-in read-only
   `quality` field. Without the query parameter the old response shape remains.
3. Batch asset staging accepts a bounded `.zip` upload and adds `progress` and
   per-entry validation results. Existing multipart files and commit/rollback
   envelopes remain valid.
4. V2 speech is sent through the existing child-targeted `robot_speak_text`
   event only when the profile explicitly configures speech; legacy audio is
   retained otherwise.
5. `GET /teacher`, `GET /teacher/` and
   `GET /teacher/<path:asset_path>` add the production same-origin teacher SPA;
   the legacy `/therapist` entry remains and now defaults to `/teacher/`.
6. Runtime behavior synchronization additively pins one registered Runtime for
   prepare/commit/cancel and exposes `preferredRuntimeId` in Runtime status.
   Prepared behavior TTL and cross-session takeover change internal recovery,
   while exact envelope fields and existing endpoints remain unchanged.

## Known non-equivalence risks

- Checksum mismatch in the historical `/upload` path is logged but still
  accepted; changing that would be a product behavior change and is a separate
  compatibility decision.
- Current V2 shadow comparison is in-process and not a durable historical
  report; canary stage selection is not a full deployment service.
- The device registry does not prove physical health or first samples.
