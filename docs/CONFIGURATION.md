# Configuration and content management

Configuration precedence is: explicit request/session value, persisted YAML or
JSON profile, environment variable, then existing product default. Do not
change a default as a performance or migration shortcut.

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

Phrase selection is keyed by course type, not by an individual course row.
Creating a course under an existing type therefore makes it use that type's
enabled phrases immediately; the Realtime Phrases page queries and displays the
currently linked course rows on every refresh. Device and recording operations
are a top-level Configuration Center area at `/server/config/devices`, not an
Interaction Content subview.

## LLM reply expressions

Configuration Center -> Interaction Content -> Behavior Binding includes a
separate length-based expression matcher for generated dialogue replies. Its
source of truth is `doll/data/emotions_meta.json` under
`dialogueReplyExpressions`; it does not alter or override course bindings in
`course_map.json`. Rules contain strictly increasing `maxChars` values and MP4
emotion filenames. Whitespace is excluded from the runtime character count,
the first matching upper bound wins, and replies longer than the final bound use
the final rule. The feature is disabled when omitted, preserving deployments
that do not configure it.

`GET|PUT /api/robot/emotions/dialogue-reply-rules` reads or atomically replaces
the matcher. Enabling requires at least one valid rule; GIF, missing files,
duplicate/decreasing bounds, and more than twelve rules are rejected. Referenced
expressions participate in deletion protection.

## Continuous speech recognition

`config/analyzers.yaml` keeps the continuous course-ASR gate under
`analyzers.speech`. The gate evaluates the unnormalized 16 kHz PCM before
Paraformer and requires both whole-window energy and a minimum share of voiced
20 ms frames. Defaults are `rms_threshold=0.006`,
`frame_rms_threshold=0.014`, `peak_threshold=0.02`, and
`min_voiced_ratio=0.12`. With the default two-second window this requires about
240 ms of sustained voice-level audio, so a short handling noise does not start
recognition while a short child answer can.

`max_input_gain=3.0` bounds preprocessing gain; accepted low-level audio is no
longer peak-normalized to full scale. After a course question/hint/praise TTS
ends, the analyzer keeps about 180 ms of speaker-tail audio as preroll instead
of wiping the buffer and ignoring 750 ms. Consecutive identical or nested
transcripts inside an 8-second window are dropped so overlapping 2-second ASR
chunks do not reprint one child sentence. Raise the frame/peak thresholds or
voiced ratio when a deployment microphone admits persistent ambient noise.
Lower only the frame threshold when verified child speech is being missed.
Historical configurations remain compatible because missing or invalid fields
use these defaults. Changes apply when the analyzer is recreated or the Server
restarts.

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
