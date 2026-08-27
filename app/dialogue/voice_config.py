"""Single production browser-TTS voice contract.

The classroom child runs Microsoft Edge.  Voice choice is deliberately not a
user preference: every browser-TTS path must resolve the same Xiaoyi Natural
voice or report it unavailable instead of silently selecting another voice.
"""

from __future__ import annotations

from typing import Any, Dict


FIXED_BROWSER_TTS_VOICE_NAME = (
    "Microsoft Xiaoyi Online (Natural) - Chinese (Mainland) (zh-CN)"
)
FIXED_BROWSER_TTS_VOICE_MATCH_PREFIX = (
    "Microsoft Xiaoyi Online (Natural) - Chinese (Mainland)"
)
FIXED_BROWSER_TTS_VOICE_LOCALIZED_TOKEN = "微软小易在线"
FIXED_BROWSER_TTS_VOICE_LANG = "zh-CN"


def fixed_browser_tts_voice_config() -> Dict[str, str]:
    """Return a fresh template/client projection of the immutable voice."""
    return {
        "name": FIXED_BROWSER_TTS_VOICE_NAME,
        "matchPrefix": FIXED_BROWSER_TTS_VOICE_MATCH_PREFIX,
        "localizedToken": FIXED_BROWSER_TTS_VOICE_LOCALIZED_TOKEN,
        "lang": FIXED_BROWSER_TTS_VOICE_LANG,
        "label": FIXED_BROWSER_TTS_VOICE_NAME,
    }


def is_fixed_browser_tts_voice_name(name: Any) -> bool:
    """Accept Edge's English or bilingual display name for Xiaoyi only."""
    normalized = str(name or "").strip().casefold()
    if not normalized:
        return False
    return (
        normalized.startswith(FIXED_BROWSER_TTS_VOICE_MATCH_PREFIX.casefold())
        or FIXED_BROWSER_TTS_VOICE_LOCALIZED_TOKEN.casefold() in normalized
    )


def project_fixed_browser_tts_runtime_state(data: Dict[str, Any]) -> Dict[str, Any]:
    """Discard every reported browser voice except the locked Xiaoyi voice."""
    fixed = None
    for item in (data.get("voices") or [])[:100]:
        if (
            not isinstance(item, dict)
            or str(item.get("lang") or "").strip().casefold()
            != FIXED_BROWSER_TTS_VOICE_LANG.casefold()
            or not is_fixed_browser_tts_voice_name(item.get("name"))
        ):
            continue
        fixed = {
            "name": str(item.get("name") or "")[:200],
            "lang": str(item.get("lang") or FIXED_BROWSER_TTS_VOICE_LANG)[:40],
            "label": str(item.get("label") or FIXED_BROWSER_TTS_VOICE_NAME)[:260],
        }
        break
    selected = str(data.get("selectedVoice") or "")[:200]
    available = fixed is not None and is_fixed_browser_tts_voice_name(selected)
    return {
        "voices": [fixed] if fixed is not None else [],
        "selectedVoice": fixed["name"] if available else "",
        "voiceAvailable": available,
        "fixedVoice": fixed_browser_tts_voice_config(),
    }
