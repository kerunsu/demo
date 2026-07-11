# M7-B Stability, Safety, And Field Acceptance Preparation

This checklist prepares field acceptance. It is not a claim that the real robot, LAN, classroom, microphone, speaker, or camera environment has passed.

## Automated Local Gates

Run before any field rehearsal:

```powershell
npm test
npm run build
git diff --check
powershell -ExecutionPolicy Bypass -File scripts\ops\Test-DemoHealth.ps1 -BackendOrigin http://127.0.0.1:3001
```

## Long-Run Smoke

Use only synthetic or developer-authorized test data. Keep default rule/mock providers unless explicit safety review approves real providers.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\ops\Invoke-LongRunSmoke.ps1 -BackendOrigin http://SERVER_LAN_IP:3001 -DurationMinutes 30 -IntervalSeconds 30 -MaxLogMegabytes 100
```

Acceptance criteria:

- Backend `/api/health` remains reachable for the full run.
- Log directory remains under the configured size bound.
- No backend process or browser tab needs manual restart.
- No raw audio, raw video, raw camera frame, full sensitive transcript, API key, or model artifact appears in Git status, logs, screenshots, or reports.

## Recovery Drills

| Drill | Expected Result | Status |
| -- | -- | -- |
| Backend restart | `/child` can query session state after backend restart or records explicit unavailable state. | `ENVIRONMENT_PENDING` |
| Robot screen refresh | `/robot` restores session snapshot and does not duplicate playback or ACKs. | `ENVIRONMENT_PENDING` |
| WebSocket disconnect | Reconnect restores missing events or snapshot. | `ENVIRONMENT_PENDING` |
| Microphone denied | UI degrades to manual or fixed prompt path. | `ENVIRONMENT_PENDING` |
| Camera denied | Data quality marks missing device without negative child behavior. | `ENVIRONMENT_PENDING` |
| TTS unavailable | Reviewed text remains displayable and no unreviewed audio is played. | `ENVIRONMENT_PENDING` |
| LLM/safety provider unavailable | Fixed safe fallback is used and audit metadata contains reason codes only. | `ENVIRONMENT_PENDING` |

## Multi-Session Checks

- Run at least three sequential sessions on the same backend process.
- Run two browser clients connected to the same session and verify idempotent event handling.
- Verify reports retain separate session ids and do not merge child raw text.
- Verify voice metrics are bounded and deduplicated per session.

## Privacy And Retention

- Real API keys must be host environment variables only.
- Raw audio, raw video, raw frames, child identifiers, and full sensitive transcripts must not be committed or pasted into tickets.
- Runtime logs and diagnostics must be reviewed before sharing.
- `Clear-DemoRuntimeData.ps1` requires confirmation and refuses paths outside the project root.
- Retention target for local runtime logs and backups is `DEMO_RETENTION_DAYS=30` unless the project owner sets a stricter value.

## License And Human Review

| Item | Required Before Production | Status |
| -- | -- | -- |
| Piper model license | Review source, redistribution terms, and deployment constraints. | `ENVIRONMENT_PENDING` |
| Piper voice quality | Human Mandarin listening review for intelligibility and child-facing tone. | `ENVIRONMENT_PENDING` |
| Vosk/local STT model license | Review model license and redistribution terms. | `ENVIRONMENT_PENDING` |
| Cloud STT/TTS/LLM data flow | Privacy and child-data authorization review. | `CREDENTIALS_PENDING` |
| Safety review policy | Product owner approval for child-facing fallback and escalation text. | `OWNER_REQUIRED` |

## Release Checklist

- `npm test` passes.
- `npm run build` passes.
- `git diff --check` passes.
- Deployment templates are copied outside Git-tracked paths before inserting host-specific secrets.
- Backend health endpoint is reachable from robot terminal.
- `/child` and `/robot` open on target displays.
- WebSocket reconnect and duplicate ACK behavior are verified.
- Backup is created with `Backup-DemoRuntime.ps1`.
- Rollback steps from `docs/DEPLOYMENT_OPERATIONS_M7.md` are rehearsed.
- Field acceptance record includes operator, environment, provider mode, evidence, and blockers.

## Stop Conditions

- A task requires real child data without authorization.
- A task would send child raw audio/video/frame data to an external service.
- A real secret would need to be written into Git, logs, screenshots, or docs.
- A model output would be displayed or played before safety review.
- A report would claim diagnosis, norm, percentile rank, clinical conclusion, or professional interpretation without approved rules.
