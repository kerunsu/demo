# M4 Voice Service

Independent local Python voice inference service for M4 development.

## Commands

```powershell
python tools\voice-service\voice_service.py
```

Default provider is `mock`, which returns a deterministic non-sensitive transcript and does not load models.

For local Vosk testing after the model exists in the Git-ignored runtime directory:

```powershell
$env:VOICE_SERVICE_STT_PROVIDER='local-vosk'
$env:VOICE_SERVICE_VOSK_MODEL='.runtime\models\vosk\vosk-model-small-cn-0.22'
python tools\voice-service\voice_service.py
```

For the real local development main flow, enable both local providers:

```powershell
$env:VOICE_SERVICE_STT_PROVIDER='local-vosk'
$env:VOICE_SERVICE_VOSK_MODEL='.runtime\models\vosk\vosk-model-small-cn-0.22'
$env:VOICE_SERVICE_TTS_PROVIDER='local-piper'
$env:VOICE_SERVICE_PIPER_MODEL='.runtime\models\piper\zh_CN-huayan-medium.onnx'
$env:VOICE_SERVICE_PIPER_CONFIG='.runtime\models\piper\zh_CN-huayan-medium.onnx.json'
python tools\voice-service\voice_service.py
```

## Endpoints

- `GET /health`
- `POST /stt`
- `POST /tts`

The service does not persist raw audio or generated speech by default. Requests use transient in-memory audio payloads from the Node orchestration layer.
