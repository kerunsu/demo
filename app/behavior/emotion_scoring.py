"""
服务端情绪计分（对齐 browser-emotion-v1 输出形状）

生产路径无 MediaPipe blendshape 时，用 RealAttentionAnalyzer 的几何情绪标签 +
微笑/张嘴比例映射到 positive / focused / frustrated。
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(v)))


def map_label_to_emotion_scores(
    emotion_label: str,
    *,
    smile_ratio: float = 0.0,
    mar: float = 0.0,
) -> Dict[str, Any]:
    """
    将几何情绪标签映射为与 C2 一致的三色比例。

    Returns:
        positiveScore / focusedScore / frustratedScore / confidence / ...
    """
    label = (emotion_label or "Neutral").strip()
    smile = _clamp(abs(smile_ratio) * 20.0)  # ~0.02 → 0.4
    open_jaw = _clamp(mar)

    if label == "Happy":
        positive = _clamp(0.55 + 0.35 * smile)
        frustrated = _clamp(0.08 * (1.0 - smile))
        focused = _clamp(1.0 - positive - frustrated)
    elif label == "Surprise":
        positive = _clamp(0.25 + 0.2 * open_jaw)
        focused = _clamp(0.45)
        frustrated = _clamp(1.0 - positive - focused)
    elif label == "Sad":
        frustrated = _clamp(0.5 + 0.2 * (1.0 - smile))
        positive = _clamp(0.1)
        focused = _clamp(1.0 - positive - frustrated)
    else:  # Neutral / unknown
        focused = _clamp(0.55 + 0.2 * (1.0 - open_jaw))
        positive = _clamp(0.2 + 0.3 * smile)
        frustrated = _clamp(1.0 - positive - focused)

    total = positive + focused + frustrated
    if total <= 0.05:
        return {
            "positiveScore": 0.0,
            "focusedScore": 0.0,
            "frustratedScore": 0.0,
            "confidence": 0.0,
            "degraded": True,
            "algorithmVersion": "server-emotion-v1",
            "unavailable": True,
        }

    positive /= total
    focused /= total
    frustrated /= total
    confidence = _clamp(0.4 + 0.4 * max(positive, focused, frustrated))

    return {
        "positiveScore": round(positive, 3),
        "focusedScore": round(focused, 3),
        "frustratedScore": round(frustrated, 3),
        "confidence": round(confidence, 3),
        "degraded": False,
        "algorithmVersion": "server-emotion-v1",
        "unavailable": False,
        "label": label,
    }


def emotion_quality_from_scores(emo: Optional[Dict[str, Any]], face_present: bool) -> str:
    if not face_present or not emo or emo.get("unavailable"):
        return "MISSING"
    if emo.get("degraded") or float(emo.get("confidence") or 0) < 0.45:
        return "DEGRADED"
    return "VALID"


def select_attention_observations(attention_obs: list, prefer_browser: bool) -> list:
    """
    聚合用注意力样本选择：
    - prefer_browser：仅当存在「有效」browser 样本时用 browser，否则回退全部/server
    - 否则优先有效 server，无则用全部有效样本
    """
    if not attention_obs:
        return []

    def _valid(o) -> bool:
        dq = getattr(o, "data_quality", None) or ""
        return str(dq).upper() not in ("MISSING",) and (
            getattr(o, "face_present", True) is not False
        )

    browser = [o for o in attention_obs if getattr(o, "provider", "server") == "browser"]
    server = [o for o in attention_obs if getattr(o, "provider", "server") != "browser"]
    browser_valid = [o for o in browser if _valid(o)]
    server_valid = [o for o in server if _valid(o)]

    if prefer_browser and browser_valid:
        return browser_valid
    if server_valid:
        return server_valid
    if prefer_browser and browser:
        # 仅有无效 browser 时不要挡住 server
        return server_valid or [o for o in attention_obs if _valid(o)] or attention_obs
    return [o for o in attention_obs if _valid(o)] or attention_obs
