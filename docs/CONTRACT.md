# Contract — HTTP, Socket and Runtime

机器可读的 route/event 快照和所有权矩阵保留在 `tests/fixtures/contracts/`，只供测试和审计使用；它们不是开发计划。快照发生变化时，必须同时补 fixture、变更说明和兼容性决定。

## Compatibility

- Existing URLs, methods, status codes, response envelopes, event names,
  rooms, ack order, request IDs and camelCase/snake_case aliases remain valid.
- New V2 endpoints are additive. They use a `success` envelope but do not
  normalize legacy errors.
- The legacy session files remain `video.avi`, `audio.wav`,
  `video.environment.avi`, `audio.environment.wav`, `timeline.csv`,
  `session_meta.json` and `archive_meta.json`.
- New sessions add `dialogue_timeline.txt` on the first visible child dialogue
  message. Child and Maimai bubbles are stored in server order with request IDs
  and a `server.session.monotonic` offset aligned to the session recording; this
  additive text file does not replace either interaction audit timeline.
- New continuous sessions use the same `姓名-年龄-YYYYMMDD-N` directory name
  under both `recordings/sessions/` and `recordings/behavior/`. UUIDs remain
  correlation fields inside the files. Historical UUID-named behavior folders
  remain readable; they are not renamed automatically.
- Directory reservation and read-only lookup do not create folders. The first
  actual metadata, timeline, behavior or media write owns directory creation,
  so cancelled/failed preflight leaves no empty per-session directory.
- `sessionId`, `trainingSessionId`, `behaviorId`, `requestId`, `lineId` and
  `profileVersion` are correlation fields; a server-side frozen profile version
  wins over a later client value during the same session.

## Main flows

`login -> student/course selection -> prepare_training -> readiness ->
play_resource -> aux/analysis/dialogue -> teacher rating -> finalize -> report`
is one media session. `cancel_prepare_training`, retry, duplicate requests,
busy rejection, disconnect/reconnect, Runtime late upload and missing optional
devices are separate branches in the characterization suite.

Report review notifications are transition-based and idempotent. Finalization
may create one `pending_review` draft and emit one `report_ready_for_review`;
status polling only reads `/review-status` and must not regenerate that draft.
Repeating `generate` for the same pending draft emits no second notification,
and repeating it after `report_published` preserves `published`. The Server
console also ignores a duplicate ready event for a dismissed, already-open or
just-published training session.

The persisted report remains an audit-capable snapshot, but the teacher report
is a product projection rather than a raw JSON viewer. It never renders
correlation IDs, `formulaVersion`, internal status/error codes or database
field names. `courseEvaluations[]` covers every course type enabled by the
deployment scope with
`evaluated`, `insufficient_data` or `not_evaluated`; the latter two display as
“数据不足” or “未评估” and are never plotted as zero. Evaluated course cards
compare `score` with the configured `targetScore`. Recommendations expose
priority, evidence, practice, reason and progress check, and may not claim an
age norm, percentile or standardized diagnosis that the dataset does not own.
The former five-axis radar presentation is not part of the teacher projection.
The enabled course ability dimensions are shown as a percentage bar chart with a visible
training-target marker, the current percentage and the remaining percentage-
point gap. Missing dimensions remain labelled “未评估” or “数据不足” and do
not render a zero-length result bar. `narrative.headline` and
`narrative.overview` additively provide the teacher-facing performance title
and the fixed four-part reading order: overall result, relatively stable
performance, point needing attention and evidence boundary. Historical
published reports without these fields remain readable through the teacher
client's compatibility projection. The Server review editor must preserve
structured recommendation fields when an unchanged recommendation is saved;
an edited legacy body is displayed once and is never repeated into several
recommendation sections.

The deployed topology is a single active Server, teacher controller, child
page and Robot Runtime. Starting a new training is an atomic workflow takeover:
the Server serializes prepare, closes every older active media session,
finalizes older behavior trainings and replaces the same teacher's old control
lease. A stale tab remains read-only and cannot mutate the replacement session.
Duplicate requests with the same logical prepare identity remain idempotent.

An empty `aux` on `play_resource` resolves to the `silent` course-entry
lifecycle event. Every course type, including social greeting/farewell items,
must accept this event so content loading cannot be rejected before the first
real behavior. Social greeting and farewell action slots remain mutually
exclusive; accepting `silent` does not make either social action available to
ordinary naming, pairing or ordering courses.

`attention`（教师端“吸引”）和 `reward`（教师端“夸奖”）是所有课程都可用的
全局注意力状态。它们继续使用 `defaults -> course -> item` 三级行为解析，但
不会计分、推进课点或打开教师评分框。实时话术由虚拟的 `global` 话术组管理。
教师端只允许给 `reward` 传递经 Server 校验的 `behaviorAnimationOverride`，并按
儿童在本机记住选择；`course_map.json` 仍是共享三级事实源，不恢复学生覆盖层。

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
虚拟的“全局注意力互动”组单独提供可选择、可新增的 `attention` 和 `reward`
话术槽。

`GET|PUT /api/server/runtime-modes` additively exposes
`browserSpeechRate` (`0.5..2.0`, default `0.88`). The same persisted value is
attached to every `robot_speak_text` path: course questions, naming,
onomatopoeia, dialogue replies, attention, hints and praise/reward. A successful
update atomically replaces `config/runtime_modes.yaml`, updates the current
process and emits `browser_speech_rate_updated`; the child applies it to the
next utterance without restarting or interrupting the current utterance.

Demo 机课程范围的共享事实源是 `config/demo_course_scope.json`（schema v1）。
当前启用课型为 `mimic`、`pairing` 和 `ordering`；SQLite 中其他历史课程、课程资源与
历史报告不删除，但生产 `/courses`、配置中心课程目录、课程预设、配置同步导出的课程目录清单和
新生成报告都只投影这三个课型。范围文件缺失或非法时也安全回退到这三个课型，
不能因配置损坏重新暴露其他课程。

教师端课程预设的共享事实源是 `config/course_presets.json`（schema v1），
不再在教师前端硬编码课程组合。配置中心通过
`GET/POST /api/config/course-presets`、
`PUT/DELETE /api/config/course-presets/<presetId>` 管理有序的 `courseIds`、名称、
说明和唯一的 `defaultPresetId`。写入时课程必须存在且至少包含一个课点；读取时
若课程后来被删除或清空，预设返回 `available=false`，教师端不得应用。接口始终
返回当前课程目录，因此预设只保存课程身份与顺序，不复制会过期的课点列表。
评估选课页自动应用可用的默认预设；评估和干预选课页都提供预设下拉框，选中后
按预设顺序使用每门课程当前的全部课点。Demo 默认预设固定包含模仿、配对和排序，
三门课程均以整课复选框直接选择，不展开重复的逐课点图片；切换到任一课程分类后也
保持这一紧凑布局。复选框仍展开为该课程全部真实课点交给 readiness 和课程执行。
逐课点手动增删会退出“预设已应用”状态，整课复选框调整则保留快速方案布局，
但不会修改 Server 端预设。
The Server configuration console exposes device and recording operations as a
top-level page at `GET /server/config/devices`; the historical
`/server/config/content?view=phase5` browser URL redirects there.

During an active ordering question, `sequencing_set_config` stages the complete
teacher configuration without changing the category, rule, or scoring context
of the question already on screen. The child applies the staged configuration
before generating the next question and reloads the selected category's image
set when the category changes. The Server remains a session-room relay for this
event and does not persist the staged configuration. The child's
`sequencing_question_ready` payload is the fact source for the visible
question; a teacher re-ask uses that active category and rule rather than the
staged next-question configuration. In the deployed child page, the authorized
top-level child Socket receives interactive control events and relays them to
the committed iframe with `postMessage`; embedded matching/ordering iframes do
not claim the session's single child-owner lease with a second Socket. A
preloading iframe may cache its page context and `*_question_ready` envelope,
but only the top-level child may publish them after the iframe becomes the
committed visible resource. A discarded staging iframe therefore cannot start
speech or overwrite the live dialogue context.

During an active pairing question, `matching_set_difficulty` stages the
teacher-selected option count (`2..5`) without changing the cards already on
screen. The child applies that count before generating the next question; an
explicit teacher selection takes precedence over automatic and simplified
difficulty state. The Server only validates control access and relays the event.

Pairing and ordering use the Server-side training mode saved by
`prepare_training`; a stale teacher cache cannot override it in a later
`play_resource` payload:
`assessment` treats the first selection as the final result for that question;
`training` is intervention mode, where a wrong selection keeps the same target,
changes option positions after the feedback speech, and repeats until correct or
the teacher emits `matching_next` / `sequencing_next`. These events mean “next
question inside the current interactive course”; the teacher's “下一个” still
means “next course item”. While one teacher “下一题” request is waiting for the
new visible question, additional clicks are ignored; a six-second watchdog
restores the control without issuing another advance. Skipping an unresolved
question records it as not independently completed and never double-counts an
intervention attempt that was already wrong. A new question starts in
prompt-only state. The pairing target or ordering rule first moves to the
viewport centre at an emphasized scale; after correlated question speech ends
it returns to normal layout, then the options appear. Options remain
non-interactive and hidden until the correlated
`robot_speak_ended(intent=question, questionId=...)` event. A stale terminal
event from the previous ordering/pairing question cannot unlock the new one;
an eight-second failure watchdog prevents a missing TTS callback from blocking
the course indefinitely. Praise/encourage feedback uses a six-second terminal
watchdog for the same reason.

Pairing and ordering cards are fixed-size horizontal items. More options extend
the scroll surface and never shrink an existing card. The whole white rounded
card owns clipping, shadow, hint, dim, wrong, correct and flip feedback so an
image corner cannot escape during transforms. Both courses use the same
warm-yellow to white vertical background; prompt/answer/scoring/next-question behavior is
unchanged. Hinting scrolls the correct pairing card into view when needed.

After an accepted praise request for a non-interactive course, the teacher
rating dialog opens within one second of the original request and does not wait
for robot speech, motion, expression, or child animation to finish. Those
outputs continue atomically; if the rating is submitted early, the next course
resource remains queued until the active praise behavior ends.

Teacher-initiated praise in pairing and ordering courses uses the same speech,
expression, motion, and child animation package as other courses, but its
post-animation workflow is different. The accepted `play_resource_ack` and the
child-facing `play_resource` carry `teacherRatingRequired=false`,
`returnToCurrentQuestion=true`, and `holdLastFrame=false`. When the animation
ends, the overlay is removed and the already committed interactive question is
shown again with the same `questionId`; no teacher rating dialog opens and
neither the question nor the course item advances. Automatic per-question
praise in these courses follows the same no-rating/return-to-question rule.

The optional spoken wake phrase accepts the sentence-initial two-syllable
“麦麦” form and reviewed browser-ASR homophones/near sounds such as “买卖”,
“卖卖”, “妹妹” and “慢慢”. The former four-syllable forms remain compatible.
The two-syllable `ma` family is intentionally excluded so the common word
“妈妈” does not wake the agent. Text before the wake-like pair never matches.

After a wake acknowledgement TTS ends, child dialogue capture keeps a bounded
pre-roll through the short output cooldown so an answer that starts immediately
after “我在这里” is not discarded. An armed course keyword is evaluated before
the general dialogue LLM whether the session is asleep or awake. A hit emits
`keyword_auto_praise` into the existing teacher praise, rating and next-item
flow; it does not create a separate dialogue-only progression path.
After question or hint speech ends the keyword window is armed again. While this
curriculum answer window is active and the dialogue agent is still asleep, a
non-matching transcript is surfaced as a course-answer miss and must not fall
through to general dialogue. Once the agent is awake, only a true keyword hit
intercepts the turn; a miss falls through to the dialogue reply. This prevents
ordinary conversation from being silently consumed by an armed naming or
onomatopoeia question. An explicit wake phrase remains higher priority and its
remainder follows the same rule. Keyword matching first uses normalized text,
then the additive `phonetic_groups` in `config/onomatopoeia_aliases.yaml`, so
reviewed homophones such as 狗/沟 and 汪/旺 are accepted without treating
unrelated words as correct. The dialogue prompt treats onomatopoeia as vocal
imitation: it models a short sound and invites the child to say it, and must not
ask the child to click, point at or choose a picture. The production child page uses browser
`SpeechRecognition` as its only
speech-to-text provider and sends final text through `child_dialogue_text`.
Browser-originated payloads add
`recognitionProvider=browser-speech-recognition`; typed diagnostic input omits
the field.
It does not capture/upload WAV for dialogue, probe `/api/v2/voice/health`, start
the local FunASR service, or feed Server microphone chunks into a local ASR
analyzer. `config/analyzers.yaml` pins both speech analyzer and matcher to
`enabled=false`, and the configuration console exposes those legacy parameters
as read-only. During browser TTS, recognized text is held until speech ends and is
dropped when it matches the loudspeaker reference. The legacy
`child_dialogue_audio` event remains registered for one compatibility release
but returns `browser_speech_required` without invoking a local model.

For `mimic` (including legacy `imitation`/`pose`) the Server extracts 33 pose
landmarks from the current target card and each authorized child-camera frame
with the packaged MediaPipe Pose Landmarker. Matching uses visible action
joints rather than an equal average over facial landmarks, is scale/translation
invariant, accepts the horizontal mirror of an action and requires both the
configured score threshold and a continuous multi-frame hold. Question, hint
and praise speech reset and gate the hold, so merely passing through a pose
during the prompt cannot score. A stable hit records one `child_response` with
`modality=pose` and invokes the same atomic expression, motion, child animation,
praise TTS and teacher-rating package as a naming/onomatopoeia keyword hit. The
existing `keyword_auto_praise` teacher event is retained for compatibility and
carries `source=pose_match`; it is emitted only to the exact teacher room and is
deduplicated by the current training/question/item identity.

`teacher_dialogue_wake`, `teacher_dialogue_sleep` and
`teacher_dialogue_visibility` are in-classroom session commands, not teacher-lease
mutations. They do not require a login cookie or controller lease. The Server
resolves the supplied runtime `sessionId`, requires an active course and its
current `trainingSessionId`, rejects a mismatched training ID, and requires the
exact child owner for that session before emitting only to
`session_<sessionId>_child`. The ACK echoes `requestId`; the teacher releases
its busy state on ACK, disconnect or a four-second local watchdog. The wake
button changes to a close button while awake. The child immediately attempts
to start or resume browser recognition and reports listening/microphone state
back to the exact teacher room. The committed child question ID is included in
every transcript context, so a teacher wake and the following child turn share
the same identity; one completed utterance does not exit wake. Late target/option
enrichment within the same course/question identity cannot clear wake state.
Manual wake/close and panel
visibility do not play sound, interrupt content, stop recording or affect
another room.

Every completed robot behavior waits for the configurable `IDLE_POSE_DELAY`
before starting the mapped idle motion (`空动作`). Its default is `0.6s`, which
briefly holds the final pose so pairing/ordering praise returns as naturally as
other courses. The timer is cancelled immediately by a new behavior, so the
buffer never blocks the teacher's next command and applies identically to
Server OSC, child relay and Robot Runtime control modes.

## Versioned additive APIs

- `/api/v2/capture/devices` — configure/discover 0..N device profiles and freeze
  a snapshot. `GET /api/v2/capture/devices/candidates` probes Server cameras
  without changing configuration; it never reopens an index already owned by
  the configured preview broker. `POST` to that path explicitly persists one
  candidate from the latest two-minute discovery result; an absent/expired
  result returns `camera_discovery_required` instead of probing the hardware a
  second time. Only enabled, configured Server cameras are exposed as 0..N
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
- `GET /api/v2/voice/health` — legacy, read-only voice-service diagnostics for
  operators. The production child page does not call it and Server startup does
  not launch the voice-service.
- `GET /api/v2/timeline/latency/sessions` lists training sessions available to
  the read-only latency dashboard. `GET /api/v2/timeline/<trainingSessionId>/latency`
  correlates teacher, Server and endpoint milestones into
  `interaction-latency-report-v1`; `?mediaSessionId=<id>` is required by the
  Server console to isolate a retry that reused the same training ID, and
  `?format=markdown` exports the same filtered report. Reports additively expose
  `dataQuality`, lower-screen `endpointStages`, motion measurement quality and
  natural-dialogue stage summaries.
  The existing raw timeline CSV remains available from
  `GET /api/v2/timeline/<trainingSessionId>?format=csv&mediaSessionId=<id>`.
- `POST /api/v2/timeline/events` accepts the additive, server-owned child-screen
  events `child_screen_tracking_started` and `child_screen_click`. A click is
  exactly one trusted primary `pointerdown` (left mouse, touch or pen); the
  browser must not also count the synthetic `click`. The Server fixes
  `actor=child`, `source=child_ui`, `category=child_interaction` and
  `modality=screen`, validates bounded pixel/normalized coordinates and adds a
  recording-relative `details.sessionOffsetMs` when the live media session is
  available. `clickId` is the deduplication key. Target text, input values,
  full DOM paths, pointer movement and drag trajectories are never persisted.
  Same-origin interactive iframes are captured only after their committed
  `#interactive` frame is visible; staging/retiring frames cannot contribute.
- Child dialogue capture assigns one `requestId` to the whole turn. The Server
  accepts additive `dialogue_latency_event` milestones for result receipt and
  browser TTS receipt/start/end; they are audit-only and cannot drive course
  progression or robot behavior.
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
  scaled `time` and `moveMs` values. Returning from a foreground behavior uses
  the configured idle motion through this same path; `空动作` defaults to `0.5`
  so the neutral return is slower without delaying behavior completion. A new
  foreground request signals the old idle/transition worker and starts
  immediately; local OSC and Runtime transition replacement never synchronously
  join the prior worker, so a smooth return cannot block the next teacher action.
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
- `GET /api/robot/runtime/version` advertises a release only after the Server
  verifies the selected ZIP size, SHA-256 and embedded `VERSION` against
  `releases/robot/manifest.json`. A missing versioned file may use the `latest`
  alias only when the alias contains those exact declared bytes; an unrelated
  old package is never exposed with new metadata. Additive `update*` fields
  describe the lightweight Runtime hot-update archive. The existing
  `GET /api/robot/runtime/download` remains the full first-install package;
  `?kind=update` selects the lightweight archive and both variants support HTTP
  range requests. Robot Runtime `/update/apply` runs asynchronously and
  `/update/status` reports download, verification, extraction, swap, restart or
  failure stages; `/update/log` exposes only the local machine's bounded update
  log through the local-only operations UI.
- The robot `/child` page posts a local-only heartbeat to Robot Runtime. Runtime
  health exposes `childPage.online`; packaged startup and online-update restart
  restore the page and only report readiness after this browser heartbeat. A
  successful PowerShell process launch alone is not child-page readiness.

For `praise`, `reward`, and optionally `attention`, `course_map.json` may carry
an `animation` filename next
to `motions`, `emotion`, and `sequence`. The server sends the resolved static
path as `behaviorAnimation`; the child reports completion through
`behavior_animation_ended`. Automatic pairing/ordering praise and teacher
praise use the same preparation event, start anchor and completion barrier.
When praise/reward animation is empty, the server chooses a random MP4 that
passes bounded inspection; invalid placeholders remain visible for repair but
never enter the random pool. Empty attention animation means no overlay. For one compatibility
release, `praiseVideo` and `praise_video_ended` remain aliases only; they no
longer select assets or contain a separate playback implementation.

Robot Runtime `POST /devices/check` proves first samples. Its additive
`record/start.captureDevices[]` freezes Runtime-owned environment tracks; a
required open failure rejects the start before the common runtime start time.
At stop, `trackManifest` and `track__<trackId>` multipart parts extend the
existing media upload without changing the legacy `video`/`audio` parts. The
Runtime also sends the validated `humanDirName`; after a Server restart this
restores the readable session binding before a late archive is written. A name
already owned by another media session is rejected rather than overwritten.

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
