"""旧 MappingResolver 配置到 InteractionProfileV2 的只读迁移演练。

这里不写 ``course_map.json``，也不自动发布。迁移报告先给出可审阅的 draft，
由控制端显式校验、预览、发布；这样不会改变学生/课程/项目四级旧优先级。
"""

from __future__ import annotations

import copy
from typing import Any, Mapping, Optional

from .event_catalog import EventCatalog, infer_event_key
from .validation import validate_profile


_SOCIAL_EVENT_KEYS = {
    "social_greeting_intro": "greeting",
    "social_greeting_play": "greeting_response",
    "social_farewell_bye": "farewell",
    "social_farewell_reply": "farewell_response",
}


def legacy_aux_to_event(course_type: Optional[str], aux_type: str) -> Optional[str]:
    aux_type = str(aux_type or "").strip()
    if aux_type in _SOCIAL_EVENT_KEYS:
        return _SOCIAL_EVENT_KEYS[aux_type]
    if aux_type == "question":
        return infer_event_key(course_type, {"question": True})
    if aux_type in {"praise", "hint", "idle", "silent"}:
        return aux_type if aux_type != "silent" else "idle"
    return None


def legacy_entry_to_binding(entry: Any) -> dict[str, Any]:
    """将一个旧 entry 转为 replace draft；不会丢掉旧 sequence 字段。"""
    if isinstance(entry, list):
        return {"mode": "replace", "motions": copy.deepcopy(entry)}
    if not isinstance(entry, Mapping):
        return {"mode": "replace", "motions": []}
    binding: dict[str, Any] = {"mode": "replace"}
    for source, target in (
        ("motions", "motions"),
        ("emotion", "emotion"),
        ("sequence", "sequence"),
        ("speech", "speech"),
    ):
        if source in entry:
            binding[target] = copy.deepcopy(entry[source])
    return binding


def build_course_draft(
    *,
    course_id: str,
    course_type: Optional[str],
    legacy_course_entries: Mapping[str, Any],
    version: str = "migration-draft-1",
) -> dict[str, Any]:
    events: dict[str, Any] = {}
    warnings: list[str] = []
    for aux_type, entry in legacy_course_entries.items():
        event_key = legacy_aux_to_event(course_type, str(aux_type))
        if event_key is None:
            warnings.append(f"unmapped_legacy_aux:{aux_type}")
            continue
        events[event_key] = {"binding": legacy_entry_to_binding(entry)}
    return {
        "schemaVersion": 1,
        "courseId": str(course_id),
        "courseType": course_type,
        "version": version,
        "status": "draft",
        "events": events,
        "migration": {
            "source": "legacy.course_map.courses",
            "warnings": warnings,
            "autoPublish": False,
            "compatibility": "review-before-publish",
        },
    }


def dry_run_course_migration(
    *,
    course_id: str,
    course_type: Optional[str],
    legacy_course_entries: Mapping[str, Any],
    catalog: Optional[EventCatalog] = None,
    version: str = "migration-draft-1",
) -> dict[str, Any]:
    catalog = catalog or EventCatalog()
    profile = build_course_draft(
        course_id=course_id,
        course_type=course_type,
        legacy_course_entries=legacy_course_entries,
        version=version,
    )
    errors = validate_profile(profile, catalog)
    return {
        "courseId": str(course_id),
        "courseType": course_type,
        "sourceEntryCount": len(legacy_course_entries),
        "convertedEventCount": len(profile["events"]),
        "status": "review_required" if not errors else "blocked",
        "errors": list(errors),
        "profile": profile,
        "writes": [],
    }


__all__ = [
    "build_course_draft",
    "dry_run_course_migration",
    "legacy_aux_to_event",
    "legacy_entry_to_binding",
]
