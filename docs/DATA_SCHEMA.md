# Data schema and session dataset

> Demo 数据事实：`config/demo_course_scope.json` 固定两课型；`config/demo_deployment.json` 固定禁用机械动作和 Robot Runtime、启用屏幕表情。全新数据库仅播种命名和排序；旧数据库原地升级并保留历史行，但活动目录、预设、分析投影和新报告不会暴露其他课型。

## Persistent stores

- SQLite `database/app.db`: teachers, students, course types, courses/items,
  training sessions/details and report records. Existing databases are read
  and upgraded in place; reset is never a normal deployment operation.
- Read-only content catalog: CSV/YAML/JSON/static media and audio manifests.
- Teacher course presets: `config/course_presets.json` schema v3, containing
  separate assessment/intervention defaults and ordered
  `courseSelections[{courseType,itemIds}]`. It stores reviewed item identities,
  validates them against the canonical Demo catalog and is replaced atomically.
- Demo deployment capabilities: `config/demo_deployment.json` schema v1.
  Invalid or missing data falls back to the reviewed Demo capability set:
  `robotMotion=false`, `robotExpression=true`, `robotRuntime=false`.
- Demo course scope: `config/demo_course_scope.json` schema v1. The current
  deployment enables `naming` and `ordering`; database rows and assets for
  disabled historical courses remain in place but are excluded from active
  catalogs, presets, sync catalog exports and newly generated report projections.
- Session directory: `static/recordings/sessions/<human-dir>/` when the
  continuous recorder has a human directory binding, otherwise the legacy
  session directory. The directory resolver owns this choice.
- Behavior directory: new continuous sessions use the exact same readable
  name at `static/recordings/behavior/<human-dir>/`. The training UUID remains
  `training_session_id` inside `training.json` and every observation; it is not
  the new directory name. Historical `behavior/<trainingSessionId>/` data stays
  readable and is not moved automatically.
- Report drafts use `report.json`; an approved immutable delivery snapshot uses
  `report.published.json`. Ordinary status polling and repeated generation do
  not remove or downgrade that published snapshot. `publicationStatus` changes
  to `pending_review` once per new draft and to `published` on approval.
  New report snapshots add `courseScope`, `courseGoalScore` and
  `courseEvaluations[]` without
  removing legacy scores. Each course evaluation has `courseType`, display
  `label`, `status`, nullable `score`/`gapToTarget`, `targetScore`, `itemCount`
  and `teacherRatingCount`; an unassessed enabled course stores null scores,
  never zero. On the demo machine the array and course-score maps contain only
  naming and ordering.
  Rule-generated recommendations are structured as `priority`, `title`,
  `evidence`, `practice`, `why` and `progressCheck`. These fields explain the
  observed session and do not represent population norms. New narratives add
  teacher-facing `headline` and `overview.{overall,stable,attention,boundary}`.
  These strings are derived only from the current report snapshot. The teacher
  client may project older `analysis`/`body` values into the same visual
  structure, but it does not mutate historical files or infer a missing score.

`<human-dir>` remains a flat, compatibility-safe name such as
`姓名-年龄-YYYYMMDD-N`. The control console groups these directories by
`studentId` for browsing; it does not move historical data into new folders.
This keeps old analysis scripts working while making each child's sessions
and files visible together.

Directory binding and read-only lookup are side-effect free. A preflight
reservation, status query, missing report lookup or `Session` object creation
must not create a directory. `sessions/<human-dir>/` is created by the first
timeline/metadata/media write, and `behavior/<human-dir>/` by the first behavior
record. Normal continuous recording no longer creates fallback UUID directories
directly under `static/recordings/`. Failed or cancelled preflight therefore
leaves no empty per-session directory.

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
| `dialogue_timeline.txt` | server-ordered child/Maimai chat bubbles with wall time, session-monotonic offset and request ID |
| `session_meta.json` | schema v2 session identity, shared behavior directory, track manifest, clock/quality and effective versions |
| `archive_meta.json` | Runtime late-upload source, checksum and saved-file metadata |

The primary compatibility names cannot be renamed or replaced by MP4. MP4 may
only be a later derived export. A `tracks[]` entry contains stable `trackId`,
`kind`, `role`, `deviceId`, `runtimeId`, `required`, `filename`, `format`,
clock domain and quality fields. Missing drop/offset fields mean “not recorded”,
not zero.

New continuous sessions declare `schemaVersion: 2`, `behaviorDirName` equal to
`humanDirName`, `clockDomain: server.session.monotonic`, and the compatibility
`child_video`/`child_audio` entries in `tracks[]`. Runtime environment tracks
are merged additively. Finalization updates session status/duration/segment
fields without replacing existing track or quality fields. `session_meta.json`,
`timeline.csv` and `dialogue_timeline.txt` use same-directory temporary files,
`fsync`, and atomic replacement.

`dialogue_timeline.txt` is created on the first non-empty child chat bubble for
that media session. Rows are assigned a six-digit server sequence and contain
the server-local ISO timestamp, a millisecond `T+HH:MM:SS.mmm` offset in the
same `server.session.monotonic` clock domain as the recording timeline, the
visible role (`儿童` or `麦麦`), `requestId`, and the exact displayed text.
Newlines, tabs and the column separator inside content are losslessly escaped.
If a Server restart has removed the in-memory monotonic origin, the writer
derives `T+` from `recordingStartedAtUnix` and still clamps it to the last row so
the durable sequence never moves backwards.
Only visible chat content is included: UI status/error hints and internal audit
events remain in their existing channels. The writer resolves the durable
`mediaSessionId` binding and never creates a fallback UUID session directory.

Runtime archive upload repeats the validated `humanDirName`. If the Server's
in-memory binding was lost, this name may restore the mapping only when the
target is absent or its metadata already belongs to the same `mediaSessionId`;
an occupied name is never reused for another session.

All track timestamps are normalized to the session monotonic time base; wall
clock is explanatory metadata only. The read-only validator and the opt-in
quality view never repair or create files.

For Runtime multi-track recording, all configured handles are opened before
`runtime.session.monotonic` t=0. Each track records `firstFrameAt` or
`firstChunkAt`, counters and terminal status in `tracks[]`; these offsets make
the small thread-start skew explicit for later alignment.

## Interaction timeline

Each new training session may contain
`static/recordings/behavior/<human-dir>/interaction_timeline.jsonl`; historical
`static/recordings/behavior/<trainingSessionId>/` remains readable.
Every line is an immutable `InteractionEvent` with correlation IDs, actor,
server timestamp, state transition, degradation/error fields and metadata.
Stable events include `question_presented`, `question_audio_ended`,
`no_response`, `question_repeat`, `hint`, `reminder`, `child_response`,
`praise`, `attention_intervention`, `attention_reward`, `rating` and
`next_question`; modality events use the same timeline.

Historical mimic actions may append one `child_response` for compatibility, but
`mimic` is outside the active Demo course scope. Its legacy metadata uses
`courseType=mimic`, `modality=pose`, `isCorrect=true`, the
0..1 `score` and `threshold`, `algorithmVersion`, visible-joint `coverage`,
`mirrored`, `stableFrames` and `holdMs`. These are recognition evidence, not a
teacher-visible diagnosis. Repeated successful frames for the same
training/question/item do not append another response or praise request.

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

Child screen input is additive to the same full audit file; there is no second
raw click file. `child_screen_tracking_started` distinguishes a tracked session
with zero clicks from an older/unavailable session. Each trusted primary
`pointerdown` produces `child_screen_click` with `child-screen-click-v1`
details: unique `clickId`, page-local `clientSequence`, pointer type/button,
client monotonic time, page/frame and coordinate-space labels, top-viewport and
course-content pixel positions, 0..1 normalized positions, viewport/content
dimensions, device-pixel ratio/orientation, course/question context and a
bounded target descriptor (`tag`, `id`, `role`, `dataAction`, `targetType`,
`targetKey`, `interactionKind`, `interactive`). The target descriptor never
contains rendered text, input values or a full DOM path. `sessionOffsetMs` is
the Server receipt offset from the continuous recording start when that live
clock is available. Mouse movement, touch movement, drag paths and uncommitted
interactive iframe clicks are not collected.

`session_summary.json.screen_interaction` uses
`screen-interaction-summary-v1`. `tracking_status=NOT_COLLECTED` keeps all
count fields null; `READY` permits a real zero. Ready summaries contain total,
task, blank and other click counts, counts by pointer/page/question, first click
offset/latency and duplicate count. Every `windows/*.json` receives
`analysis_summary.screen_interaction` with the corresponding question counts
and first-click timing. Counts are derived from unique `clickId` rows; the
append-only raw audit remains the fact source.

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

## Demo 屏幕媒体映射

`doll/data/course_map.json` 是儿童屏幕动画与屏幕表情的兼容映射。发布数据允许
`animation`、`emotion`/`expressionMediaId`、表扬事件专用且至少含两个文件名的 `emotions` 随机表情池和 `sequence.audio.offsetMs`；不得写入 `motion`、`motions` 或 `motionOffsetMs`。
`static/resources/Animations/*.mp4` 是儿童反馈资源；`static/resources/Emotions/*.mp4` 和
`doll/data/emotions_meta.json` 是屏幕表情资源与元数据。

`doll/data/motions.json`、`doll/Pose/` 和机械动作资产不属于 Demo 发布 schema。
动画/表情重命名与映射更新必须在同一操作内完成，JSON 写入使用同目录临时
文件、`fsync` 和原子替换。

## Server camera registry

Local camera discovery is candidate-only and does not write configuration.
Discovery results are held in memory for two minutes so explicit confirmation
does not immediately reopen the same Windows DirectShow device. Once a camera
is configured, discovery lists that profile without probing its index again;
the shared preview broker remains the sole owner and its first frame is the
availability proof. This avoids native OpenCV heap corruption caused by
concurrent or rapid open/release cycles.
After explicit operator confirmation, an automatically added camera is stored
in `config/capture_devices.json` with `deviceId=server.camera.<index>`,
`owner=server`, and `selector.index=<operating-system index>`. The first local
camera receives role `primary_environment`; later cameras receive
`environment_secondary`. Removing or disabling the profile removes it from
future preflight checks and monitor preview without changing historical
session manifests.
