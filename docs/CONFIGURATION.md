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
