# Extension guide

## New device or track

Add a `DeviceProfile`/`DeviceDiscoveryPort` adapter and fake tests first. Keep
stable IDs, explicit owner/runtime, clock domain and required/optional policy.
Do not choose filenames in acquisition; use the storage layout port. The
primary environment track must retain its compatibility name.

The control console distinguishes `connected` (a real first frame/chunk was
read) from `captureReady` (the recorder can write that source into the frozen
session manifest). Robot Runtime devices advertise `multi-track-media-v1`, are
frozen at strict readiness, open before the shared start time and upload their
manifest/files at stop. Server-owned additional devices remain probe-only
until a Server multi-track recorder is supplied; they must not be promoted to
`captureReady`.

## New expression asset

New expression uploads and batch imports are MP4 only. Event MP4 files must be
authored as one complete non-looping cycle whose final frame joins the idle
asset; the browser uses the native `ended` event and then reveals the looping
idle layer. Existing GIF files remain readable for legacy course bindings but
are deprecated and cannot be uploaded as new assets.

## New model

Implement `AnalysisModel`/`ModelProvider` with descriptor, health, analyze,
close, timeout/cancel and degraded/no-data output. Register it through the
composition root; never import Flask, SocketIO, the dialogue service or a
concrete recorder from computation.

## New interaction/dialogue

Add a catalog event and schema fixture, then bind by
`courseId -> eventKey -> sceneKey -> lineId`. Validate reachability, fallback,
unique line IDs, assets and durations before publish. Use the stable dialogue
request/response/speech-command ports; the facade may continue emitting the
existing `robot_speak_text` event. Preview and shadow must not actuate hardware.

Every extension needs a legacy fallback, a rollback switch, an automated
contract test, a migration-log entry and an update to the traceability matrix.
