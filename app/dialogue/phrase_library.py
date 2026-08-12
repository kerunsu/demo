"""Server-editable selection and custom additions for browser TTS phrases.

The shipped phrase bank stays in ``dialogue_phrases.yaml``.  Server-side
choices and locally added phrases live in a small overlay so editing does not
rewrite or accidentally discard the reviewed base corpus.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any, Dict, Iterable, List, Optional

import yaml

from app.config import BASE_DIR


OVERLAY_PATH = BASE_DIR / "config" / "dialogue_phrase_selection.yaml"
SCHEMA_VERSION = 1
MANAGED_INTENTS = (
    "question",
    "hint",
    "praise",
    "social_greeting_intro",
    "social_greeting_play",
    "social_farewell_bye",
    "social_farewell_reply",
)
_lock = RLock()


def _clean_lines(values: Any) -> List[str]:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return []
    result: List[str] = []
    for value in values:
        line = str(value or "").strip()
        if line and line not in result:
            result.append(line)
    return result


def _load_overlay() -> Dict[str, Any]:
    if not OVERLAY_PATH.exists():
        return {"schema_version": SCHEMA_VERSION, "custom": {}, "enabled": {}}
    with OVERLAY_PATH.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("实时话术选择文件格式错误")
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("custom", {})
    data.setdefault("enabled", {})
    return data


def _atomic_save(data: Dict[str, Any]) -> None:
    OVERLAY_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{OVERLAY_PATH.name}.", suffix=".tmp", dir=str(OVERLAY_PATH.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            yaml.safe_dump(
                data,
                handle,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, OVERLAY_PATH)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def custom_lines(intent: str, course_key: str) -> List[str]:
    with _lock:
        data = _load_overlay()
        section = (data.get("custom") or {}).get(intent) or {}
        return _clean_lines(section.get(course_key)) if isinstance(section, dict) else []


def enabled_lines(intent: str, course_key: str) -> Optional[List[str]]:
    """Return explicit selection, or ``None`` when the base bank is untouched."""
    with _lock:
        data = _load_overlay()
        section = (data.get("enabled") or {}).get(intent) or {}
        if not isinstance(section, dict) or course_key not in section:
            return None
        return _clean_lines(section.get(course_key))


def merge_library(base_lines: Iterable[str], intent: str, course_key: str) -> List[str]:
    return _clean_lines([*base_lines, *custom_lines(intent, course_key)])


def effective_lines(base_lines: Iterable[str], intent: str, course_key: str) -> List[str]:
    library = merge_library(base_lines, intent, course_key)
    selected = enabled_lines(intent, course_key)
    if selected is None:
        return library
    allowed = set(library)
    return [line for line in selected if line in allowed]


def get_slot(base_lines: Iterable[str], intent: str, course_key: str) -> Dict[str, Any]:
    library = merge_library(base_lines, intent, course_key)
    selected = enabled_lines(intent, course_key)
    return {
        "intent": intent,
        "courseType": course_key,
        "library": library,
        "selected": library if selected is None else [x for x in selected if x in set(library)],
        "explicit": selected is not None,
    }


def set_enabled(intent: str, course_key: str, lines: Any) -> Dict[str, Any]:
    if intent not in MANAGED_INTENTS:
        raise ValueError("不支持的话术用途")
    course_key = str(course_key or "").strip().lower()
    if not course_key:
        raise ValueError("courseType required")
    chosen = _clean_lines(lines)
    if not chosen:
        raise ValueError("每组至少启用一句话术")
    with _lock:
        from app.dialogue.phrases import base_lines_for

        data = _load_overlay()
        library = merge_library(base_lines_for(intent, course_key), intent, course_key)
        unknown = [line for line in chosen if line not in library]
        if unknown:
            raise ValueError(f"话术不在本地语料库中: {unknown[0]}")
        data.setdefault("enabled", {}).setdefault(intent, {})[course_key] = chosen
        _atomic_save(data)
    return get_slot(base_lines_for(intent, course_key), intent, course_key)


def add_custom(intent: str, course_key: str, text: Any) -> Dict[str, Any]:
    if intent not in MANAGED_INTENTS:
        raise ValueError("不支持的话术用途")
    course_key = str(course_key or "").strip().lower()
    line = str(text or "").strip()
    if not course_key:
        raise ValueError("courseType required")
    if not line:
        raise ValueError("请输入新话术")
    if len(line) > 200:
        raise ValueError("单条话术不能超过 200 个字符")
    if "\n" in line or "\r" in line:
        raise ValueError("单条话术不能换行")
    with _lock:
        from app.dialogue.phrases import base_lines_for

        data = _load_overlay()
        custom = data.setdefault("custom", {}).setdefault(intent, {}).setdefault(course_key, [])
        custom = _clean_lines(custom)
        if line not in base_lines_for(intent, course_key) and line not in custom:
            custom.append(line)
        data["custom"][intent][course_key] = custom

        library = merge_library(base_lines_for(intent, course_key), intent, course_key)
        enabled_section = data.setdefault("enabled", {}).setdefault(intent, {})
        selected = _clean_lines(enabled_section.get(course_key, library))
        if line not in selected:
            selected.append(line)
        enabled_section[course_key] = selected
        _atomic_save(data)
    return get_slot(base_lines_for(intent, course_key), intent, course_key)
