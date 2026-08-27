"""Demo-machine curriculum scope shared by catalogs and reports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


COURSE_SCOPE_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "demo_course_scope.json"
)
SAFE_DEFAULT_COURSE_TYPES = ("pairing", "ordering")
COURSE_TYPE_ALIASES = {
    "matching": "pairing",
    "sequencing": "ordering",
    "speech": "naming",
    "imitation": "mimic",
    "pose": "mimic",
}
COURSE_TYPE_LABELS = {
    "mimic": "模仿",
    "pairing": "配对",
    "ordering": "排序",
}
COURSE_DIMENSIONS = {
    "mimic": "attention",
    "pairing": "matching",
    "ordering": "ordering",
}


def canonical_course_type(value: Any) -> str:
    course_type = str(value or "").strip().lower()
    return COURSE_TYPE_ALIASES.get(course_type, course_type)


def _normalize_course_types(values: Iterable[Any]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in values:
        course_type = canonical_course_type(value)
        if not course_type or course_type in normalized:
            continue
        normalized.append(course_type)
    return tuple(normalized)


def enabled_course_types(path: Path | None = None) -> tuple[str, ...]:
    """Return the reviewed demo scope, failing closed to pairing/ordering."""
    scope_path = Path(path) if path is not None else COURSE_SCOPE_PATH
    try:
        raw = json.loads(scope_path.read_text(encoding="utf-8"))
        if raw.get("schemaVersion") != 1:
            raise ValueError("unsupported_demo_course_scope_schema")
        values = raw.get("enabledCourseTypes")
        if not isinstance(values, list):
            raise ValueError("enabledCourseTypes_must_be_an_array")
        normalized = _normalize_course_types(values)
        if not normalized:
            raise ValueError("enabledCourseTypes_must_not_be_empty")
        if normalized != SAFE_DEFAULT_COURSE_TYPES:
            raise ValueError("demo_course_scope_must_remain_fixed")
        return SAFE_DEFAULT_COURSE_TYPES
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return SAFE_DEFAULT_COURSE_TYPES


def enabled_course_type_set(path: Path | None = None) -> frozenset[str]:
    return frozenset(enabled_course_types(path))


def enabled_course_dimensions(path: Path | None = None) -> tuple[str, ...]:
    course_dimensions = tuple(
        COURSE_DIMENSIONS[course_type]
        for course_type in enabled_course_types(path)
        if course_type in COURSE_DIMENSIONS
    )
    # 注意力是跨课程采集维度，不是可选课程；两课程 Demo 仍保留该报告证据。
    return tuple(dict.fromkeys(("attention", *course_dimensions)))


def is_course_type_enabled(value: Any, path: Path | None = None) -> bool:
    return canonical_course_type(value) in enabled_course_type_set(path)


def filter_course_payloads(
    courses: Sequence[Mapping[str, Any]],
    *,
    type_key: str = "type",
    path: Path | None = None,
) -> list[Mapping[str, Any]]:
    enabled = enabled_course_type_set(path)
    return [
        course
        for course in courses
        if canonical_course_type(course.get(type_key)) in enabled
    ]
