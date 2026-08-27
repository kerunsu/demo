"""Canonical one-course-per-type catalog migration.

The legacy seed and the resource importers used different course titles, so a
single CourseType could acquire two Course rows.  This module repairs that
split at the fact-source boundary and migrates the two external ID stores that
must move with it: teacher presets and robot behavior mappings.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from sqlalchemy import text

from app.storage.session_layout import atomic_write_json
from database.models import Course, CourseItem, CourseType, db


TYPE_CN_TO_EN = {
    "模仿": "mimic",
    "命名": "naming",
    "拟声": "onomatopoeia",
    "配对": "pairing",
    "排序": "ordering",
    "社交": "social",
}


def _read_json(path: Path, *, default: Mapping[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return copy.deepcopy(dict(default))
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"invalid_json_document:{path.name}")
    return value


def _normalized_path(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/").rstrip("/").casefold()


def _item_identity(item: CourseItem) -> tuple[str, str]:
    name = str(item.name or "").strip().casefold()
    media = _normalized_path(item.media_file)
    return name, media


def _find_same_item(targets: Iterable[CourseItem], source: CourseItem) -> CourseItem | None:
    source_name, source_media = _item_identity(source)
    if source_media:
        by_media = next((item for item in targets if _item_identity(item)[1] == source_media), None)
        if by_media is not None:
            return by_media
    if source_name:
        return next((item for item in targets if _item_identity(item)[0] == source_name), None)
    return None


def _fill_missing_item_fields(target: CourseItem, source: CourseItem) -> None:
    for field in ("icon", "hint_audio", "difficulty", "config", "speech_target"):
        if not getattr(target, field, None) and getattr(source, field, None):
            setattr(target, field, getattr(source, field))


def _course_rank(course: Course) -> tuple[int, int, int]:
    """Prefer the content-rich row, then a runnable entry, then stable oldest ID."""
    return (len(course.items or []), 1 if course.entry_file else 0, -int(course.id))


def _has_mapping_value(value: Any) -> bool:
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, dict):
        return bool(value)
    return value not in (None, "")


def _merge_mapping_layer(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if key == "items":
            continue
        if key not in target or not _has_mapping_value(target.get(key)):
            target[key] = copy.deepcopy(value)


def _migrate_course_map(
    document: dict[str, Any],
    course_aliases: Mapping[int, int],
    item_aliases: Mapping[tuple[int, int], int],
) -> dict[str, Any]:
    updated = copy.deepcopy(document)
    courses = updated.setdefault("courses", {})
    for old_id, canonical_id in course_aliases.items():
        old_key, canonical_key = str(old_id), str(canonical_id)
        source = courses.get(old_key)
        if not isinstance(source, dict):
            courses.pop(old_key, None)
            continue
        target = courses.setdefault(canonical_key, {})
        _merge_mapping_layer(target, source)
        target_items = target.setdefault("items", {})
        for old_item_key, item_value in (source.get("items") or {}).items():
            try:
                old_item_id = int(old_item_key)
            except (TypeError, ValueError):
                continue
            target_item_id = item_aliases.get((old_id, old_item_id), old_item_id)
            target_item = target_items.setdefault(str(target_item_id), {})
            if isinstance(target_item, dict) and isinstance(item_value, dict):
                _merge_mapping_layer(target_item, item_value)
        courses.pop(old_key, None)

    # Historical student overrides are no longer in the execution chain, but
    # migrate their IDs so the configuration document contains no split course.
    for student in (updated.get("students") or {}).values():
        if not isinstance(student, dict):
            continue
        containers = [student]
        if isinstance(student.get("courses"), dict):
            containers.append(student["courses"])
        for container in containers:
            for old_id, canonical_id in course_aliases.items():
                old_key, canonical_key = str(old_id), str(canonical_id)
                source = container.get(old_key)
                if not isinstance(source, dict):
                    container.pop(old_key, None)
                    continue
                target = container.setdefault(canonical_key, {})
                _merge_mapping_layer(target, source)
                container.pop(old_key, None)
        flat_items = student.get("items")
        if isinstance(flat_items, dict):
            for key in list(flat_items):
                parts = str(key).replace("/", "_").split("_", 1)
                if len(parts) != 2 or not all(part.isdigit() for part in parts):
                    continue
                old_course_id, old_item_id = int(parts[0]), int(parts[1])
                if old_course_id not in course_aliases:
                    continue
                new_course_id = course_aliases[old_course_id]
                new_item_id = item_aliases.get((old_course_id, old_item_id), old_item_id)
                flat_items.setdefault(f"{new_course_id}_{new_item_id}", flat_items[key])
                del flat_items[key]
    return updated


def _migrate_presets(
    document: dict[str, Any],
    course_id_to_type: Mapping[int, str],
    item_ids_by_type: Mapping[str, list[int]],
    item_id_aliases: Mapping[int, int],
) -> dict[str, Any]:
    version = document.get("schemaVersion")
    if version not in (1, 2, 3):
        raise ValueError("invalid_course_preset_document")
    presets = document.get("presets")
    if not isinstance(presets, list):
        raise ValueError("invalid_course_preset_document")

    migrated: list[dict[str, Any]] = []
    for raw in presets:
        if not isinstance(raw, dict):
            raise ValueError("invalid_course_preset")
        mode = str(raw.get("mode") or "assessment").strip().lower()
        if mode not in ("assessment", "intervention"):
            raise ValueError("invalid_course_preset_mode")
        if version == 3:
            values = raw.get("courseSelections")
            if not isinstance(values, list):
                raise ValueError("invalid_course_preset_selection")
            selections: list[dict[str, Any]] = []
            seen_types: set[str] = set()
            for selection in values:
                if not isinstance(selection, dict) or not isinstance(selection.get("itemIds"), list):
                    raise ValueError("invalid_course_preset_selection")
                course_type = str(selection.get("courseType") or "").strip().lower()
                if not course_type or course_type in seen_types:
                    raise ValueError("invalid_course_preset_selection")
                seen_types.add(course_type)
                item_ids: list[int] = []
                for raw_item_id in selection["itemIds"]:
                    item_id = item_id_aliases.get(int(raw_item_id), int(raw_item_id))
                    if item_id not in item_ids:
                        item_ids.append(item_id)
                selections.append({"courseType": course_type, "itemIds": item_ids})
        else:
            values = raw.get("courseTypes") if version == 2 else raw.get("courseIds")
            if not isinstance(values, list):
                raise ValueError("invalid_course_preset_selection")
            course_types: list[str] = []
            for value in values:
                course_type = (
                    str(value or "").strip().lower()
                    if version == 2
                    else course_id_to_type.get(int(value))
                )
                if not course_type:
                    raise ValueError(f"unknown_preset_course:{value}")
                if course_type not in course_types:
                    course_types.append(course_type)
            # Type-only presets had no way to express a subset. Materialize the
            # exact current IDs once so later catalog additions cannot silently
            # expand a saved preset.
            selections = [
                {"courseType": course_type, "itemIds": list(item_ids_by_type.get(course_type, []))}
                for course_type in course_types
            ]
        item = {
            key: copy.deepcopy(value)
            for key, value in raw.items()
            if key not in {"courseIds", "courseTypes", "courseSelections", "mode"}
        }
        item["mode"] = mode
        item["courseSelections"] = selections
        migrated.append(item)

    if version == 3:
        raw_defaults = document.get("defaultPresetIds")
        if not isinstance(raw_defaults, dict):
            raise ValueError("invalid_course_preset_document")
        defaults = {
            "assessment": raw_defaults.get("assessment"),
            "intervention": raw_defaults.get("intervention"),
        }
    else:
        defaults = {
            "assessment": document.get("defaultPresetId"),
            "intervention": None,
        }
    for mode in ("assessment", "intervention"):
        candidates = [preset["id"] for preset in migrated if preset["mode"] == mode]
        if defaults[mode] not in candidates:
            defaults[mode] = candidates[0] if candidates else None
    return {
        "schemaVersion": 3,
        "defaultPresetIds": defaults,
        "presets": migrated,
    }


def ensure_canonical_course_catalog(
    *,
    preset_path: Path,
    course_map_path: Path,
) -> dict[str, Any]:
    """Merge duplicate Course rows by CourseType and migrate their external IDs.

    The operation is idempotent. JSON documents are atomically replaced before
    the database commit; a failure restores their previous values and rolls the
    database transaction back.
    """
    preset_path = Path(preset_path)
    course_map_path = Path(course_map_path)
    presets_before = _read_json(
        preset_path,
        default={
            "schemaVersion": 3,
            "defaultPresetIds": {"assessment": None, "intervention": None},
            "presets": [],
        },
    )
    mapping_before = _read_json(
        course_map_path,
        default={"defaults": {}, "courses": {}, "students": {}},
    )

    course_id_to_type: dict[int, str] = {}
    course_aliases: dict[int, int] = {}
    item_aliases: dict[tuple[int, int], int] = {}
    removed_courses: list[int] = []

    try:
        for course_type in CourseType.query.order_by(CourseType.id).all():
            type_key = TYPE_CN_TO_EN.get(str(course_type.name or "").strip())
            if not type_key:
                continue
            courses = list(Course.query.filter_by(course_type_id=course_type.id).order_by(Course.id).all())
            for course in courses:
                course_id_to_type[int(course.id)] = type_key
            if not courses:
                continue

            canonical = max(courses, key=_course_rank)
            canonical.title = str(course_type.name).strip()
            targets = list(canonical.items or [])
            for source in courses:
                if source.id == canonical.id:
                    continue
                course_aliases[int(source.id)] = int(canonical.id)
                for field in ("icon", "question_audio", "praise_audio", "entry_file"):
                    if not getattr(canonical, field, None) and getattr(source, field, None):
                        setattr(canonical, field, getattr(source, field))
                for item in list(source.items or []):
                    target = _find_same_item(targets, item)
                    if target is None:
                        item.course = canonical
                        targets.append(item)
                        item_aliases[(int(source.id), int(item.id))] = int(item.id)
                    else:
                        _fill_missing_item_fields(target, item)
                        item_aliases[(int(source.id), int(item.id))] = int(target.id)
                        # The duplicate remains owned by the legacy course and is
                        # removed by that course's delete-orphan cascade below.
                        # Deleting it explicitly as well makes SQLAlchemy issue a
                        # second DELETE when the parent is removed.
                db.session.flush()
                db.session.delete(source)
                removed_courses.append(int(source.id))

        # Enforce the invariant below every route/importer as well. Existing
        # SQLite deployments need explicit in-place DDL because create_all()
        # cannot add an index to an already-created table.
        db.session.flush()
        db.session.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_course_course_type "
            "ON course(course_type_id)"
        ))

        item_ids_by_type: dict[str, list[int]] = {}
        for course in Course.query.order_by(Course.id).all():
            if not course.course_type:
                continue
            course_type = TYPE_CN_TO_EN.get(str(course.course_type.name or "").strip())
            if course_type:
                item_ids_by_type[course_type] = sorted(int(item.id) for item in (course.items or []))
        item_id_aliases = {
            old_item_id: target_id
            for (_, old_item_id), target_id in item_aliases.items()
        }
        presets_after = _migrate_presets(
            presets_before,
            course_id_to_type,
            item_ids_by_type,
            item_id_aliases,
        )
        mapping_after = _migrate_course_map(mapping_before, course_aliases, item_aliases)
        atomic_write_json(preset_path, presets_after)
        atomic_write_json(course_map_path, mapping_after)
        db.session.commit()
    except Exception:
        db.session.rollback()
        atomic_write_json(preset_path, presets_before)
        atomic_write_json(course_map_path, mapping_before)
        raise

    return {
        "removedCourseIds": sorted(removed_courses),
        "courseAliases": {str(key): value for key, value in sorted(course_aliases.items())},
        "itemAliases": {
            f"{course_id}:{item_id}": target_id
            for (course_id, item_id), target_id in sorted(item_aliases.items())
        },
        "schemaVersion": 3,
    }


__all__ = ["TYPE_CN_TO_EN", "ensure_canonical_course_catalog"]
