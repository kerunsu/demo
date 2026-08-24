"""Versioned, atomic storage for teacher course presets."""

from __future__ import annotations

import copy
import json
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.storage.session_layout import atomic_write_json


_SAFE_ID = re.compile(r"[^a-z0-9-]+")


class JsonCoursePresetStore:
    """Keep ordered course selections independent from Flask and SQLAlchemy."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    @staticmethod
    def _empty_document() -> dict[str, Any]:
        return {"schemaVersion": 1, "defaultPresetId": None, "presets": []}

    @staticmethod
    def _normalize_course_ids(values: Sequence[Any]) -> list[int]:
        normalized: list[int] = []
        seen: set[int] = set()
        for raw in values:
            if isinstance(raw, bool):
                raise ValueError("course_ids_must_be_positive_integers")
            try:
                course_id = int(raw)
            except (TypeError, ValueError) as exc:
                raise ValueError("course_ids_must_be_positive_integers") from exc
            if course_id <= 0 or str(raw).strip() != str(course_id):
                raise ValueError("course_ids_must_be_positive_integers")
            if course_id not in seen:
                seen.add(course_id)
                normalized.append(course_id)
        if not normalized:
            raise ValueError("course_ids_required")
        return normalized

    @staticmethod
    def _normalize_name(value: Any) -> str:
        name = str(value or "").strip()
        if not name:
            raise ValueError("preset_name_required")
        if len(name) > 80:
            raise ValueError("preset_name_too_long")
        return name

    @staticmethod
    def _normalize_description(value: Any) -> str:
        description = str(value or "").strip()
        if len(description) > 240:
            raise ValueError("preset_description_too_long")
        return description

    @staticmethod
    def _new_id(name: str, occupied: set[str]) -> str:
        base = _SAFE_ID.sub("-", name.lower()).strip("-")[:36] or "preset"
        candidate = base
        while candidate in occupied:
            candidate = f"{base[:27]}-{uuid.uuid4().hex[:8]}"
        return candidate

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_document()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if (
            not isinstance(raw, dict)
            or raw.get("schemaVersion") != 1
            or not isinstance(raw.get("presets"), list)
        ):
            raise ValueError("invalid_course_preset_document")

        presets: list[dict[str, Any]] = []
        ids: set[str] = set()
        for item in raw["presets"]:
            if not isinstance(item, dict):
                raise ValueError("invalid_course_preset")
            if not isinstance(item.get("courseIds"), list):
                raise ValueError("invalid_course_preset_course_ids")
            preset_id = str(item.get("id") or "").strip()
            if not preset_id or preset_id in ids:
                raise ValueError("invalid_course_preset_id")
            ids.add(preset_id)
            presets.append({
                "id": preset_id,
                "name": self._normalize_name(item.get("name")),
                "description": self._normalize_description(item.get("description")),
                "courseIds": self._normalize_course_ids(item.get("courseIds") or []),
            })

        default_id = raw.get("defaultPresetId")
        if default_id is not None and str(default_id) not in ids:
            raise ValueError("invalid_default_course_preset")
        if presets and default_id is None:
            raise ValueError("default_course_preset_required")
        return {
            "schemaVersion": 1,
            "defaultPresetId": str(default_id) if default_id is not None else None,
            "presets": presets,
        }

    @staticmethod
    def _assert_unique_name(presets: Sequence[Mapping[str, Any]], name: str, *, except_id: str | None = None) -> None:
        duplicate = next((
            item for item in presets
            if str(item.get("id")) != except_id
            and str(item.get("name") or "").casefold() == name.casefold()
        ), None)
        if duplicate is not None:
            raise ValueError("preset_name_already_exists")

    def get_document(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._load())

    def create(
        self,
        *,
        name: Any,
        description: Any,
        course_ids: Sequence[Any],
        is_default: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            document = self._load()
            clean_name = self._normalize_name(name)
            self._assert_unique_name(document["presets"], clean_name)
            preset = {
                "id": self._new_id(clean_name, {str(item["id"]) for item in document["presets"]}),
                "name": clean_name,
                "description": self._normalize_description(description),
                "courseIds": self._normalize_course_ids(course_ids),
            }
            document["presets"].append(preset)
            if is_default or not document["defaultPresetId"]:
                document["defaultPresetId"] = preset["id"]
            atomic_write_json(self.path, document)
            return copy.deepcopy(preset)

    def update(
        self,
        preset_id: str,
        *,
        name: Any,
        description: Any,
        course_ids: Sequence[Any],
        is_default: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            document = self._load()
            target = next((item for item in document["presets"] if item["id"] == preset_id), None)
            if target is None:
                raise KeyError("course_preset_not_found")
            clean_name = self._normalize_name(name)
            self._assert_unique_name(document["presets"], clean_name, except_id=preset_id)
            target.update({
                "name": clean_name,
                "description": self._normalize_description(description),
                "courseIds": self._normalize_course_ids(course_ids),
            })
            if is_default:
                document["defaultPresetId"] = preset_id
            atomic_write_json(self.path, document)
            return copy.deepcopy(target)

    def delete(self, preset_id: str) -> None:
        with self._lock:
            document = self._load()
            remaining = [item for item in document["presets"] if item["id"] != preset_id]
            if len(remaining) == len(document["presets"]):
                raise KeyError("course_preset_not_found")
            document["presets"] = remaining
            if document["defaultPresetId"] == preset_id:
                document["defaultPresetId"] = remaining[0]["id"] if remaining else None
            atomic_write_json(self.path, document)


__all__ = ["JsonCoursePresetStore"]
