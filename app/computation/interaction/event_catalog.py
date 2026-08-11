"""正式事件目录与课程类型兼容推导。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional


@dataclass(frozen=True)
class EventDefinition:
    key: str
    label: str
    kind: str = "instant"  # state | instant | timed
    duration_ms: Optional[int] = None
    interruptible: bool = True
    priority: int = 0
    return_to_idle: bool = True
    allowed_from: tuple[str, ...] = ()


_DEFAULT_EVENTS = (
    ("idle", "待机", "state", None, True, 0, False),
    ("sleepy", "困倦", "state", None, True, 10, False),
    ("question.naming", "提问-命名", "instant", None, True, 50, True),
    ("question.vocal_imitation", "提问-拟声/模仿发声", "instant", None, True, 50, True),
    ("question.ordering", "提问-排序", "instant", None, True, 50, True),
    ("question.pairing", "提问-配对", "instant", None, True, 50, True),
    ("praise", "鼓励/表扬", "instant", None, True, 80, True),
    ("hint", "提示", "instant", None, True, 70, True),
    ("call_child", "呼唤儿童", "instant", None, True, 60, True),
    ("retry", "鼓励/再试一次", "instant", None, True, 75, True),
    ("greeting", "打招呼", "instant", None, True, 40, True),
    ("greeting_response", "回应打招呼", "instant", None, True, 40, True),
    ("farewell", "再见", "instant", None, True, 40, True),
    ("farewell_response", "回应再见", "instant", None, True, 40, True),
    ("calm_speech.2s", "平静说话-2秒", "timed", 2000, True, 30, True),
    ("calm_speech.3s", "平静说话-3秒", "timed", 3000, True, 30, True),
)


class EventCatalog:
    def __init__(self, events: Optional[Iterable[EventDefinition]] = None) -> None:
        self._events: Dict[str, EventDefinition] = {
            key: EventDefinition(key, label, kind, duration, interruptible, priority, idle)
            for key, label, kind, duration, interruptible, priority, idle in _DEFAULT_EVENTS
        }
        for event in events or ():
            self.register(event)

    def register(self, event: EventDefinition) -> None:
        key = str(event.key or "").strip()
        if not key or any(ch.isspace() for ch in key):
            raise ValueError("event_key_invalid")
        kind = str(event.kind or "instant").strip().lower()
        duration_ms = None if event.duration_ms is None else int(event.duration_ms)
        priority = int(event.priority)
        if kind not in {"state", "instant", "timed"}:
            raise ValueError("event_kind_invalid")
        if kind == "timed" and (duration_ms is None or duration_ms <= 0):
            raise ValueError("timed_event_duration_required")
        if duration_ms is not None and duration_ms < 0:
            raise ValueError("event_duration_invalid")
        allowed_from = tuple(str(item).strip() for item in event.allowed_from if str(item).strip())
        if key in allowed_from:
            raise ValueError("event_transition_self_reference")
        if (allowed_from != event.allowed_from or kind != event.kind or
                duration_ms != event.duration_ms or priority != event.priority):
            event = EventDefinition(
                key=key,
                label=event.label,
                kind=kind,
                duration_ms=duration_ms,
                interruptible=event.interruptible,
                priority=priority,
                return_to_idle=event.return_to_idle,
                allowed_from=allowed_from,
            )
        if key in self._events and self._events[key] != event:
            raise ValueError(f"published_event_key_immutable:{key}")
        self._events[key] = event

    def get(self, key: str) -> Optional[EventDefinition]:
        return self._events.get(str(key or ""))

    def list(self) -> tuple[EventDefinition, ...]:
        return tuple(self._events.values())

    def validate(self, key: str) -> EventDefinition:
        event = self.get(key)
        if event is None:
            raise KeyError(f"event_not_registered:{key}")
        return event

    def validate_transition(self, previous: Optional[str], current: str) -> bool:
        """验证可选状态转移白名单；未声明白名单的事件保持兼容地允许。"""
        event = self.validate(current)
        if not event.allowed_from or previous is None:
            return True
        return str(previous) in event.allowed_from


_global_catalog = EventCatalog()


def get_event_catalog() -> EventCatalog:
    return _global_catalog


def infer_event_key(course_type: Optional[str], aux: Optional[dict] = None) -> Optional[str]:
    """只做明确兼容推导；优先级和旧 aux 语义保持不变。"""

    aux = aux or {}
    if aux.get("praise") is True:
        return "praise"
    if aux.get("hint") is True:
        return "hint"
    if aux.get("socialGreetingIntro") is True:
        return "greeting"
    if aux.get("socialGreetingPlay") is True:
        return "greeting_response"
    if aux.get("socialFarewellBye") is True:
        return "farewell"
    if aux.get("socialFarewellReply") is True:
        return "farewell_response"
    if aux.get("question") is not True:
        return "idle" if not aux else None
    kind = str(course_type or "").strip().lower()
    if kind == "naming":
        return "question.naming"
    if kind == "onomatopoeia":
        return "question.vocal_imitation"
    if kind == "mimic":
        explicit = (
            aux.get("eventKey")
            or aux.get("event_key")
            or aux.get("questionSubtype")
            or aux.get("questionType")
            or aux.get("interactionEvent")
            or aux.get("courseSubtype")
        )
        if aux.get("isVocalImitation") is True or str(explicit or "").strip().lower() in {
            "question.vocal_imitation", "vocal_imitation", "onomatopoeia"
        }:
            return "question.vocal_imitation"
        # A generic mimic course may be pose/action imitation. Keep legacy
        # behavior unless the course metadata makes the speech meaning explicit.
        return None
    if kind in {"ordering", "sequencing"}:
        return "question.ordering"
    if kind in {"pairing", "matching"}:
        return "question.pairing"
    return None


__all__ = ["EventCatalog", "EventDefinition", "infer_event_key", "get_event_catalog"]
