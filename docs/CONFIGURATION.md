# Configuration and content management

Configuration precedence is: explicit request/session value, persisted YAML or
JSON profile, environment variable, then existing product default. Do not
change a default as a performance or migration shortcut.

`BEHAVIOR_START_LEAD_MS` keeps the default shared multimodal staging window
(700ms by default). Correct-answer praise uses the same synchronized anchor with
the shorter `BEHAVIOR_FEEDBACK_START_LEAD_MS` window (400ms by default), because
expression assets are already warm and measured classroom LAN/server latency
leaves sufficient commit margin. `BEHAVIOR_COMMIT_MIN_LEAD_MS` remains the hard
lower bound.

## Devices

`/api/v2/capture/devices` stores 0..N server/Runtime camera and microphone
profiles with stable `deviceId` and `trackId`, `role`, `enabled`, `required`,
owner/runtime and format/capabilities. Editing the registry affects the next
session; a frozen snapshot is not changed in place. Zero environment devices is
valid when the DeploymentProfile does not require them. The current release
has registry/discovery/configuration and fake preflight ports; physical
per-device check/open/first-sample integration remains a Stage 5 blocker.

## Assets and interaction

Actions and GIF emotions are staged, validated, previewed and committed with
logical `assetId/version` separated from physical filenames. Batch import
accepts individual files or bounded ZIP archives and reports each item plus
conflict policy (`skip`, `rename`, `overwrite`).

The state machine returns to its configured idle motion after a foreground
behavior finishes. That return uses the idle motion's normal per-motion
`speedMultiplier`, so it is tuned in the Action Library instead of by adding a
second state-machine delay. The repository default `空动作` uses `0.5` for a
gentler return; changing that one action updates local, child-agent and Robot
Runtime playback consistently. Idle transition replacement is non-blocking:
the next formal action cancels the previous worker cooperatively and starts at
once instead of waiting for a thread join.

InteractionProfileV2 is keyed by course, then event/scene/line context. A
binding may describe motions, expressions, fixed audio/TTS speech and timing.
Deployment stages are `legacy_only`, `shadow`, `draft_preview`,
`published_canary`, `published`; runtime selection remains legacy unless a
valid published profile is explicitly eligible. Invalid/unmatched V2 always
falls back to the old MappingResolver/course_map path.

## Realtime course phrases

Course prompts, hints, praise and social utterances are realtime browser TTS.
The reviewed base corpus is `config/dialogue_phrases.yaml`. Server-side choices
and locally added phrases are stored separately in
`config/dialogue_phrase_selection.yaml`, using atomic replacement. This overlay
contains `custom` candidate lines and the per-intent/per-course `enabled` set;
when a slot has no explicit selection, all reviewed base lines remain enabled.

Use Configuration Center -> Interaction Content -> Realtime Phrases to select
one or more lines for each course type. Adding a line stores it locally and
enables it immediately. A slot cannot be saved empty. Ordering keeps its eight
rule-specific question slots in addition to general hint and praise. Legacy
course/item audio paths remain readable for database compatibility but are no
longer editable in the course page and are not runtime inputs.

Server Configuration Center -> Overview also owns `browser_speech_rate` in
`config/runtime_modes.yaml`. The range is `0.5..2.0`, default `0.88`, and a
missing field in an older file preserves that default. Saving is same-directory
temporary write + `fsync` + atomic replace. `BROWSER_SPEECH_RATE` is an
environment fallback only; the persisted runtime value wins after restart.

Phrase selection is keyed by course type, not by an individual course row.
Creating a course under an existing type therefore makes it use that type's
enabled phrases immediately; the Realtime Phrases page queries and displays the
currently linked course rows on every refresh. Device and recording operations
are a top-level Configuration Center area at `/server/config/devices`, not an
Interaction Content subview.

## Course answer pronunciation tolerance

`config/onomatopoeia_aliases.yaml` remains the reviewed answer vocabulary for
naming and onomatopoeia courses. Its existing `aliases` mapping adds accepted
animal sounds. The additive `phonetic_groups` list groups characters that the
browser recognizer commonly confuses because they are homophones or close in
pronunciation; the first character is only the internal matching representative.
For example, 狗/沟 and 汪/旺 share a group, so the displayed and persisted
transcript remains unchanged while the correct course keyword is accepted.

An absent or empty `phonetic_groups` section preserves the former exact-text
matching behavior. Keep groups narrow and reviewable: adding an unrelated
character makes every keyword containing that group equivalent during course
answer matching. The file is already included by the recursive `config/`
configuration sync/export.

## Teacher course presets

`config/demo_course_scope.json` is the deployment-level curriculum boundary.
Schema v1 stores ordered `enabledCourseTypes`; this demo deployment fixes the
list to `mimic`, `pairing` and `ordering`. The Server applies it to production course
selection, Configuration Center course/preset catalogs, phrase-course lists,
configuration-sync course exports and new report scoring/projection. Missing or
invalid scope data fails closed to the same three types. It does not delete the
other course rows, assets or historical reports from SQLite/storage.

## Mimic pose recognition

`config/analyzers.yaml` keeps the pose analyzer and matcher in `real` mode and
loads `models/pose_landmarker_lite.task`. The matcher defaults are a `0.72`
action-joint score threshold, minimum landmark visibility `0.35`, distance
scale `action_sigma=0.55`, mirrored matching enabled, at least four successful
frames held for `0.6s`, and a maximum `0.55s` gap between contributing frames.
These settings are reviewed as one unit: lowering the score or hold time raises
false positives; increasing either makes young children's approximate actions
harder to accept. Missing model/target pose is an unavailable recognizer and
must never be converted into an automatic correct answer. The deployment-root
model file is supplied to MediaPipe as bytes so a Windows drive-letter path
cannot be reinterpreted relative to the Python package directory.

Course presets are managed in Configuration Center -> Interaction Content ->
Course Presets and stored in `config/course_presets.json` with
`schemaVersion: 1`. Each preset has an immutable `id`, display `name`, optional
`description`, and an ordered, duplicate-free `courseIds` list. The document
has exactly one `defaultPresetId` whenever at least one preset exists. Creating
the first preset makes it the default; deleting the default promotes the first
remaining preset.

The Server rejects a save when a selected course is missing or has no course
items. A later course deletion or removal of all its items does not rewrite the
preset silently: `GET /api/config/course-presets` reports `missingCourseIds`,
`emptyCourseIds`, and `available: false`, and the teacher dropdown disables that
preset until an operator repairs it. Writes use same-directory `fsync` and
atomic replacement. The configuration sync package already includes this file
through its recursive `config/` collection.

## Collaboration sync

The configuration center exposes `GET /api/v2/config/sync/manifest` and
`GET /api/v2/config/sync/export`. The manifest covers repository configuration,
robot motion data and presets, `course_map.json`, InteractionProfile files,
emotion assets, and all `static/resources` course media. The export is a
reviewable ZIP that can be unpacked and committed to Git. It also contains a
JSON course catalog export so course changes stored in SQLite are reviewable.

The sync package intentionally excludes `database/app.db`, recordings, report
results, temporary files and `doll/data/students.json`. Never replace a target
database from Git; apply the course catalog through an explicit migration or
the existing idempotent course import scripts.

The Git source of truth for robot content is `doll/data/motions.json`,
`doll/data/course_map.json`, `doll/data/emotions_meta.json`,
`static/resources/Emotions/`, and `static/resources/Animations/`. The last
directory is the default encouragement animation library. A `praise` binding
may set `animation` to an MP4 filename; an empty value means random selection
from that library. These paths are intentionally not ignored, so review and
commit their changes together. The old `config/praise_videos.yaml` and
`static/resources/videos/praise/` path are no longer runtime inputs.
