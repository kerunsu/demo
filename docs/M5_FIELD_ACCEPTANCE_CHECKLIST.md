# M5 Field Acceptance Checklist

This checklist prepares real environment validation. It is not a claim that field acceptance has been completed.

## Required Environment

- Robot Windows terminal with child screen and robot screen browsers.
- Independent backend/server host on the same LAN.
- Camera available to the child screen browser.
- Microphone and speaker available for M4 voice chain regression.
- Stable classroom lighting.
- Test area with controlled occlusion and optional multiple-person scenarios.
- Synthetic, adult-authorized, or non-child licensed test material only.

## Safety Preconditions

- No real child video or identity data by default.
- No raw frame upload to external cloud vision services.
- No real API keys in code, logs, screenshots, or Git.
- No raw camera frame persistence unless a separate explicit test protocol is approved.
- Logs must not contain image base64, raw audio, or full sensitive transcript text.

## Execution Steps

1. Start backend and frontend with LAN runtime config.
2. Open `/child` and `/robot` on the robot terminal.
3. Confirm WebSocket recovery from refresh and reconnect.
4. Confirm camera permission prompt and denial path.
5. Confirm no-camera path marks `missing_device`.
6. Confirm low-fps frame descriptor ACKs without raw-frame persistence.
7. Confirm Mock Attention scenarios still drive summaries.
8. If a local vision model is approved, run a minimal non-child fixture smoke test and record latency.
9. Run one full training session with voice chain regression.
10. Generate behavior question and session summaries.
11. Confirm data quality is separate from child performance.
12. Confirm no formal score, norm, percentile, or diagnosis is produced by M5.

## Result Recording

| Item | Status | Evidence | Notes |
| -- | -- | -- | -- |
| Robot camera permission | `ENVIRONMENT_PENDING` |  |  |
| LAN dual-screen recovery | `ENVIRONMENT_PENDING` |  |  |
| Classroom lighting | `ENVIRONMENT_PENDING` |  |  |
| Occlusion | `ENVIRONMENT_PENDING` |  |  |
| Multiple people | `ENVIRONMENT_PENDING` |  |  |
| Long run stability | `ENVIRONMENT_PENDING` |  |  |
| Human annotation comparison | `ENVIRONMENT_PENDING` |  |  |

## Stop Conditions

- Real child data would be required without authorization.
- Raw frames would need to be sent to an external cloud vision service.
- A real API key would need to be written into code or Git.
- Logs or reports expose sensitive raw media or identity data.
