"""Authoritative robot neutral pose derived from the configured idle motion."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict

from app.robot.config import COURSE_MAP_FILE, MOTIONS_FILE


AXES = ("pitch", "yaw", "armL", "armR")
# Last-resort safety value.  The normal path reads the first frame of 空动作.
EMPTY_ACTION_FALLBACK: Dict[str, int] = {
    "pitch": 200,
    "yaw": 160,
    "armL": 320,
    "armR": 50,
}

_lock = threading.RLock()
_cache_key = None
_cached_pose: Dict[str, int] = dict(EMPTY_ACTION_FALLBACK)


def _mtime(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return -1


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _resolve_pose() -> Dict[str, int]:
    course_map = _read_json(Path(COURSE_MAP_FILE))
    idle_name = str((course_map.get("defaults") or {}).get("idle") or "空动作")
    document = _read_json(Path(MOTIONS_FILE))
    motions = document.get("motions") if isinstance(document.get("motions"), dict) else document
    frames = motions.get(idle_name) if isinstance(motions, dict) else None
    pose = {}
    if isinstance(frames, list) and frames and isinstance(frames[0], dict):
        candidate = frames[0].get("pose")
        pose = candidate if isinstance(candidate, dict) else {}
    resolved = dict(EMPTY_ACTION_FALLBACK)
    for axis in AXES:
        try:
            resolved[axis] = int(pose.get(axis, resolved[axis]))
        except (TypeError, ValueError):
            pass
    return resolved


def get_neutral_pose() -> Dict[str, int]:
    """Return a copy of the first pose of the configured idle/empty action."""
    global _cache_key, _cached_pose
    key = (_mtime(Path(COURSE_MAP_FILE)), _mtime(Path(MOTIONS_FILE)))
    with _lock:
        if key != _cache_key:
            _cached_pose = _resolve_pose()
            _cache_key = key
        return dict(_cached_pose)


def complete_pose(pose: Any) -> Dict[str, int]:
    """Fill incomplete input without ever falling back to a legacy midpoint."""
    source = pose if isinstance(pose, dict) else {}
    result = get_neutral_pose()
    for axis in AXES:
        try:
            result[axis] = int(source.get(axis, result[axis]))
        except (TypeError, ValueError):
            pass
    return result
