# Operations, release and rollback

## Health checks

Run `python -m pytest tests -q`, `python -m py_compile app.py`, and
`python scripts/bootstrap.py --check-only`. Build the teacher client with
`npm ci` and `npm run build` in a clean environment. Runtime health is checked
through `/api/server/status`, `/api/robot/runtime/status` and the existing
monitor endpoint.

Normal Windows startup is `./start_server.ps1`. It builds the finite teacher
production bundle and serves it at `http://<server>:8080/teacher/`; it does not
leave a Vite process on 5173. A repeated Server start reuses the one healthy
8080 instance.

In the local configuration console, “设备与录制” calls
`POST /api/v2/control/devices/check`: Runtime and Server probes must each read
a real first video frame/audio chunk. Runtime heartbeat alone is never a green
device check. After a course, `GET /api/v2/control/overview` groups recorded
sessions by child and the local-only reveal action opens only a validated
direct child of the sessions root.

The teacher client selects strict preflight automatically in agent/Robot
Runtime mode. Before each course, confirm all enabled and required devices are
capture-ready in the console; the same frozen device snapshot is then sent to
Runtime for one shared recording start. Browser mode intentionally keeps the
legacy preflight path for compatibility. Server-owned extra devices are
currently probe-only; select Robot Runtime ownership for extra tracks that
must be recorded and uploaded into the session dataset.

## Safe deployment

1. Back up `database/app.db`, `static/recordings`, `static/resources`, config
   files and the Robot Runtime release manifest.
2. Install Python dependencies and run non-destructive checks.
3. Run teacher `npm ci`/build and verify static URLs.
4. Apply database schema compatibility checks; never delete the old DB.
5. Start `app.py`, then register Runtime and verify heartbeats.
6. Run fake-device contract tests, then the browser/Runtime/hardware smoke
checklist in `docs/TESTING.md`.

On the robot, extract `releases/robot/EIArt-Robot-latest.zip` and run
`start.bat`. Repeated clicks on the same build reuse the healthy Runtime. If a
different packaged version owns 19091, the launcher validates that the owning
process is `RobotRuntime`, stops it, restarts the named `DollSer` process so the
current `Settings.xml` is loaded, and waits for `/ready=true`. The current
release configures DollSer as COM3. Never kill an unrelated owner of 19091.

On the first `app.py` start, the voice launcher checks the exact Python used by
voice-service. Missing `torch`, `funasr`, and `modelscope` packages are
installed from `tools/voice-service/requirements.txt`, then the FunASR ASR,
VAD, and punctuation models are downloaded into
`.runtime/models/voice/modelscope/`. The resolved paths are recorded in
`.runtime/models/voice/model_paths.json`; later starts validate and reuse them.
Failures are logged with the pip or downloader error and voice-service is not
started in a false-ready state. Set `VOICE_SERVICE_AUTO_INSTALL=0` or
`VOICE_SERVICE_AUTO_DOWNLOAD=0` only for pre-provisioned/offline deployments.

Rollback is a versioned application/config switch: disable new V2 profiles,
return to `legacy_only`, restore the prior application/release package and
restart. Do not rewrite historical sessions or delete assets. Keep deprecated
shims for at least one release cycle.

The current Robot Runtime package is described by
`releases/robot/manifest.json` and `robot_runtime/VERSION`; its hash and size
must be checked before distribution. The packer publishes the complete
`EIArt-Robot-<version>.zip` for first installation and a smaller
`EIArt-Robot-Update-<version>.zip` for `/ui` hot update, then atomically replaces
the manifest last. The Server refuses a package whose size, SHA-256 or embedded
VERSION differs from the manifest. Never repair a failed release by pointing a
new manifest at an older `latest.zip`.

## Analyzer health

`GET /api/server/diagnostics` reports `pipelineHealth.status`, separate vision
and audio flags, and component failures with `required/stage/error`. Required
failure is `unhealthy` and blocks strict readiness; optional failure is
`degraded`. Install the pinned MediaPipe range from `requirements.txt` and the
real ASR stack, including `torchaudio`, from the optional requirements file.

## Multi-worker coordination

Teacher leases are atomically persisted under
`.runtime/coordination/teacher_leases.json` with a same-host OS file lock. The
robot behavior slot uses `.runtime/coordination/robot_behavior.lock`, preventing
overlap across local WSGI workers. Multi-host deployments still require a
shared backend such as Redis.

On Windows, coordination lock paths are resolved once to absolute paths.
Blocking acquisition retries transient `EINVAL`/open failures, and an unlock
error is contained because closing the descriptor releases the OS lock. A
worker that still cannot acquire the lock returns
`teacher_control_temporarily_unavailable` and must not read or write lease
state without coordination. Raw OS errors such as `[Errno 22]` must never be
shown by the teacher UI.

For a stuck interaction, inspect `/api/robot/runtime/status` first. The
`preferredRuntimeId` should equal the `advertisedUrl` reported by the live child
page. Then correlate `sessionId/requestId/behaviorId` in
`full_interaction_timeline.jsonl`. `another_behavior_prepared` should self-heal
after the prepared-motion TTL or when a new session takes over; repeated
occurrence after an upgrade means the robot is still running an old package.

Uploaded MP4 assets are size-bounded and parsed as ISO-BMFF. Known duration,
resolution and codec values are validated. Older partial-metadata assets remain
readable but return `validationStatus: degraded` with specific warnings.

## Dialogue wake and audit exports

Server Config → Overview controls `dialogue_wake_word_enabled` in
`config/runtime_modes.yaml`. It defaults to `false`; teacher-button wake remains
available while voice wake is disabled. The teacher control page can hide/show
the child dialogue panel without changing recording state.

For a test session, open `full_interaction_timeline.jsonl` directly beside the
recorded media in `static/recordings/sessions/<humanCourseDirectory>/`. The
teacher UI intentionally has no log export controls. Server-side tooling may
request `/api/v2/timeline/<trainingSessionId>?format=csv|jsonl`. Correlate failed or
out-of-order behavior by `requestId` and `behaviorId`, then compare each modality
phase. A missing terminal event is distinguishable from `failed`, `timeout`,
`unverified`, or `degraded` rather than being reported as success.

## Application logs

All process logs are written to `logs/app.log` (UTF-8). Since 2026-08-10 every
module — including socket handlers, recording timeline and robot service —
defaults to appending a shared file handler in `app/utils/logger.py`; the
console prints `INFO` while the file receives `DEBUG`. Previously only the
startup logger reached the file, which made "clicked but nothing happened"
incidents invisible after the fact.

Playback incidents are diagnosed from two complementary views:

- `logs/app.log` — server-side decision trail: `play_resource 收到` (request
  arrived), `play_resource 被拒` (lease/authorize rejection), `play_resource
  行为繁忙拒绝` (behavior busy, with `active_behavior` and `remaining_ms`),
  `表情 ended 回执与命令不匹配，忽略` / `表情完成回传超时` (robot expression
  receipt missing or unmatched), plus Robot Runtime heartbeats.
- `full_interaction_timeline.jsonl` — every `play_resource_ack` (accepted,
  `behavior_busy`, `behavior_start_failed`, idempotent replay, lease rejection)
  is appended with `requestId`/`behaviorId`/`remainingMs` so teacher clicks can
  be matched against question progression end to end.

To capture a live incident without keeping a console window open, start the
backend via `server.ps1` (stdout is inherited by the PowerShell host) or wrap
`python app.py` with output redirection; the file handler keeps working
regardless of how the process was launched.
