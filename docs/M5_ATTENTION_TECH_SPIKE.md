# M5 Attention Technology Spike

## Status

- Current status: `DEVELOPMENT_PROVIDER_READY_WITH_ENVIRONMENT_PENDING`
- Current runnable provider: `mock-attention` plus camera frame descriptor ingress
- External cloud vision calls: none
- Model downloads: none
- Real child video or image data: none
- Raw frame persistence: disabled

## Compared Routes

| Route | Decision | Notes |
| -- | -- | -- |
| Browser lightweight inference | `CAN_DEFER` | Strong privacy, but model distribution and browser CPU still need real robot validation. |
| Browser low-fps frame samples to server | `DEFAULT_FOR_M5` | Implemented as descriptor-first ingress with frame hash, sequence, dimensions, quality metadata, and no raw-frame persistence. |
| Continuous video stream to server | `DEFER` | Higher bandwidth and privacy risk; not needed for M5 v1. |
| Server vision inference service | `SKELETON_READY` | Provider boundary exists through replaceable attention provider; real model remains pending. |

## Current Implementation

- Frontend camera capture owns camera permission, video device enumeration, stop/release, low-fps sampling, downsampling, and descriptor generation.
- Frontend sends only metadata descriptors to `/api/behavior/:sessionId/camera/frames/:frameId`.
- Backend accepts descriptors, tracks sequence gaps, stores no raw frame, and writes attention observations through the repository.
- Mock scenarios cover `face_present`, `no_face`, `multiple_faces`, `looking_away`, `occluded`, `low_confidence`, and `camera_unavailable`.

## Data Safety

- Descriptors include frame hash, byte length, dimensions, timestamp, session/question/correlation IDs, and `rawFramePersisted: false`.
- Descriptors do not include base64 image data.
- Logs and tests do not include raw frames.
- No model cache, virtual environment, downloaded fixture, or media file is committed.

## Environment Pending

- Real robot camera permission flow.
- Real classroom light, occlusion, and multiple-person scenes.
- Real model accuracy and latency.
- Human annotated validation samples.
- Long-running camera stability.

## Recommendation For M5 v1

Continue with browser camera permission and low-fps descriptor/controlled sample boundary, server-side replaceable Attention Provider, and Mock/fixture tests. Upgrade to a true local vision model only after real robot hardware, acceptable latency, privacy policy, and non-child licensed fixtures are available.
