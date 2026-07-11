import base64
import json
import os
import tempfile
import threading
import time
import traceback
import wave
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VOSK_MODEL = REPO_ROOT / ".runtime" / "models" / "vosk" / "vosk-model-small-cn-0.22"
DEFAULT_EXPERT_VOSK_MODEL = REPO_ROOT.parent / "ExpertAnnotator_ASD-main" / "asd_llm_agent" / "models" / "vosk-model-small-cn-0.22"
DEFAULT_PIPER_MODEL = REPO_ROOT / ".runtime" / "models" / "piper" / "zh_CN-huayan-medium.onnx"
DEFAULT_PIPER_CONFIG = REPO_ROOT / ".runtime" / "models" / "piper" / "zh_CN-huayan-medium.onnx.json"
STT_PROVIDER = os.environ.get("VOICE_SERVICE_STT_PROVIDER", "mock").strip().lower()
TTS_PROVIDER = os.environ.get("VOICE_SERVICE_TTS_PROVIDER", "mock").strip().lower()
VOSK_MODEL_PATH = Path(os.environ.get("VOICE_SERVICE_VOSK_MODEL", str(DEFAULT_VOSK_MODEL)))
FUNASR_MODEL = os.environ.get("VOICE_SERVICE_FUNASR_MODEL", "paraformer-zh")
FUNASR_VAD_MODEL = os.environ.get("VOICE_SERVICE_FUNASR_VAD_MODEL", "fsmn-vad")
FUNASR_PUNC_MODEL = os.environ.get("VOICE_SERVICE_FUNASR_PUNC_MODEL", "ct-punc")
FUNASR_FALLBACK_VOSK_MODEL_PATH = Path(os.environ.get("VOICE_SERVICE_FUNASR_FALLBACK_VOSK_MODEL", str(DEFAULT_EXPERT_VOSK_MODEL)))
FUNASR_FALLBACK_VOSK_ENABLED = os.environ.get("VOICE_SERVICE_FUNASR_FALLBACK_VOSK", "disabled").strip().lower() == "enabled"
PIPER_MODEL_PATH = Path(os.environ.get("VOICE_SERVICE_PIPER_MODEL", str(DEFAULT_PIPER_MODEL)))
PIPER_CONFIG_PATH = Path(os.environ.get("VOICE_SERVICE_PIPER_CONFIG", str(DEFAULT_PIPER_CONFIG)))
MAX_AUDIO_BYTES = int(os.environ.get("VOICE_SERVICE_MAX_AUDIO_BYTES", str(5 * 1024 * 1024)))

_vosk_model = None
_vosk_error = None
_funasr_model = None
_funasr_error = None
_funasr_fallback_vosk_model = None
_funasr_fallback_vosk_error = None
_piper_voice = None
_piper_error = None
_vosk_lock = threading.Lock()
_funasr_lock = threading.Lock()
_funasr_fallback_vosk_lock = threading.Lock()
_piper_lock = threading.Lock()
_funasr_infer_lock = threading.Lock()


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def json_response(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json; charset=utf-8")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def load_vosk_model():
    global _vosk_model, _vosk_error
    if _vosk_model is not None or _vosk_error is not None:
        return _vosk_model
    with _vosk_lock:
        if _vosk_model is not None or _vosk_error is not None:
            return _vosk_model
        try:
            from vosk import Model

            _vosk_model = Model(str(VOSK_MODEL_PATH))
        except Exception as exc:  # noqa: BLE001 - service health should report provider load failures.
            _vosk_error = str(exc)
    return _vosk_model


def load_funasr_model():
    global _funasr_model, _funasr_error
    if _funasr_model is not None or _funasr_error is not None:
        return _funasr_model
    with _funasr_lock:
        if _funasr_model is not None or _funasr_error is not None:
            return _funasr_model
        try:
            from funasr import AutoModel

            _funasr_model = AutoModel(
                model=FUNASR_MODEL,
                vad_model=FUNASR_VAD_MODEL,
                vad_kwargs={"max_single_segment_time": 30000},
                punc_model=FUNASR_PUNC_MODEL,
                disable_update=True,
            )
        except Exception as exc:  # noqa: BLE001 - service health should report provider load failures.
            _funasr_error = str(exc)
    return _funasr_model


def load_funasr_fallback_vosk_model():
    global _funasr_fallback_vosk_model, _funasr_fallback_vosk_error
    if _funasr_fallback_vosk_model is not None or _funasr_fallback_vosk_error is not None:
        return _funasr_fallback_vosk_model
    with _funasr_fallback_vosk_lock:
        if _funasr_fallback_vosk_model is not None or _funasr_fallback_vosk_error is not None:
            return _funasr_fallback_vosk_model
        try:
            from vosk import Model

            _funasr_fallback_vosk_model = Model(str(FUNASR_FALLBACK_VOSK_MODEL_PATH))
        except Exception as exc:  # noqa: BLE001
            _funasr_fallback_vosk_error = str(exc)
    return _funasr_fallback_vosk_model


def load_piper_voice():
    global _piper_voice, _piper_error
    if _piper_voice is not None or _piper_error is not None:
        return _piper_voice
    with _piper_lock:
        if _piper_voice is not None or _piper_error is not None:
            return _piper_voice
        try:
            from piper import PiperVoice

            _piper_voice = PiperVoice.load(str(PIPER_MODEL_PATH), str(PIPER_CONFIG_PATH), use_cuda=False)
        except Exception as exc:  # noqa: BLE001 - service health should report provider load failures.
            _piper_error = str(exc)
    return _piper_voice


def stt_model_status():
    if STT_PROVIDER == "local-vosk":
        if _vosk_model is not None:
            return "READY"
        return "LOCAL_MODEL_ERROR" if _vosk_error else "LOCAL_MODEL_PENDING"
    if STT_PROVIDER == "local-funasr":
        if _funasr_model is not None:
            return "READY"
        if _funasr_error:
            return "LOCAL_MODEL_ERROR"
        if FUNASR_FALLBACK_VOSK_ENABLED and _funasr_fallback_vosk_model is not None:
            return "DEGRADED"
        return "LOCAL_MODEL_PENDING"
    return "READY"


def tts_model_status():
    if TTS_PROVIDER == "local-piper":
        if _piper_voice is not None:
            return "READY"
        return "LOCAL_MODEL_ERROR" if _piper_error else "LOCAL_MODEL_PENDING"
    return "READY"


def warmup_models():
    if STT_PROVIDER == "local-vosk":
        load_vosk_model()
    if STT_PROVIDER == "local-funasr":
        load_funasr_model()
        if _funasr_model is None and FUNASR_FALLBACK_VOSK_ENABLED and FUNASR_FALLBACK_VOSK_MODEL_PATH.exists():
            load_funasr_fallback_vosk_model()
    if TTS_PROVIDER == "local-piper":
        load_piper_voice()


def transcribe_mock(payload):
    return {
        "providerId": "mock-stt",
        "modelId": "fixture-transcript-v1",
        "transcript": "我选择左边的图片",
        "confidence": 0.96,
        "language": payload.get("languageHint") or "zh-CN",
        "durationMs": 1200,
        "externalNetworkCalled": False,
        "inputPersisted": False,
        "generatedAt": now_iso(),
    }


def synthesize_mock(payload):
    return {
        "providerId": "mock-tts",
        "modelId": "synthetic-silence-v1",
        "audioBase64": "UklGRiQAAABXQVZFZm10IBAAAAABAAEA",
        "mimeType": "audio/wav",
        "durationMs": 900,
        "sampleRateHz": 16000,
        "externalNetworkCalled": False,
        "inputPersisted": False,
        "generatedAt": now_iso(),
    }


def read_wav_pcm(audio_bytes):
    with wave.open(BytesIO(audio_bytes), "rb") as wav_file:
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frame_rate = wav_file.getframerate()
        chunks = []
        while True:
            chunk = wav_file.readframes(16000)
            if not chunk:
                break
            chunks.append(chunk)

    frames = b"".join(chunks)
    bytes_per_frame = channels * sample_width
    if bytes_per_frame <= 0:
        raise wave.Error("Invalid WAV frame size.")
    usable_length = (len(frames) // bytes_per_frame) * bytes_per_frame
    if usable_length != len(frames):
        frames = frames[:usable_length]
    return frames, channels, sample_width, frame_rate, usable_length // bytes_per_frame


def wav_duration_ms(audio_bytes):
    _frames, _channels, _sample_width, frame_rate, frame_count = read_wav_pcm(audio_bytes)
    return round((frame_count / float(frame_rate)) * 1000), frame_rate


def add_leading_silence_to_wav(audio_bytes, silence_ms=300):
    frames, channels, sample_width, frame_rate, _frame_count = read_wav_pcm(audio_bytes)
    silence_frame_count = int(frame_rate * silence_ms / 1000)
    silence = b"\x00" * silence_frame_count * channels * sample_width

    output = BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(channels)
        wav_file.setsampwidth(sample_width)
        wav_file.setframerate(frame_rate)
        wav_file.writeframes(silence + frames)
    return output.getvalue()


def synthesize_piper(payload):
    voice = load_piper_voice()
    if voice is None:
        return {
            "error": {
                "code": "LOCAL_MODEL_PENDING",
                "message": _piper_error or "Piper model is not available.",
            }
        }, 503

    text = (payload.get("text") or "").strip()
    if not text:
        return {"error": {"code": "EMPTY_TEXT", "message": "TTS text is required."}}, 400

    output = BytesIO()
    try:
        with wave.open(output, "wb") as wav_file:
            voice.synthesize_wav(text, wav_file)
        audio_bytes = output.getvalue()
        duration_ms, sample_rate = wav_duration_ms(audio_bytes)
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return {"error": {"code": "PROVIDER_FAILURE", "message": str(exc)}}, 500

    return {
        "providerId": "local-piper-zh-huayan",
        "modelId": "zh_CN-huayan-medium",
        "audioBase64": base64.b64encode(audio_bytes).decode("ascii"),
        "mimeType": "audio/wav",
        "durationMs": duration_ms,
        "sampleRateHz": sample_rate,
        "externalNetworkCalled": False,
        "inputPersisted": False,
        "generatedAt": now_iso(),
    }, 200


def transcribe_vosk(payload):
    model = load_vosk_model()
    if model is None:
        return {
            "error": {
                "code": "LOCAL_MODEL_PENDING",
                "message": _vosk_error or "Vosk model is not available.",
            }
        }, 503

    audio = base64.b64decode(payload.get("audioBase64") or "", validate=True)
    if len(audio) > MAX_AUDIO_BYTES:
        return {"error": {"code": "AUDIO_TOO_LARGE", "message": "Audio payload exceeds service limit."}}, 413

    try:
        from vosk import KaldiRecognizer

        with wave.open(BytesIO(audio), "rb") as wav_file:
            recognizer = KaldiRecognizer(model, wav_file.getframerate())
            while True:
                data = wav_file.readframes(4000)
                if not data:
                    break
                recognizer.AcceptWaveform(data)
            final = json.loads(recognizer.FinalResult())
            duration_ms = round((wav_file.getnframes() / float(wav_file.getframerate())) * 1000)
    except Exception as exc:  # noqa: BLE001
        return {"error": {"code": "UNSUPPORTED_AUDIO_FORMAT", "message": str(exc)}}, 400

    return {
        "providerId": "local-vosk-small-cn",
        "modelId": "vosk-model-small-cn-0.22",
        "transcript": final.get("text", ""),
        "confidence": 0.8 if final.get("text") else 0.0,
        "language": payload.get("languageHint") or "zh-CN",
        "durationMs": duration_ms,
        "externalNetworkCalled": False,
        "inputPersisted": False,
        "generatedAt": now_iso(),
    }, 200


def transcribe_fallback_vosk(payload):
    model = load_funasr_fallback_vosk_model()
    if model is None:
        return {
            "error": {
                "code": "LOCAL_MODEL_PENDING",
                "message": _funasr_fallback_vosk_error or "Expert Vosk fallback model is not available.",
            }
        }, 503

    audio = base64.b64decode(payload.get("audioBase64") or "", validate=True)
    if len(audio) > MAX_AUDIO_BYTES:
        return {"error": {"code": "AUDIO_TOO_LARGE", "message": "Audio payload exceeds service limit."}}, 413

    try:
        from vosk import KaldiRecognizer

        with wave.open(BytesIO(audio), "rb") as wav_file:
            recognizer = KaldiRecognizer(model, wav_file.getframerate())
            while True:
                data = wav_file.readframes(4000)
                if not data:
                    break
                recognizer.AcceptWaveform(data)
            final = json.loads(recognizer.FinalResult())
            duration_ms = round((wav_file.getnframes() / float(wav_file.getframerate())) * 1000)
    except Exception as exc:  # noqa: BLE001
        return {"error": {"code": "UNSUPPORTED_AUDIO_FORMAT", "message": str(exc)}}, 400

    return {
        "providerId": "expert-vosk-small-cn",
        "modelId": "vosk-model-small-cn-0.22",
        "transcript": final.get("text", ""),
        "confidence": 0.78 if final.get("text") else 0.0,
        "language": payload.get("languageHint") or "zh-CN",
        "durationMs": duration_ms,
        "externalNetworkCalled": False,
        "inputPersisted": False,
        "fallbackFrom": "local-funasr",
        "generatedAt": now_iso(),
    }, 200


def extract_funasr_text(result):
    if isinstance(result, list):
        return "".join(str(item.get("text", "")) for item in result if isinstance(item, dict)).strip()
    if isinstance(result, dict):
        return str(result.get("text", "")).strip()
    return ""


def transcribe_funasr(payload):
    model = load_funasr_model()
    if model is None:
        return {
            "error": {
                "code": "LOCAL_MODEL_PENDING",
                "message": _funasr_error or "FunASR model is not available.",
            }
        }, 503

    try:
        audio = base64.b64decode(payload.get("audioBase64") or "", validate=True)
    except Exception as exc:  # noqa: BLE001
        return {"error": {"code": "BAD_AUDIO", "message": str(exc)}}, 400

    if len(audio) > MAX_AUDIO_BYTES:
        return {"error": {"code": "AUDIO_TOO_LARGE", "message": "Audio payload exceeds service limit."}}, 413

    temp_path = None
    started = time.perf_counter()
    try:
        duration_ms, sample_rate = wav_duration_ms(audio)
        audio_for_model = add_leading_silence_to_wav(audio)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(audio_for_model)

        with _funasr_infer_lock:
            result = model.generate(
                input=str(temp_path),
                batch_size_s=300,
                batch_size_threshold_s=60,
            )
        transcript = extract_funasr_text(result)
        if not transcript:
            return {"error": {"code": "EMPTY_RESULT", "message": "No speech text recognized."}}, 200

        return {
            "providerId": "local-funasr-zh",
            "modelId": FUNASR_MODEL,
            "transcript": transcript,
            "confidence": 0.9,
            "language": payload.get("languageHint") or "zh-CN",
            "durationMs": duration_ms,
            "sampleRateHz": sample_rate,
            "processLatencyMs": round((time.perf_counter() - started) * 1000),
            "externalNetworkCalled": False,
            "inputPersisted": False,
            "generatedAt": now_iso(),
        }, 200
    except wave.Error as exc:
        return {"error": {"code": "UNSUPPORTED_AUDIO_FORMAT", "message": str(exc)}}, 400
    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        return {"error": {"code": "PROVIDER_FAILURE", "message": str(exc)}}, 500
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


class VoiceServiceHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib handler API.
        if self.path != "/health":
            return json_response(self, 404, {"error": {"code": "NOT_FOUND", "message": "Unknown route."}})
        stt_provider_status = stt_model_status()
        tts_provider_status = tts_model_status()
        return json_response(
            self,
            200,
            {
                "status": "ok",
                "provider": STT_PROVIDER,
                "providerStatus": stt_provider_status,
                "sttProvider": STT_PROVIDER,
                "sttProviderStatus": stt_provider_status,
                "ttsProvider": TTS_PROVIDER,
                "ttsProviderStatus": tts_provider_status,
                "modelPath": str(VOSK_MODEL_PATH),
                "funasrModel": FUNASR_MODEL,
                "funasrVadModel": FUNASR_VAD_MODEL,
                "funasrPuncModel": FUNASR_PUNC_MODEL,
                "funasrFallbackVoskEnabled": FUNASR_FALLBACK_VOSK_ENABLED,
                "funasrFallbackVoskModelPath": str(FUNASR_FALLBACK_VOSK_MODEL_PATH),
                "piperModelPath": str(PIPER_MODEL_PATH),
                "externalNetworkCalled": False,
                "inputPersisted": False,
                "generatedAt": now_iso(),
            },
        )

    def do_POST(self):  # noqa: N802 - stdlib handler API.
        if self.path not in {"/stt", "/tts"}:
            return json_response(self, 404, {"error": {"code": "NOT_FOUND", "message": "Unknown route."}})
        try:
            length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:  # noqa: BLE001
            return json_response(self, 400, {"error": {"code": "BAD_JSON", "message": "Invalid JSON request."}})

        if self.path == "/tts":
            if TTS_PROVIDER == "local-piper":
                result, status = synthesize_piper(payload)
                return json_response(self, status, result)
            return json_response(self, 200, synthesize_mock(payload))

        if STT_PROVIDER == "local-vosk":
            result, status = transcribe_vosk(payload)
            return json_response(self, status, result)
        if STT_PROVIDER == "local-funasr":
            result, status = transcribe_funasr(payload)
            return json_response(self, status, result)
        return json_response(self, 200, transcribe_mock(payload))

    def log_message(self, _format, *_args):
        return


def main():
    host = os.environ.get("VOICE_SERVICE_HOST", "127.0.0.1")
    port = int(os.environ.get("VOICE_SERVICE_PORT", "8765"))
    server = ThreadingHTTPServer((host, port), VoiceServiceHandler)
    print(f"Voice service listening on http://{host}:{port} stt={STT_PROVIDER} tts={TTS_PROVIDER}")
    threading.Thread(target=warmup_models, daemon=True).start()
    server.serve_forever()


if __name__ == "__main__":
    main()
