"""Partner business logic — edit this file (and partner.env)."""

from __future__ import annotations

import base64
import os
import wave
from io import BytesIO


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip() or default


CONTEXT_INPUT_MODE = _env("CONTEXT_INPUT_MODE", "both")
STT_MODE = _env("STT_MODE", "audio")


def process_turn(payload: dict) -> dict:
    """Single entry: audio + pageContext + history -> replyText + replyAudio."""
    page = payload.get("pageContext") or {}
    text_ctx = page.get("text") or {}
    screenshot = page.get("screenshot")
    narrative = text_ctx.get("narrative") or text_ctx.get("prompt") or ""

    use_text = CONTEXT_INPUT_MODE in {"text", "both"}
    use_image = CONTEXT_INPUT_MODE in {"image", "both"} and screenshot

    scene_hint = narrative if use_text else ""
    if use_image:
        scene_hint = f"{scene_hint} [screenshot attached]".strip()

    transcript_hint = ""
    if STT_MODE == "audio":
        audio = payload.get("audio") or {}
        transcript_hint = _mock_transcribe(audio.get("base64") or "")
    elif STT_MODE == "text_only_fallback":
        transcript_hint = scene_hint[:80]

    reply = (
        f"我听到了。{transcript_hint or '我们继续看看题目吧。'}"
        if scene_hint or transcript_hint
        else "我们继续当前题目吧。"
    )

    return {
        "ok": True,
        "replyText": reply,
        "replyAudio": _silent_wav_base64(),
        "metadata": {
            "provider": "reference-partner",
            "sttModeUsed": STT_MODE,
            "contextMode": CONTEXT_INPUT_MODE,
        },
    }


def _mock_transcribe(_audio_b64: str) -> str:
    return "（参考 STT）"


def _silent_wav_base64() -> dict:
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(b"\x00\x00" * 1600)
    return {"base64": base64.b64encode(buf.getvalue()).decode("ascii"), "mimeType": "audio/wav"}
