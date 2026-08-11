"""监控台事件环形缓冲（进程内，最近 N 条）。"""
from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

_MAX_EVENTS = 50
_lock = threading.Lock()
_events: Deque[Dict[str, Any]] = deque(maxlen=_MAX_EVENTS)
# quality 降级限流：training:question -> last quality
_last_quality: Dict[str, str] = {}
_last_quality_at: Dict[str, float] = {}
_QUALITY_COOLDOWN_SEC = 15.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def append_monitor_event(
    kind: str,
    message: str,
    *,
    training_session_id: Optional[str] = None,
    question_id: Optional[str] = None,
    level: str = "info",
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    item = {
        "t": _now_iso(),
        "kind": kind,
        "level": level,
        "message": message,
        "trainingSessionId": training_session_id,
        "questionId": question_id,
    }
    if extra:
        item["extra"] = extra
    with _lock:
        _events.append(item)


def list_monitor_events(limit: int = 50) -> List[Dict[str, Any]]:
    with _lock:
        items = list(_events)
    if limit > 0:
        return items[-limit:]
    return items


def clear_monitor_events() -> None:
    with _lock:
        _events.clear()
        _last_quality.clear()
        _last_quality_at.clear()


def note_attention_quality(
    training_session_id: Optional[str],
    question_id: Optional[str],
    quality: Optional[str],
) -> None:
    """质量进入 DEGRADED/MISSING 时记一条事件（同窗限流）。"""
    q = str(quality or "").upper()
    if q not in ("DEGRADED", "MISSING", "INSUFFICIENT", "MISSING_DEVICE"):
        return
    key = f"{training_session_id or ''}:{question_id or ''}"
    now = time.time()
    with _lock:
        prev = _last_quality.get(key)
        last_at = _last_quality_at.get(key, 0.0)
        if prev == q and (now - last_at) < _QUALITY_COOLDOWN_SEC:
            return
        _last_quality[key] = q
        _last_quality_at[key] = now
    append_monitor_event(
        "attention_quality",
        f"注意力质量降级为 {q}",
        training_session_id=training_session_id,
        question_id=question_id,
        level="warn",
        extra={"quality": q},
    )
