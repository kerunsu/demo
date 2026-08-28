"""Encouragement animation library backed by repository-tracked MP4 files."""
from __future__ import annotations

import json
import os
import random
import re
import threading
from pathlib import Path
from typing import Any, Dict, List

from app.config import Config
from app.robot.config import COURSE_MAP_FILE, PRAISE_RANDOM_ANIMATION
from app.utils.logger import setup_logger
from app.robot.mp4_validation import inspect_mp4
from app.robot.video_optimizer import save_optimized_mp4
from app.storage.session_layout import atomic_write_json


logger = setup_logger("animation_assets")
_animation_lock = threading.RLock()
_playable_cache_key: tuple = ()
_playable_cache_names: List[str] = []
# Upload clients may send a local ``C:\\fakepath\\`` prefix and users may
# reasonably name assets in Chinese. The basename check below removes the
# client-side path; this pattern still rejects separators and control chars.
SAFE_ANIMATION_NAME = re.compile(r"^[^/\\\x00-\x1f\x7f]+\.mp4$", re.IGNORECASE)


def animations_dir() -> Path:
    return Path(Config.STATIC_DIR) / "resources" / "Animations"


def ensure_animations_dir() -> Path:
    path = animations_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_animation_files() -> List[str]:
    path = ensure_animations_dir()
    return sorted(
        (item.name for item in path.iterdir() if item.is_file() and item.suffix.lower() == ".mp4"),
        key=str.lower,
    )


def _animation_version(path: Path) -> str:
    """Return a cheap content-revision token for browser cache invalidation."""
    stat = path.stat()
    return f"{stat.st_mtime_ns:x}-{stat.st_size:x}"


def _animation_runtime_path(path: Path) -> str:
    return f"resources/Animations/{path.name}?v={_animation_version(path)}"


def _walk_animation_refs(node: Any, path: str, out: List[str], name: str) -> None:
    if isinstance(node, dict):
        animation = node.get("animation")
        if isinstance(animation, str) and os.path.basename(animation) == name:
            out.append(path or "root")
        animations = node.get("animations")
        if isinstance(animations, list):
            for index, value in enumerate(animations):
                if isinstance(value, str) and os.path.basename(value) == name:
                    out.append(
                        f"{path}.animations[{index}]" if path
                        else f"animations[{index}]"
                    )
        for key, value in node.items():
            if key not in {"animation", "animations"}:
                _walk_animation_refs(value, f"{path}.{key}" if path else str(key), out, name)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _walk_animation_refs(value, f"{path}[{index}]", out, name)


def find_animation_references(name: str) -> List[str]:
    try:
        course_map = json.loads(Path(COURSE_MAP_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    refs: List[str] = []
    _walk_animation_refs(course_map, "", refs, os.path.basename(name or ""))
    return refs


def get_animations_payload() -> Dict[str, Any]:
    global _playable_cache_key, _playable_cache_names
    items = []
    for name in list_animation_files():
        refs = find_animation_references(name)
        path = ensure_animations_dir() / name
        try:
            media = inspect_mp4(path.read_bytes())
        except (OSError, ValueError) as exc:
            media = {
                "validationStatus": "invalid",
                "validationWarnings": [str(exc)],
            }
        items.append({
            "name": name,
            "url": f"/static/{_animation_runtime_path(path)}",
            "version": _animation_version(path),
            "refCount": len(refs),
            "referencedBy": refs,
            **media,
        })
    signature = []
    directory = ensure_animations_dir()
    for item in items:
        try:
            stat = (directory / item["name"]).stat()
            signature.append((item["name"], stat.st_mtime_ns, stat.st_size))
        except OSError:
            signature.append((item["name"], 0, 0))
    with _animation_lock:
        _playable_cache_key = (str(directory.resolve()), tuple(signature))
        _playable_cache_names = [
            str(item["name"])
            for item in items
            if item.get("validationStatus") in {"compatible", "degraded"}
        ]
    return {"animations": [item["name"] for item in items], "items": items}


def _playable_animation_names() -> List[str]:
    """Return only assets that passed bounded MP4 inspection.

    Old repositories may contain placeholder files with an ``.mp4`` suffix.
    They stay visible in the library for repair/removal, but must never enter
    the runtime random pool where one bad draw makes encouragement disappear.
    """
    global _playable_cache_key, _playable_cache_names
    directory = ensure_animations_dir()
    names = list_animation_files()
    signature = []
    for name in names:
        try:
            stat = (directory / name).stat()
            signature.append((name, stat.st_mtime_ns, stat.st_size))
        except OSError:
            signature.append((name, 0, 0))
    cache_key = (str(directory.resolve()), tuple(signature))
    with _animation_lock:
        if cache_key == _playable_cache_key:
            return list(_playable_cache_names)
        playable: List[str] = []
        for name in names:
            try:
                media = inspect_mp4((directory / name).read_bytes())
            except (OSError, ValueError):
                continue
            if media.get("validationStatus") in {"compatible", "degraded"}:
                playable.append(name)
        _playable_cache_key = cache_key
        _playable_cache_names = playable
        return list(playable)


def save_uploaded_animation(
    filename: str,
    file_bytes: bytes,
    *,
    return_details: bool = False,
) -> str | Dict[str, Any]:
    raw_name = str(filename or "").replace("\\", "/")
    name = os.path.basename(raw_name)
    if not SAFE_ANIMATION_NAME.fullmatch(name):
        raise ValueError("Only a plain .mp4 filename is allowed")
    if not file_bytes:
        raise ValueError("Empty animation file")
    destination = ensure_animations_dir() / name
    if destination.exists():
        raise FileExistsError(f"Animation already exists: {name}")
    result = save_optimized_mp4(
        ensure_animations_dir(), name, file_bytes, kind="animation"
    )
    logger.info(
        "Uploaded encouragement animation: %s optimized=%s %s->%s bytes",
        name, result["optimized"], result["originalSizeBytes"], result["sizeBytes"],
    )
    return result if return_details else name


def _validate_animation_name(value: Any) -> str:
    name = str(value or "").strip()
    if not SAFE_ANIMATION_NAME.fullmatch(name):
        raise ValueError("Only a plain .mp4 filename is allowed")
    return name


def _rename_animation_refs(node: Any, old: str, new: str) -> int:
    changed = 0
    if isinstance(node, dict):
        if isinstance(node.get("animation"), str):
            current = node["animation"]
            if os.path.basename(current.replace("\\", "/")) == old:
                prefix = current[:len(current) - len(os.path.basename(current))]
                node["animation"] = prefix + new
                changed += 1
        if isinstance(node.get("animations"), list):
            for index, value in enumerate(node["animations"]):
                if not isinstance(value, str):
                    continue
                current_name = os.path.basename(value.replace("\\", "/"))
                if current_name == old:
                    prefix = value[:len(value) - len(current_name)]
                    node["animations"][index] = prefix + new
                    changed += 1
        for key, value in node.items():
            if key not in {"animation", "animations"}:
                changed += _rename_animation_refs(value, old, new)
    elif isinstance(node, list):
        for value in node:
            changed += _rename_animation_refs(value, old, new)
    return changed


def rename_animation_file(old_name: str, new_name: str) -> Dict[str, Any]:
    """Rename an animation and update every course binding atomically."""
    old = _validate_animation_name(old_name)
    new = _validate_animation_name(new_name)
    if old == new:
        return {"oldName": old, "newName": new, "referencesUpdated": 0}
    directory = ensure_animations_dir()
    source = directory / old
    destination = directory / new
    with _animation_lock:
        if not source.is_file():
            raise FileNotFoundError(f"Animation does not exist: {old}")
        if destination.exists():
            raise FileExistsError(f"Animation already exists: {new}")
        map_path = Path(COURSE_MAP_FILE)
        map_before = map_path.read_bytes() if map_path.is_file() else None
        course_map = {}
        changed = 0
        if map_before is not None:
            try:
                course_map = json.loads(map_before.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise ValueError(f"course_map_invalid: {exc}") from exc
            changed = _rename_animation_refs(course_map, old, new)
        os.replace(source, destination)
        try:
            if changed:
                atomic_write_json(map_path, course_map)
        except Exception:
            os.replace(destination, source)
            raise
    logger.info("Renamed encouragement animation: %s -> %s (%s references)", old, new, changed)
    return {"oldName": old, "newName": new, "referencesUpdated": changed}


def delete_animation_file(name: str, force: bool = False) -> None:
    safe_name = os.path.basename(name or "")
    if not SAFE_ANIMATION_NAME.fullmatch(safe_name) or safe_name != name:
        raise ValueError("Invalid animation filename")
    refs = find_animation_references(safe_name)
    if refs and not force:
        raise PermissionError(f"Animation is referenced by {len(refs)} binding(s)")
    path = ensure_animations_dir() / safe_name
    if not path.is_file():
        raise FileNotFoundError(f"Animation does not exist: {safe_name}")
    path.unlink()
    logger.info("Deleted encouragement animation: %s (force=%s)", safe_name, force)


def resolve_animation(
    selection: Any,
    *,
    random_pool: Any = None,
    allow_random_fallback: bool = True,
) -> str | None:
    """Resolve a fixed file, an explicit reviewed pool, or a legacy fallback."""
    raw_selection = str(selection or "").strip()
    explicit_random = raw_selection == PRAISE_RANDOM_ANIMATION
    configured = "" if explicit_random else os.path.basename(raw_selection)
    available = _playable_animation_names()
    if explicit_random:
        requested: List[str] = []
        if isinstance(random_pool, list):
            for raw_name in random_pool:
                name = os.path.basename(str(raw_name or "").strip())
                if name and name not in requested:
                    requested.append(name)
        if not requested:
            logger.warning("Random praise animation requires an explicit reviewed pool")
            return None
        eligible = [name for name in requested if name in available]
        missing = [name for name in requested if name not in available]
        if missing:
            logger.warning(
                "Configured praise animation pool contains missing/invalid files: %s",
                missing,
            )
        if not eligible:
            logger.warning("Configured praise animation pool has no playable files")
            return None
        selected = random.choice(eligible)
        return _animation_runtime_path(animations_dir() / selected)
    if configured:
        if configured in available:
            return _animation_runtime_path(animations_dir() / configured)
        logger.warning("Configured encouragement animation is missing or invalid: %s", configured)
        if not allow_random_fallback:
            return None
    if not allow_random_fallback:
        return None
    if not available:
        logger.warning("Encouragement animation library is empty: %s", animations_dir())
        return None
    selected = random.choice(available)
    return _animation_runtime_path(animations_dir() / selected)
