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
_PRESET_MODES = ("assessment", "intervention")


class JsonCoursePresetStore:
    """Persist exact lesson selections with independent defaults per use case."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    @staticmethod
    def _empty_document() -> dict[str, Any]:
        return {
            "schemaVersion": 3,
            "defaultPresetIds": {mode: None for mode in _PRESET_MODES},
            "presets": [],
        }

    @staticmethod
    def _normalize_mode(value: Any) -> str:
        mode = str(value or "").strip().lower()
        if mode not in _PRESET_MODES:
            raise ValueError("invalid_course_preset_mode")
        return mode

    @staticmethod
    def _normalize_course_types(values: Sequence[Any]) -> list[str]:
        """Normalize legacy type-only requests before the API expands their items."""
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in values:
            course_type = str(raw or "").strip().lower()
            if not re.fullmatch(r"[a-z][a-z0-9_-]*", course_type):
                raise ValueError("course_types_must_be_identifiers")
            if course_type not in seen:
                seen.add(course_type)
                normalized.append(course_type)
        if not normalized:
            raise ValueError("course_types_required")
        return normalized

    @staticmethod
    def _normalize_item_ids(values: Sequence[Any]) -> list[int]:
        normalized: list[int] = []
        seen: set[int] = set()
        for raw in values:
            if isinstance(raw, bool) or not str(raw).strip().isdigit():
                raise ValueError("item_ids_must_be_positive_integers")
            item_id = int(raw)
            if item_id <= 0:
                raise ValueError("item_ids_must_be_positive_integers")
            if item_id not in seen:
                seen.add(item_id)
                normalized.append(item_id)
        if not normalized:
            raise ValueError("course_selection_items_required")
        return normalized

    @classmethod
    def _normalize_course_selections(cls, values: Sequence[Any]) -> list[dict[str, Any]]:
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
            raise ValueError("course_selections_must_be_an_array")
        normalized: list[dict[str, Any]] = []
        seen_types: set[str] = set()
        for raw in values:
            if not isinstance(raw, Mapping):
                raise ValueError("invalid_course_selection")
            course_type = str(raw.get("courseType") or "").strip().lower()
            if not re.fullmatch(r"[a-z][a-z0-9_-]*", course_type):
                raise ValueError("course_types_must_be_identifiers")
            if course_type in seen_types:
                raise ValueError("duplicate_course_selection_type")
            raw_item_ids = raw.get("itemIds")
            if not isinstance(raw_item_ids, list):
                raise ValueError("item_ids_must_be_an_array")
            seen_types.add(course_type)
            normalized.append({
                "courseType": course_type,
                "itemIds": cls._normalize_item_ids(raw_item_ids),
            })
        if not normalized:
            raise ValueError("course_selections_required")
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

    @staticmethod
    def _repair_defaults(
        document: dict[str, Any],
        *,
        preferred: Mapping[str, str] | None = None,
    ) -> None:
        defaults = document.setdefault("defaultPresetIds", {})
        preferred = preferred or {}
        for mode in _PRESET_MODES:
            candidates = [item["id"] for item in document["presets"] if item["mode"] == mode]
            requested = preferred.get(mode)
            current = defaults.get(mode)
            if requested in candidates:
                defaults[mode] = requested
            elif current not in candidates:
                defaults[mode] = candidates[0] if candidates else None

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_document()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        if (
            not isinstance(raw, dict)
            or raw.get("schemaVersion") != 3
            or not isinstance(raw.get("defaultPresetIds"), dict)
            or not isinstance(raw.get("presets"), list)
        ):
            raise ValueError("invalid_course_preset_document")

        presets: list[dict[str, Any]] = []
        ids: set[str] = set()
        for item in raw["presets"]:
            if not isinstance(item, dict):
                raise ValueError("invalid_course_preset")
            if not isinstance(item.get("courseSelections"), list):
                raise ValueError("invalid_course_preset_selections")
            preset_id = str(item.get("id") or "").strip()
            if not preset_id or preset_id in ids:
                raise ValueError("invalid_course_preset_id")
            ids.add(preset_id)
            presets.append({
                "id": preset_id,
                "mode": self._normalize_mode(item.get("mode")),
                "name": self._normalize_name(item.get("name")),
                "description": self._normalize_description(item.get("description")),
                "courseSelections": self._normalize_course_selections(item["courseSelections"]),
            })

        defaults: dict[str, str | None] = {}
        presets_by_id = {item["id"]: item for item in presets}
        for mode in _PRESET_MODES:
            default_id = raw["defaultPresetIds"].get(mode)
            candidates = [item for item in presets if item["mode"] == mode]
            if candidates and default_id is None:
                raise ValueError("default_course_preset_required")
            if default_id is not None:
                default_id = str(default_id)
                target = presets_by_id.get(default_id)
                if target is None or target["mode"] != mode:
                    raise ValueError("invalid_default_course_preset")
            defaults[mode] = default_id
        return {
            "schemaVersion": 3,
            "defaultPresetIds": defaults,
            "presets": presets,
        }

    @staticmethod
    def _assert_unique_name(
        presets: Sequence[Mapping[str, Any]],
        name: str,
        *,
        except_id: str | None = None,
    ) -> None:
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
        mode: Any,
        name: Any,
        description: Any,
        course_selections: Sequence[Any],
        is_default: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            document = self._load()
            clean_mode = self._normalize_mode(mode)
            clean_name = self._normalize_name(name)
            self._assert_unique_name(document["presets"], clean_name)
            preset = {
                "id": self._new_id(clean_name, {str(item["id"]) for item in document["presets"]}),
                "mode": clean_mode,
                "name": clean_name,
                "description": self._normalize_description(description),
                "courseSelections": self._normalize_course_selections(course_selections),
            }
            document["presets"].append(preset)
            preferred = {clean_mode: preset["id"]} if is_default else None
            self._repair_defaults(document, preferred=preferred)
            atomic_write_json(self.path, document)
            return copy.deepcopy(preset)

    def update(
        self,
        preset_id: str,
        *,
        mode: Any,
        name: Any,
        description: Any,
        course_selections: Sequence[Any],
        is_default: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            document = self._load()
            target = next((item for item in document["presets"] if item["id"] == preset_id), None)
            if target is None:
                raise KeyError("course_preset_not_found")
            clean_name = self._normalize_name(name)
            clean_mode = self._normalize_mode(mode)
            self._assert_unique_name(document["presets"], clean_name, except_id=preset_id)
            target.update({
                "mode": clean_mode,
                "name": clean_name,
                "description": self._normalize_description(description),
                "courseSelections": self._normalize_course_selections(course_selections),
            })
            preferred = {clean_mode: preset_id} if is_default else None
            self._repair_defaults(document, preferred=preferred)
            atomic_write_json(self.path, document)
            return copy.deepcopy(target)

    def delete(self, preset_id: str) -> None:
        with self._lock:
            document = self._load()
            remaining = [item for item in document["presets"] if item["id"] != preset_id]
            if len(remaining) == len(document["presets"]):
                raise KeyError("course_preset_not_found")
            document["presets"] = remaining
            self._repair_defaults(document)
            atomic_write_json(self.path, document)


__all__ = ["JsonCoursePresetStore"]
