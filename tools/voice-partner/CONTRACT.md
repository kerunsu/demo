# Voice partner HTTP contract

## POST /v1/voice-turn

We always send **both** `pageContext.text` and `pageContext.screenshot` (screenshot may be `null` with `screenshotUnavailableReason`). You choose what to use via `CONTEXT_INPUT_MODE` in your `partner.env`.

### Request

| Field | Required | Notes |
|-------|----------|-------|
| `schemaVersion` | yes | `voice-partner-turn-v1` |
| `sessionId` | yes | |
| `turnId` | yes | |
| `correlationId` | yes | |
| `capturedAt` | yes | ISO-8601 |
| `audio.base64` | yes | merged turn audio (e.g. webm) |
| `audio.mimeType` | yes | |
| `audio.durationMs` | yes | |
| `pageContext.text` | yes | structured + `narrative` |
| `pageContext.screenshot` | no | JPEG/PNG or null |
| `history` | yes | last turns, `{ role: user\|assistant, text }` — we do **not** send our browser STT |
| `locale` | yes | e.g. `zh-CN` |

Auth (if configured): header `x-voice-partner-key`

### Success response

```json
{
  "ok": true,
  "replyText": "...",
  "replyAudio": { "base64": "...", "mimeType": "audio/wav" },
  "metadata": { "provider": "...", "latencyMs": 120 }
}
```

`replyAudio` optional; we still show `replyText` if missing.

### Error response

```json
{
  "ok": false,
  "error": { "code": "PARTNER_FAILURE", "message": "..." }
}
```

## GET /health

```json
{ "status": "ok" }
```

## Your config (`partner.env`)

```env
CONTEXT_INPUT_MODE=both    # text | image | both
STT_MODE=audio             # audio | text_only_fallback | none
LLM_HTTP_URL=              # any HTTP you control
TTS_HTTP_URL=
```

## curl example

```bash
curl -s -X POST http://127.0.0.1:9876/v1/voice-turn \
  -H "content-type: application/json" \
  -H "x-voice-partner-key: dev-partner-key" \
  -d @tools/voice-partner/fixtures/minimal-turn.json
```
