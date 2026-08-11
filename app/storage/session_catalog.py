"""Read-only catalog of recorded sessions for the server control console.

The catalog never creates or repairs session directories.  Existing flat,
human-readable directory names remain the on-disk compatibility contract;
the returned groups provide the child-oriented view needed by operators.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import Config
from app.storage.session_quality import inspect_session_directory


def sessions_root() -> Path:
    return Path(Config.RECORDINGS_DIR) / "sessions"


def _read_meta(directory: Path) -> dict[str, Any]:
    path = directory / "session_meta.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _student_index() -> dict[str, dict[str, Any]]:
    """Best-effort DB enrichment; old sessions remain visible without DB."""

    try:
        from database.models import Student

        return {
            str(student.id): {
                "id": student.id,
                "name": student.name,
                "age": student.age,
                "teacher": student.teacher,
            }
            for student in Student.query.all()
        }
    except Exception:
        return {}


def _session_time(meta: dict[str, Any], directory: Path) -> str | None:
    value = meta.get("recordingStartedAt") or meta.get("startedAt")
    if value:
        return str(value)
    try:
        return datetime.fromtimestamp(directory.stat().st_mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


def _active_recording_ids() -> set[str]:
    """Return process-local recorder truth without mutating persisted metadata."""

    try:
        from app.services.recording_timeline import list_active_recording_sessions

        return {
            str(session.media_session_id)
            for session in list_active_recording_sessions()
            if getattr(session, "status", None) == "recording"
        }
    except Exception:
        return set()


def build_session_catalog(*, limit: int = 200) -> dict[str, Any]:
    root = sessions_root()
    students = _student_index()
    active_recording_ids = _active_recording_ids()
    locked_state: dict[str, dict[str, Any]] = {}
    try:
        from app.services.recording_admin import get_locked_state

        locked_state = get_locked_state()
    except Exception:
        locked_state = {}
    directories = []
    if root.is_dir():
        directories = [path for path in root.iterdir() if path.is_dir()]
        directories.sort(
            key=lambda path: path.stat().st_mtime if path.exists() else 0,
            reverse=True,
        )

    sessions: list[dict[str, Any]] = []
    for directory in directories[: max(1, min(int(limit), 1000))]:
        meta = _read_meta(directory)
        quality = inspect_session_directory(directory)
        student_id = meta.get("studentId", meta.get("student_id"))
        student = students.get(str(student_id)) if student_id is not None else None
        if student is None:
            student = {
                "id": student_id,
                "name": meta.get("studentName") or meta.get("student_name") or "未关联儿童",
                "age": meta.get("studentAge") or meta.get("student_age"),
                "teacher": None,
            }
        files = [
            value
            for value in (quality.get("files") or {}).values()
            if isinstance(value, dict) and value.get("present")
        ]
        media_session_id = meta.get("mediaSessionId") or meta.get("media_session_id")
        persisted_status = meta.get("status") or quality.get("status") or "unknown"
        live_active = bool(media_session_id and str(media_session_id) in active_recording_ids)
        # A stale `recording` value is common after a crash/restart.  Exposing it
        # as current state makes operators believe hardware is still occupied.
        # Keep the durable value for audit, but derive the control-plane status
        # from the live in-memory recorder registry.
        status = (
            "recording"
            if live_active
            else "interrupted"
            if persisted_status == "recording"
            else persisted_status
        )
        degradation_reasons = list(
            (quality.get("quality") or {}).get("degradationReasons", [])
        )
        if persisted_status == "recording" and not live_active:
            degradation_reasons.append("stale_recording_metadata")
        sessions.append({
            "folderName": directory.name,
            "mediaSessionId": media_session_id,
            "trainingSessionId": meta.get("trainingSessionId") or meta.get("training_session_id"),
            "student": student,
            "status": status,
            "persistedStatus": persisted_status,
            "liveActive": live_active,
            "recordingStartedAt": _session_time(meta, directory),
            "durationSec": (quality.get("quality") or {}).get("durationSec"),
            "timelineRows": (quality.get("quality") or {}).get("timelineRows", 0),
            "totalBytes": (quality.get("storage") or {}).get("totalBytes", 0),
            "storageWritable": (quality.get("storage") or {}).get("writable", False),
            "health": quality.get("status") or "unknown",
            "degradationReasons": sorted(set(degradation_reasons)),
            "tracks": quality.get("tracks") or [],
            "files": files,
            "canReveal": True,
            "locked": bool((locked_state.get(directory.name) or {}).get("locked")),
        })

    grouped: dict[str, dict[str, Any]] = {}
    for item in sessions:
        student = item["student"]
        key = str(student.get("id") if student.get("id") is not None else student.get("name"))
        group = grouped.setdefault(key, {"student": student, "sessions": [], "totalBytes": 0})
        group["sessions"].append(item)
        group["totalBytes"] += int(item.get("totalBytes") or 0)

    return {
        "schemaVersion": 1,
        "storage": {
            "sessionsRootName": root.name,
            "exists": root.is_dir(),
            "sessionCount": len(sessions),
            "totalBytes": sum(int(item.get("totalBytes") or 0) for item in sessions),
            "layout": "flat-human-readable-child-prefix",
        },
        "sessions": sessions,
        "children": list(grouped.values()),
    }


def resolve_session_folder(folder_name: str) -> Path:
    """Resolve exactly one direct child; rejects traversal and nested paths."""

    name = str(folder_name or "").strip()
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError("invalid_session_folder")
    root = sessions_root().resolve()
    candidate = (root / name).resolve()
    if candidate.parent != root or not candidate.is_dir():
        raise FileNotFoundError("session_folder_not_found")
    return candidate


__all__ = ["build_session_catalog", "resolve_session_folder", "sessions_root"]
