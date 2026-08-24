# Data schema and session dataset

## Persistent stores

- SQLite `database/app.db`: teachers, students, course types, courses/items,
  training sessions/details and report records. Existing databases are read
  and upgraded in place; reset is never a normal deployment operation.
- Read-only content catalog: CSV/YAML/JSON/static media and audio manifests.
- Teacher course presets: versioned `config/course_presets.json`, containing
  one `defaultPresetId` and ordered `courseIds` per preset. It stores no copied
  course or item payload and is replaced atomically.
- Session directory: `static/recordings/sessions/<human-dir>/` when the
  continuous recorder has a human directory binding, otherwise the legacy
  session directory. The directory resolver owns this choice.

`<human-dir>` remains a flat, compatibility-safe name such as
`姓名-年龄-YYYYMMDD-N`. The control console groups these directories by
`studentId` for browsing; it does not move historical data into new folders.
This keeps old analysis scripts working while making each child's sessions
and files visible together.

## Compatibility files

| File | Meaning |
|---|---|
| `video.avi` | child/primary video |
| `audio.wav` | child/primary audio |
| `video.environment.avi` | first `primary_environment` video |
| `audio.environment.wav` | first `primary_environment` audio |
| `video.environment.<trackId>.avi` | additional environment video |
| `audio.environment.<trackId>.wav` | additional environment audio |
| `timeline.csv` | one continuous session timeline; course changes append rows |
| `session_meta.json` | session, track manifest, clock/quality and effective versions |
| `archive_meta.json` | Runtime late-upload source, checksum and saved-file metadata |

The primary compatibility names cannot be renamed or replaced by MP4. MP4 may
only be a later derived export. A `tracks[]` entry contains stable `trackId`,
`kind`, `role`, `deviceId`, `runtimeId`, `required`, `filename`, `format`,
clock domain and quality fields. Missing drop/offset fields mean “not recorded”,
not zero.

All track timestamps are normalized to the session monotonic time base; wall
clock is explanatory metadata only. The read-only validator and the opt-in
quality view never repair or create files.

For Runtime multi-track recording, all configured handles are opened before
`runtime.session.monotonic` t=0. Each track records `firstFrameAt` or
`firstChunkAt`, counters and terminal status in `tracks[]`; these offsets make
the small thread-start skew explicit for later alignment.

## Interaction timeline

Each training session may contain
`static/recordings/behavior/<trainingSessionId>/interaction_timeline.jsonl`.
Every line is an immutable `InteractionEvent` with correlation IDs, actor,
server timestamp, state transition, degradation/error fields and metadata.
Stable events include `question_presented`, `question_audio_ended`,
`no_response`, `question_repeat`, `hint`, `reminder`, `child_response`,
`praise`, `attention_intervention`, `attention_reward`, `rating` and
`next_question`; modality events use the same timeline.

Response latency is server-authoritative: first valid `child_response` minus
first `question_audio_ended`, with latest-prompt latency retained separately.
Historical sessions may use the legacy client value. Behavior JSON uses a
same-directory temporary file, `fsync`, and atomic replacement.

### Full interaction audit timeline

New sessions also write
`static/recordings/sessions/<humanCourseDirectory>/full_interaction_timeline.jsonl`,
beside that course's `video.avi`, `audio.wav`, `timeline.csv`, and
`session_meta.json`.
This append-only `full-interaction-timeline-v1` stream is the test/audit view,
not a replacement for either legacy timeline. Each row has a server-assigned
`sequence`, UTC `timestamp`, `serverEpochMs`, `serverMonotonicMs`, optional
client timestamp/clock offset, correlation IDs, actor/source/category,
event/phase/status/modality, degradation/error data and bounded `details`.

The recording folder is resolved by the pair `trainingSessionId + mediaSessionId`
stored in `session_meta.json`; no second audit folder is created under the
internal UUID. A training ID may be reused by a retry, so the writer cache,
sequence counter, read API and exports are all bound to the exact media session.
An unqualified legacy read selects only the latest matching media session and
must never merge rows from multiple recording folders.
Raw audio/video payloads are replaced by byte length and SHA-256; credentials
are redacted. Same-host writers use an OS file lock. Query with
`GET /api/v2/timeline/<trainingSessionId>?mediaSessionId=<id>` and export with
`?format=csv` or `?format=jsonl` while retaining the same media-session filter.

Recorded events include browser-emitted socket traffic (teacher and child UI,
recorded by the browser itself before dispatch), robot execution/modality
events, and server-side decisions. Every `play_resource_ack` emitted by the
server is recorded as `event: play_resource_ack` with `phase: response`; its
`status` is `accepted` on success or the rejection reason (`behavior_busy`,
`control_lease_missing`, `observer_read_only`, `behavior_start_failed`, …),
with `details.busy`, `details.remainingMs` and `details.activeBehaviorId` so
"clicked but nothing happened" can be attributed to an exact refusal branch.

Latency instrumentation is additive. Teacher `play_resource` may carry
`clientCommandAtMs`, `teacherNetworkRttMs` and `clientTransport`; old clients
remain valid when these fields are absent. The Server records
`latency.play_resource_received`, `latency.multimodal_dispatched`, and exact
Socket callback receipts as `latency.modality_ready_callback` /
`latency.modality_started_callback`. Endpoint callbacks may additionally carry
`commandReceivedAtClientMs`, `readyAtClientMs` and `actualAtClientMs`. A child
`resource_ready` also carries bounded `timing` for preflight, load/decode,
paint wait, crossfade and total client transition. Natural-dialogue rounds use
one `requestId` from VAD capture through STT, answer/wake/LLM decision, TTS
dispatch, browser receipt, actual speech start and speech end. These fields are
diagnostics only and cannot alter scheduling, acceptance or state transitions.
The derived `interaction-latency-report-v1` contains per-session P50/P95/max
summaries, per-request Server/network/sync stages, per-modality observations,
natural-dialogue stage summaries, data-isolation status, automatic findings
and the static voice-strategy review. See
`docs/INTERACTION_LATENCY.md` for formulas and clock-domain limits.

## Robot asset display tuning

`doll/data/motions.json` remains schema version 2. Optional
`motionMeta.<motionName>.speedMultiplier` is a finite number in `0.25..4.0`;
missing or invalid historical values read as `1.0`. The source frames are not
rewritten. Runtime playback derives effective `time` and `moveMs` by dividing
both fields by the multiplier, so Git diffs retain the original recording.

`doll/data/emotions_meta.json` schema version 2 contains `default`, `idlePool`,
`styles` and `globalFilter`. `idlePool` is a non-empty ordered set of emotion
filenames used for random, non-repeating-when-possible idle playback;
`default` mirrors its first item for older clients. A `styles.<filename>` object has `speedMultiplier`
(`0.25..4.0`, MP4 only), `scale` (`0.5..2.0`), `hueDeg` (`-180..180`),
`brightness`/`saturation` (`0..2`) and `opacity` (`0..1`). Missing styles use
identity values. `globalFilter` adds `enabled` and `contrast` (`0..2`) to the
color/opacity fields. Rendering applies the per-emotion transform/filter to
the media first, then the global filter on its parent layer. This layer exists
only on the robot emotion page and cannot affect child-screen animations.

Both metadata files use a same-directory temporary file, `fsync` and atomic
replacement. Commit these JSON files together with assets so a Git pull or
process restart restores the same effective appearance.

## Server camera registry

Local camera discovery is candidate-only and does not write configuration.
After explicit operator confirmation, an automatically added camera is stored
in `config/capture_devices.json` with `deviceId=server.camera.<index>`,
`owner=server`, and `selector.index=<operating-system index>`. The first local
camera receives role `primary_environment`; later cameras receive
`environment_secondary`. Removing or disabling the profile removes it from
future preflight checks and monitor preview without changing historical
session manifests.
