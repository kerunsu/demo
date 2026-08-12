# Contract — HTTP, Socket and Runtime

机器可读的 route/event 快照和所有权矩阵仍保留在 `docs/refactor/`，供测试和审计追溯；它们不是新的开发计划。快照发生变化时，必须同时补 fixture、变更说明和兼容性决定。

## Compatibility

- Existing URLs, methods, status codes, response envelopes, event names,
  rooms, ack order, request IDs and camelCase/snake_case aliases remain valid.
- New V2 endpoints are additive. They use a `success` envelope but do not
  normalize legacy errors.
- The legacy session files remain `video.avi`, `audio.wav`,
  `video.environment.avi`, `audio.environment.wav`, `timeline.csv`,
  `session_meta.json` and `archive_meta.json`.
- `sessionId`, `trainingSessionId`, `behaviorId`, `requestId`, `lineId` and
  `profileVersion` are correlation fields; a server-side frozen profile version
  wins over a later client value during the same session.

## Main flows

`login -> student/course selection -> prepare_training -> readiness ->
play_resource -> aux/analysis/dialogue -> teacher rating -> finalize -> report`
is one media session. `cancel_prepare_training`, retry, duplicate requests,
busy rejection, disconnect/reconnect, Runtime late upload and missing optional
devices are separate branches in the characterization suite.

The deployed topology is a single active Server, teacher controller, child
page and Robot Runtime. Starting a new training is an atomic workflow takeover:
the Server serializes prepare, closes every older active media session,
finalizes older behavior trainings and replaces the same teacher's old control
lease. A stale tab remains read-only and cannot mutate the replacement session.
Duplicate requests with the same logical prepare identity remain idempotent.

The production teacher SPA is served by Flask at `/teacher/`; `/teacher` and
the legacy `/therapist` entry redirect there by default. API, session cookie
and Socket.IO therefore share the 8080 origin. Port 5173 is only an explicit
Vite development surface and is not part of production startup.

Course prompts, hints, praise and social utterances use child-browser realtime
TTS only. Legacy course/item MP3 fields remain readable for stored-data
compatibility but are not selected by normal playback, even if an old
`DIALOGUE_TTS_MODE=file|both` environment value remains. The Server content
console manages a per-course-type enabled phrase set through
`GET /api/config/phrases`, `PUT /api/config/phrases/<intent>/<courseType>` and
`POST /api/config/phrases/<intent>/<courseType>/custom`. Every slot must retain
at least one enabled phrase; ordering rule questions keep separate variants.
The Server configuration console exposes device and recording operations as a
top-level page at `GET /server/config/devices`; the historical
`/server/config/content?view=phase5` browser URL redirects there.

## Versioned additive APIs

- `/api/v2/capture/devices` — configure/discover 0..N device profiles and freeze
  a snapshot. The current registry is configuration-only; it does not claim to
  be a physical capture broker.
- `/api/v2/assets/batch-import` — stage, preview, commit or roll back motions
  and emotions. Multipart files and bounded ZIP archives are supported.
- `/api/v2/interaction` — event catalog, draft/publish/deploy/rollback and
  resolution preview. Unmatched, draft or invalid profiles fall back to legacy.
- `GET /api/media/<sessionId>/status?includeQuality=1` — opt-in read-only
  storage/track/timeline health view; the default status response is unchanged.
- `GET /api/v2/control/overview` — default/configured device state plus a
  read-only child-grouped recording and file catalog.
- `POST /api/v2/control/devices/check` — bounded Server/Runtime first-frame and
  first-audio-chunk probes. Connected and capture-ready are separate fields.
- `POST /api/v2/control/sessions/<folderName>/reveal` — local-console-only,
  traversal-safe Windows folder reveal; it never accepts an arbitrary path.
- `GET /api/v2/config/sync/manifest` — read-only SHA-256 inventory of
  configuration-center files and an anonymized course catalog count.
- `GET /api/v2/config/sync/export` — ZIP export of Git-reviewable configuration
  and content assets; database, recordings and student PII are excluded.
- `GET /api/v2/voice/health` — read-only voice-service reachability, STT model
  readiness and Python dependency status for the child page and console.
- `GET /api/robot/animations`, `POST /api/robot/animations/upload`, and
  `DELETE /api/robot/animations/<name>` manage repository-tracked MP4
  encouragement animations. Referenced assets reject deletion unless the
  caller explicitly uses `force=1`.
- `PUT /api/robot/animations/<name>/rename` accepts `{ "newName": "...mp4" }`.
  It renames the repository file and updates all `course_map.json` animation
  references in the same operation, returning `referencesUpdated`.
- `GET|PUT /api/robot/motions/<name>/playback` reads or updates the per-motion
  `speedMultiplier` (`0.25..4.0`; `2.0` means twice as fast). The effective
  frames sent through local OSC, Robot Runtime and child-agent modes carry
  scaled `time` and `moveMs` values.
- `GET|PUT /api/robot/emotions/<name>/style` reads or updates per-emotion
  `speedMultiplier`, `scale`, `hueDeg`, `brightness`, `saturation` and
  `opacity`. MP4 supports `0.25..4.0` playback speed. Historical GIF remains
  readable but its speed is fixed at `1.0` because browsers cannot reliably
  retime an animated image.
- `GET|PUT /api/robot/emotions/global-filter` reads or updates the enabled
  environment-light correction (`hueDeg`, `brightness`, `saturation`,
  `contrast`, `opacity`). `robot_emotion_change` additively includes the
  effective `style` and `globalFilter`; existing consumers may ignore them.
  A save notification reuses this event with `settingsOnly=true`; the robot
  display applies it immediately without starting, interrupting or completing
  a behavior.

For a praise action, `course_map.json` may carry an `animation` filename next
to `motions`, `emotion`, and `sequence`. The server sends the resolved static
path as `behaviorAnimation`; the child reports completion through
`behavior_animation_ended`. When `animation` is empty or missing, the server
chooses a random MP4 from `static/resources/Animations/`. For one compatibility
release, `praiseVideo` and `praise_video_ended` remain aliases only; they no
longer select assets or contain a separate playback implementation.

Robot Runtime `POST /devices/check` proves first samples. Its additive
`record/start.captureDevices[]` freezes Runtime-owned environment tracks; a
required open failure rejects the start before the common runtime start time.
At stop, `trackManifest` and `track__<trackId>` multipart parts extend the
existing media upload without changing the legacy `video`/`audio` parts.

The teacher client requests `preflightMode=strict` by default for agent/Robot
Runtime capture. Browser capture retains `preflightMode=legacy` for backward
compatibility. In strict mode, formal recording cannot start until every
enabled and required device in the frozen profile passes its real-sample
preflight; optional or disabled devices may degrade with an explicit result.

## Room and security rules

Child behavior is sent only to `session_<id>_child`; teacher feedback is sent
to the teacher room/requester as defined by the frozen event fixture. An
unresolved child owner must not become a global broadcast. Runtime upload and
robot runtime requests retain their existing optional shared-key checks.

For `behavior-sync-v1`, the child heartbeat selects the Runtime physically
paired with the live child page. A behavior freezes that `runtimeBaseUrl` at
prepare time; commit and cancel must target the same Runtime even if another
installed Runtime sends a newer registry heartbeat. Runtime drops abandoned
prepared motions after 15 seconds by default, and a new `sessionId` may
supersede an older prepared transaction immediately. Exact three-ID checks and
idempotent replay remain mandatory.
