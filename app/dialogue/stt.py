"""对话用 FunASR：优先本进程，否则走本地 voice-service HTTP（app.py 可自动拉起）。"""

from __future__ import annotations

import base64
import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from array import array
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from app.utils.logger import setup_logger

logger = setup_logger("dialogue.stt")

_model = None
_model_error: Optional[str] = None
_lock = threading.Lock()

# The browser VAD is a latency optimization, not a trust boundary.  Classroom
# fan/projector noise and speaker feedback can still open a turn, so re-check
# raw PCM before FunASR and reject common silence/noise hallucinations after it.
_DIALOGUE_RMS_THRESHOLD = 0.006
_DIALOGUE_FRAME_RMS_THRESHOLD = 0.014
_DIALOGUE_PEAK_THRESHOLD = 0.02
_DIALOGUE_MIN_VOICED_RATIO = 0.10
_DIALOGUE_FRAME_MS = 20
_PUNCT_RE = re.compile(
    r'[\s\u3000，。！？、；：,.!?;:\'\"“”‘’（）()\[\]【】<>《》…—～~·]+'
)
_CJK_RE = re.compile(r'[\u4e00-\u9fff]')
_LATIN_RE = re.compile(r'[A-Za-z]')
_FILLER_ONLY = frozenset({
    '嗯', '啊', '呃', '哦', '唔', '呵', '额', '欸', '唉',
    '的', '了', '呢', '吧', '嘛', '呀', '嗯嗯', '啊啊', '呃呃',
})


def _local_model_path() -> Optional[str]:
    override = (os.environ.get("FUNASR_MODEL_PATH") or "").strip()
    if override and Path(override).exists():
        return override
    home = Path.home() / ".cache" / "modelscope" / "hub" / "models" / "iic"
    candidate = home / "speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
    if candidate.exists():
        return str(candidate)
    return None


def _load_local_funasr():
    global _model, _model_error
    if _model is not None or _model_error is not None:
        return _model
    with _lock:
        if _model is not None or _model_error is not None:
            return _model
        try:
            from funasr import AutoModel

            model_ref = _local_model_path() or "paraformer-zh"
            logger.info("加载对话 FunASR: %s", model_ref)
            _model = AutoModel(
                model=model_ref,
                vad_model=(
                    os.environ.get("DIALOGUE_FUNASR_VAD_MODEL")
                    or os.environ.get("VOICE_SERVICE_FUNASR_VAD_MODEL")
                    or "fsmn-vad"
                ),
                vad_kwargs={"max_single_segment_time": 30000},
                punc_model=(
                    os.environ.get("DIALOGUE_FUNASR_PUNC_MODEL")
                    or os.environ.get("VOICE_SERVICE_FUNASR_PUNC_MODEL")
                    or "ct-punc"
                ),
                disable_update=True,
            )
        except Exception as exc:  # noqa: BLE001
            _model_error = str(exc)
            logger.warning("本进程 FunASR 不可用: %s", exc)
    return _model


def _suffix_for_mime(mime_type: str) -> str:
    mime = (mime_type or "").lower()
    if "wav" in mime:
        return ".wav"
    if "webm" in mime:
        return ".webm"
    if "ogg" in mime:
        return ".ogg"
    if "mp4" in mime or "m4a" in mime:
        return ".m4a"
    if "mpeg" in mime or "mp3" in mime:
        return ".mp3"
    return ".bin"


def _looks_like_wav(audio_bytes: bytes) -> bool:
    return len(audio_bytes) >= 12 and audio_bytes[0:4] == b"RIFF" and audio_bytes[8:12] == b"WAVE"


def _normalized_asr_text(text: str) -> str:
    return _PUNCT_RE.sub('', str(text or '').strip())


def _is_plausible_asr_text(text: str) -> bool:
    cleaned = _normalized_asr_text(text)
    if not cleaned or cleaned in _FILLER_ONLY:
        return False
    # Chinese classroom speech should not become a short Latin noise token such
    # as "Gyggny".  Keep mixed/CJK text and single-character CJK answers.
    if _LATIN_RE.search(cleaned) and not _CJK_RE.search(cleaned):
        return False
    if len(cleaned) < 2 and not _CJK_RE.search(cleaned):
        return False
    return True


def _is_likely_tts_echo(transcript: str, reference_text: Optional[str]) -> bool:
    heard = _normalized_asr_text(transcript)
    spoken = _normalized_asr_text(reference_text or '')
    if len(heard) < 2 or len(spoken) < 2:
        return False
    if heard in spoken:
        return True
    similarity = difflib.SequenceMatcher(None, heard, spoken).ratio()
    return similarity >= 0.72


def _pcm_samples_from_wav(wav_bytes: bytes) -> Optional[tuple[list[float], int]]:
    """Decode uncompressed PCM WAV to mono floats for the server-side VAD."""
    try:
        with wave.open(BytesIO(wav_bytes), "rb") as wav_file:
            if wav_file.getcomptype() != "NONE":
                return None
            channels = max(1, wav_file.getnchannels())
            sample_width = wav_file.getsampwidth()
            sample_rate = wav_file.getframerate()
            frames = wav_file.readframes(wav_file.getnframes())
    except (EOFError, wave.Error):
        return None

    if sample_rate <= 0 or sample_width not in {1, 2, 4} or not frames:
        return None
    if sample_width == 1:
        interleaved = [(value - 128) / 128.0 for value in frames]
    else:
        typecode = 'h' if sample_width == 2 else 'i'
        raw = array(typecode)
        raw.frombytes(frames)
        if sys.byteorder != 'little':
            raw.byteswap()
        scale = float(1 << (sample_width * 8 - 1))
        interleaved = [value / scale for value in raw]

    usable = (len(interleaved) // channels) * channels
    if usable <= 0:
        return None
    if channels == 1:
        mono = interleaved[:usable]
    else:
        mono = [
            sum(interleaved[index:index + channels]) / channels
            for index in range(0, usable, channels)
        ]
    return mono, sample_rate


def _wav_voice_activity(wav_bytes: bytes) -> Optional[Dict[str, Any]]:
    decoded = _pcm_samples_from_wav(wav_bytes)
    if decoded is None:
        return None
    samples, sample_rate = decoded
    if not samples:
        return None
    rms = (sum(sample * sample for sample in samples) / len(samples)) ** 0.5
    peak = max(abs(sample) for sample in samples)
    frame_samples = max(1, int(sample_rate * _DIALOGUE_FRAME_MS / 1000))
    frame_count = len(samples) // frame_samples
    voiced_frames = 0
    for frame_index in range(frame_count):
        start = frame_index * frame_samples
        frame = samples[start:start + frame_samples]
        frame_rms = (sum(value * value for value in frame) / len(frame)) ** 0.5
        frame_peak = max(abs(value) for value in frame)
        if (
            frame_rms >= _DIALOGUE_FRAME_RMS_THRESHOLD
            and frame_peak >= _DIALOGUE_PEAK_THRESHOLD
        ):
            voiced_frames += 1
    voiced_ratio = voiced_frames / frame_count if frame_count else 0.0
    is_speech = (
        rms >= _DIALOGUE_RMS_THRESHOLD
        and peak >= _DIALOGUE_PEAK_THRESHOLD
        and voiced_ratio >= _DIALOGUE_MIN_VOICED_RATIO
    )
    return {
        "isSpeech": is_speech,
        "rms": round(rms, 6),
        "peak": round(peak, 6),
        "voicedRatio": round(voiced_ratio, 6),
        "sampleRate": sample_rate,
    }


def _ffmpeg_bin() -> Optional[str]:
    override = (os.environ.get("FFMPEG_PATH") or "").strip()
    if override and Path(override).exists():
        return override
    found = shutil.which("ffmpeg")
    return found


def _ensure_wav_bytes(audio_bytes: bytes, mime_type: str) -> bytes:
    """FunASR / voice-service 期望 WAV；浏览器常上送 webm。"""
    if _looks_like_wav(audio_bytes):
        return audio_bytes

    ffmpeg = _ffmpeg_bin()
    if not ffmpeg:
        logger.warning("非 WAV 音频且未找到 ffmpeg，将原样尝试识别 mime=%s", mime_type)
        return audio_bytes

    suffix = _suffix_for_mime(mime_type)
    src_path = None
    dst_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as src:
            src.write(audio_bytes)
            src_path = src.name
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as dst:
            dst_path = dst.name
        cmd = [
            ffmpeg,
            "-y",
            "-i",
            src_path,
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            dst_path,
        ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=float(os.environ.get("DIALOGUE_FFMPEG_TIMEOUT_SECONDS") or 30),
            check=False,
        )
        if proc.returncode != 0:
            logger.warning(
                "ffmpeg 转 WAV 失败 code=%s stderr=%s",
                proc.returncode,
                (proc.stderr or b"")[:300],
            )
            return audio_bytes
        return Path(dst_path).read_bytes()
    except Exception as exc:  # noqa: BLE001
        logger.warning("ffmpeg 转 WAV 异常: %s", exc)
        return audio_bytes
    finally:
        for path in (src_path, dst_path):
            if not path:
                continue
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass


def _transcribe_local(audio_bytes: bytes) -> Optional[str]:
    model = _load_local_funasr()
    if model is None:
        return None
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        path = tmp.name
    try:
        res = model.generate(input=path, batch_size=1, disable_pbar=True)
        result = res[0] if isinstance(res, list) else res
        text = (result.get("text") or "").replace(" ", "").strip()
        return text or None
    except Exception as exc:  # noqa: BLE001
        logger.warning("本机 FunASR 识别失败: %s", exc)
        return None
    finally:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass


def _transcribe_voice_service(
    audio_bytes: bytes, mime_type: str = "audio/wav"
) -> Dict[str, Any]:
    """返回 {ok, transcript, error}。"""
    base = (os.environ.get("VOICE_PYTHON_SERVICE_URL") or "http://127.0.0.1:8765").rstrip("/")
    try:
        resp = requests.post(
            f"{base}/stt",
            json={
                "audioBase64": base64.b64encode(audio_bytes).decode("ascii"),
                "mimeType": mime_type or "audio/wav",
                "languageHint": "zh-CN",
            },
            timeout=float(os.environ.get("DIALOGUE_STT_TIMEOUT_SECONDS") or 60),
        )
        if resp.status_code == 503:
            logger.warning("voice-service STT pending/error: %s", resp.text[:200])
            return {"ok": False, "transcript": "", "error": "voice_service_pending"}
        if not resp.ok:
            logger.warning("voice-service STT HTTP %s: %s", resp.status_code, resp.text[:200])
            return {"ok": False, "transcript": "", "error": f"voice_service_http_{resp.status_code}"}
        data = resp.json()
        err = data.get("error")
        if err:
            # EMPTY_RESULT 等仍算服务可达，只是本段无有效语音
            code = err.get("code") if isinstance(err, dict) else str(err)
            logger.warning("voice-service STT error: %s", err)
            return {"ok": False, "transcript": "", "error": f"voice_service:{code}"}
        text = (data.get("transcript") or "").strip()
        if not text:
            return {"ok": False, "transcript": "", "error": "voice_service:empty_transcript"}
        return {"ok": True, "transcript": text, "error": None}
    except Exception as exc:  # noqa: BLE001
        logger.warning("voice-service STT 调用失败: %s", exc)
        return {"ok": False, "transcript": "", "error": f"voice_service_unreachable:{exc}"}


def _finalize_transcript(
    text: str,
    *,
    provider: str,
    timing: Dict[str, Any],
    echo_reference_text: Optional[str],
) -> Dict[str, Any]:
    if not _is_plausible_asr_text(text):
        logger.info("丢弃不可信对话 ASR 文本 provider=%s text=%r", provider, text[:40])
        return {
            "ok": False,
            "transcript": "",
            "provider": provider,
            "error": "implausible_transcript",
            "timing": {**timing, "rejectedAs": "implausible_transcript"},
        }
    if _is_likely_tts_echo(text, echo_reference_text):
        logger.info("丢弃疑似扬声器回声 provider=%s transcriptLength=%s", provider, len(text))
        return {
            "ok": False,
            "transcript": "",
            "provider": provider,
            "error": "tts_echo",
            "timing": {**timing, "rejectedAs": "tts_echo"},
        }
    return {
        "ok": True,
        "transcript": text,
        "provider": provider,
        "error": None,
        "timing": timing,
    }


def transcribe_wav_bytes(
    wav_bytes: bytes,
    *,
    echo_reference_text: Optional[str] = None,
) -> Dict[str, Any]:
    """识别已是 WAV 的 PCM 字节。返回 {ok, transcript, provider, error}。"""
    if not wav_bytes or len(wav_bytes) < 64:
        return {"ok": False, "transcript": "", "provider": None, "error": "audio_too_short"}

    vad = _wav_voice_activity(wav_bytes)
    vad_timing = {"vad": vad} if vad is not None else {}
    if vad is not None and not vad.get("isSpeech"):
        logger.info(
            "对话音频未通过服务端 VAD rms=%s peak=%s voiced=%s",
            vad.get("rms"),
            vad.get("peak"),
            vad.get("voicedRatio"),
        )
        return {
            "ok": False,
            "transcript": "",
            "provider": None,
            "error": "no_speech",
            "timing": vad_timing,
        }

    local_started = time.perf_counter()
    text = _transcribe_local(wav_bytes)
    local_ms = round((time.perf_counter() - local_started) * 1000, 3)
    if text:
        return _finalize_transcript(
            text,
            provider="local-funasr",
            timing={
                **vad_timing,
                "localAttemptMs": local_ms,
                "remoteFallbackMs": 0,
            },
            echo_reference_text=echo_reference_text,
        )

    remote_started = time.perf_counter()
    remote = _transcribe_voice_service(wav_bytes, mime_type="audio/wav")
    remote_ms = round((time.perf_counter() - remote_started) * 1000, 3)
    if remote.get("ok") and remote.get("transcript"):
        return _finalize_transcript(
            str(remote["transcript"]),
            provider="voice-service-funasr",
            timing={
                **vad_timing,
                "localAttemptMs": local_ms,
                "remoteFallbackMs": remote_ms,
            },
            echo_reference_text=echo_reference_text,
        )

    err = remote.get("error") or _model_error or "funasr_unavailable"
    return {
        "ok": False,
        "transcript": "",
        "provider": None,
        "error": err,
        "timing": {
            **vad_timing,
            "localAttemptMs": local_ms,
            "remoteFallbackMs": remote_ms,
        },
    }


def voice_service_ready(timeout: float = 2.0) -> bool:
    """本地 voice-service /health 是否 READY（连续 ASR 回退用）。"""
    base = (os.environ.get("VOICE_PYTHON_SERVICE_URL") or "http://127.0.0.1:8765").rstrip("/")
    try:
        resp = requests.get(f"{base}/health", timeout=timeout)
        if not resp.ok:
            return False
        data = resp.json() if resp.content else {}
        status = str(
            data.get("sttProviderStatus")
            or data.get("providerStatus")
            or data.get("status")
            or ""
        ).upper()
        return status in {"READY", "OK", "AVAILABLE"}
    except Exception:  # noqa: BLE001
        return False


def transcribe_audio_base64(
    audio_base64: str,
    *,
    mime_type: str = "audio/webm",
    echo_reference_text: Optional[str] = None,
) -> Dict[str, Any]:
    """返回 {ok, transcript, provider, error}。"""
    decode_started = time.perf_counter()
    try:
        audio_bytes = base64.b64decode(audio_base64, validate=False)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "transcript": "", "provider": None, "error": f"invalid_base64:{exc}"}
    decode_ms = round((time.perf_counter() - decode_started) * 1000, 3)

    if len(audio_bytes) < 64:
        return {"ok": False, "transcript": "", "provider": None, "error": "audio_too_short"}

    convert_started = time.perf_counter()
    wav_bytes = _ensure_wav_bytes(audio_bytes, mime_type)
    convert_ms = round((time.perf_counter() - convert_started) * 1000, 3)
    result = transcribe_wav_bytes(
        wav_bytes,
        echo_reference_text=echo_reference_text,
    )
    timing = dict(result.get("timing") or {})
    timing.update({"base64DecodeMs": decode_ms, "audioConvertMs": convert_ms})
    result["timing"] = timing
    return result
