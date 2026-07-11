# M4-013 Voice Test Fixtures

This directory defines fixture descriptors for automated voice-chain tests.

- Do not commit raw microphone recordings, generated audio, model caches, `.runtime`, or real API keys here.
- Fixture descriptors may represent synthetic audio, developer-authorized test speech, authorized non-child samples, silence, noise, and mock network/playback conditions.
- Cloud STT/TTS tests must remain disabled unless credentials are supplied through environment variables and the specific benchmark command enables them.
- Real child voice is not allowed in development fixtures.
