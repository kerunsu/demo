# Device and track acceptance report

## Proven in automation

- Registry supports stable `deviceId`/`trackId`, zero-to-many profiles, update,
  delete, discovery adapter and frozen snapshots.
- Duplicate track IDs, invalid booleans, persistence failure rollback and
  legacy primary filename mapping are protected by tests.
- Session quality inspection is read-only and reports file size/hash (opt-in),
  manifest fields, timeline validity, drop counters/offsets when present,
  storage free space and degradation reasons.
- The existing Jinja configuration center has an additive “设备与交付” panel
  that calls only the versioned facade APIs for device registry/freeze, quality,
  batch import and V2 resolution preview.

## Not yet accepted in production

The registry currently stores configuration. It does not open or check every
physical camera/microphone, reserve each device, write each dynamic track from
the active capture lifecycle, or verify first frame/first audio block before
formal recording. The old ambient camera is still a single-instance service;
there is no equivalent multi-instance environment microphone service.

Required next implementation: a real Server/Runtime `DeviceBroker`, wired into
strict readiness and the single composition root, with per-device health,
reserve/open/close, first-sample evidence and rollback. Keep optional devices
skippable only when the DeploymentProfile says optional/disabled.

## Filename invariants

`video.avi`, `audio.wav`, `video.environment.avi` and
`audio.environment.wav` remain compatibility tracks. Additional tracks use a
safe stable track ID and are described in `session_meta.json`; MP4 cannot
replace AVI/WAV.
