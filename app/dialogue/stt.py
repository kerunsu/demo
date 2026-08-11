"""对话用 FunASR：优先本进程，否则走本地 voice-service HTTP（app.py 可自动拉起）。"""

from __future__ import annotations

import base64
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from app.utils.logger import setup_logger

logger = setup_logger("dialogue.stt")

_model = None
_model_error: Optional[str] = None
_lock = threading.Lock()


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
            _model = AutoModel(model=model_ref, disable_update=True)
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


def transcribe_audio_base64(
    audio_base64: str,
    *,
    mime_type: str = "audio/webm",
) -> Dict[str, Any]:
    """返回 {ok, transcript, provider, error}。"""
    try:
        audio_bytes = base64.b64decode(audio_base64, validate=False)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "transcript": "", "provider": None, "error": f"invalid_base64:{exc}"}

    if len(audio_bytes) < 64:
        return {"ok": False, "transcript": "", "provider": None, "error": "audio_too_short"}

    wav_bytes = _ensure_wav_bytes(audio_bytes, mime_type)

    # 优先本机 FunASR；失败则走 DemoRobot voice-service（同样可配 FunASR）
    text = _transcribe_local(wav_bytes)
    if text:
        return {"ok": True, "transcript": text, "provider": "local-funasr", "error": None}

    remote = _transcribe_voice_service(wav_bytes, mime_type="audio/wav")
    if remote.get("ok") and remote.get("transcript"):
        return {
            "ok": True,
            "transcript": remote["transcript"],
            "provider": "voice-service-funasr",
            "error": None,
        }

    # 本进程无 FunASR 时，以 voice-service 错误为准，避免掩盖「服务未开」
    err = remote.get("error") or _model_error or "funasr_unavailable"
    return {"ok": False, "transcript": "", "provider": None, "error": err}
