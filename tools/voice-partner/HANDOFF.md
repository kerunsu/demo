# Handoff checklist (partner)

1. Read [CONTRACT.md](./CONTRACT.md) only — no frontend code required.
2. Copy `partner.env.example` → `partner.env`.
3. Implement `POST /v1/voice-turn` **or** edit `partner_impl.py` and run `reference_server.py`.
4. Set `CONTEXT_INPUT_MODE` / `STT_MODE` in `partner.env`.
5. Point our team to your base URL + API key for `VOICE_PARTNER_BASE_URL` / `VOICE_PARTNER_API_KEY`.

We send every turn:

- merged child audio
- page text (`narrative` + structured fields)
- screenshot when capture succeeds

We consume only:

- `replyText`
- `replyAudio` (optional)

We run our own browser STT for assessment; **do not rely on us sending transcript**.
