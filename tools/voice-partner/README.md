# Voice partner (black-box)

Your zone for **STT + LLM + TTS**. Our app only sends **audio + page text + screenshot** and displays **reply text + reply audio**.

## Quick start

```powershell
copy tools\voice-partner\partner.env.example tools\voice-partner\partner.env
python tools\voice-partner\reference_server.py
```

Our backend (separate repo config):

```env
VOICE_DIALOG_PROVIDER=partner
VOICE_PARTNER_BASE_URL=http://127.0.0.1:9876
VOICE_PARTNER_API_KEY=dev-partner-key
```

## What you edit (1–3 files)

| File | Purpose |
|------|---------|
| `partner.env` | `CONTEXT_INPUT_MODE`, `STT_MODE`, optional `LLM_HTTP_URL` / `TTS_HTTP_URL` |
| `partner_impl.py` | `process_turn(payload)` — or run your own HTTP server |
| `prompts/system.txt` | optional |

Do **not** need to read our frontend. See **[一页交接说明.md](./一页交接说明.md)**（中文一页交接）, [CONTRACT.md](./CONTRACT.md), and [HANDOFF.md](./HANDOFF.md).

## Health

- `GET /health`
- `POST /v1/voice-turn` — see CONTRACT

Header when `PARTNER_API_KEY` is set: `x-voice-partner-key`
