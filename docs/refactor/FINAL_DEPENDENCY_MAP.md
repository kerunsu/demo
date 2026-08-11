# Final dependency and ownership map

## Allowed direction

```text
Frontend Web -> Facade -> Acquisition
                       -> Storage
                       -> Computation
                       -> Dialogue
Acquisition / Computation / Dialogue -> contracts ports
Storage -> contracts
```

The facade owns Flask request parsing, auth/validation, use-case calls and
response/Socket presentation. It must not own formulas, media writes, codec
lifecycles, DB queries, model calls or device details.

## Current compatibility owners

| Concern | Current owner | Target port/adapter | Stage 5 state |
|---|---|---|---|
| app startup | `app.py` | composition root | compatible, not fully collapsed |
| Socket orchestration | `app/sockets/events.py`, `handlers.py` | facade use cases | compatibility shim remains |
| browser/agent capture | `app/services/media_service.py`, media routes, Runtime | `CapturePort/CaptureSink` | legacy path active |
| environment camera | `app/monitor/ambient_camera.py` | `DeviceBroker` | single-instance legacy |
| device config | `app/acquisition/device_registry.py` | `DeviceRegistry` | 0..N config/freeze only |
| session files | `app/services/recording_timeline.py`, `app/storage` | recording/layout repositories | names preserved |
| analysis/scoring | `app/services/analysis_service.py`, report/behavior | `AnalysisEngine/DecisionEngine` | adapters/skeletons |
| speech | `app/audio`, `app/dialogue`, voice service | `DialoguePort/SpeechOutput` | legacy + V2 speech bridge |
| interaction | `MappingResolver`, V2 resolver | `InteractionProfileRepository/Resolver` | V2 fallback protected |

## Concurrency ownership

Existing singletons, session manager, behavior mutex, Socket event loop,
recording queues and Runtime registry remain compatibility-owned. New code must
document its lock/lifecycle and make stop/close idempotent. No import may start
a thread or open a device.
