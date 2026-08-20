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

Generated LLM dialogue replies may add a configured MP4 expression selected by
effective reply length. When matched, speech and expression share one reserved
behavior ID, request ID, session ID and start anchor; both completion barriers
must settle before the behavior slot is released. If the behavior slot is still
held by a course utterance, the reply is queued and starts after that terminal
event; a leftover formal expression from the already-released previous behavior
must not block the matched MP4. Missing, disabled or invalid configuration
preserves the existing audio-only dialogue path. Wake replies and course
question/praise/hint speech are outside this matcher.

## Versioned additive APIs

- `/api/v2/capture/devices` — configure/discover 0..N device profiles and freeze
  a snapshot. `GET /api/v2/capture/devices/candidates` probes Server cameras
  without changing configuration; `POST` to that path explicitly persists one
  candidate. Only enabled, configured Server cameras are exposed as 0..N
  `ambient.cameras[]` by the monitor snapshot and accepted by the per-device
  preview endpoint. A Server camera passes preflight only after this shared
  preview broker obtains its first frame.
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
- `GET|PUT /api/robot/emotions/idle-pool` reads or replaces the non-empty
  random idle-expression pool. The historical `default` field and endpoint
  remain compatible and represent the first pool item. Idle media is locally
  interruptible by a formal interaction expression; a formal expression plays
  atomically to its media end (except an explicit behavior cancellation), then
  the display runs any queued formal expression or returns to random idle. A
  successful pool update emits `robot_idle_pool_changed` so an online robot
  display applies the new pool without a page refresh.
  MP4 display uses two alternating browser buffers: the outgoing expression
  reaches its natural media end and holds its final decoded frame while the
  incoming expression renders its first frame off-screen. The display then
  performs a short crossfade and only the active buffer may emit completion.
  A load or decode failure keeps the last valid frame visible instead of
  exposing the black page background.
- `GET|PUT /api/robot/emotions/dialogue-reply-rules` manages the ordered MP4
  expression rules used only by generated LLM dialogue replies. Rules match
  whitespace-free character counts by increasing upper bound; the final rule
  is also the overflow fallback.

For a praise action, `course_map.json` may carry an `animation` filename next
to `motions`, `emotion`, and `sequence`. The server sends the resolved static
path as `behaviorAnimation`; the child reports completion through
`behavior_animation_ended`. When `animation` is empty or missing, the server
chooses a random MP4 from `static/resources/Animations/`. For one compatibility
release, `praiseVideo` and `praise_video_ended` remain aliases only; they no
longer select assets or contain a separate playback implementation.
After a praise animation reaches its media end, the child keeps its final frame
visible while still emitting `behavior_animation_ended` on time. The frame is
cleared only after the next course resource commits successfully, or when the
teacher leaves; duplicate, pending, or failed resource transitions do not
restore the previous question screen.
Pairing and ordering in-item auto-praise uses the same `aux.praise` animation
resolver as a teacher praise click, but sets `holdLastFrame=false` /
`interactiveAutoPraise=true` so the overlay clears at media end. That automatic
package does not open the teacher rating dialog and does not advance the course
item. `behavior_animation_ended` still releases the reserved behavior even when
there is no teacher `play_request`; otherwise the next item question stays
queued behind `animationExpected`. A pairing wrong tap ends the question: all
options dim and the game waits for encourage speech before the next item
question.

The teacher arms praise-to-rating correlation before emitting `play_resource`.
The rating dialog is queued once by the correlated animation terminal event or
the overall `behavior_completed` event, with a bounded timeout as fallback.
Missing or degraded animation must show a notice but must not suppress rating.

Pairing and ordering item questions are idempotent by course type, question ID
and question index. A duplicate game-start or ready event for the visible item
must not replay or preempt its active question. Child answer submission does not
cancel a question already being spoken; feedback waits for that sentence to
reach its terminal event. A real transition to a newer item may supersede the
older pending question.
Each runtime session has at most one pending item-question flush loop. A busy
behavior is never aborted to make room for a question: the latest visible item
wins and starts immediately after the active utterance ends. Question speech,
expression and motion share the same behavior start anchor. Pairing and ordering
advance normally only on an `ended` speech terminal; stopped or dropped speech
waits for the bounded failure timeout instead of being treated as complete.
Praise and encourage clicked while a question is still speaking are queued and
start as soon as that question reaches a terminal event; they must not exhaust a
short retry budget and leave the game waiting. Generated LLM replies that arrive
while a course utterance still owns the behavior slot are likewise queued, and
their matched expression may immediately replace leftover formal media from the
previous already-released behavior.

After robot question speech ends, continuous ASR keeps a short speaker-tail
preroll instead of muting for most of a second, so a child answer that starts
quickly is still recognized. Identical or nested transcripts from overlapping
ASR windows are suppressed for several seconds so one spoken sentence does not
appear many times in the child dialogue UI.

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
