"""Stable session layout primitives.

This module is deliberately unaware of Flask, SQLAlchemy and recording
implementations.  It describes names and locations only; legacy recording
code remains the owner of the current write path until a later migration.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from pathlib import Path
from typing import Any, Mapping, Optional

from app.contracts.models import SessionRef, TrackRef


_SAFE_TRACK = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_track_id(value: str) -> str:
    cleaned = _SAFE_TRACK.sub("_", str(value or "track"))
    cleaned = cleaned.strip("._")
    return cleaned or "track"


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    """Replace a JSON file atomically in the same directory."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            Path(temporary).unlink(missing_ok=True)
        except OSError:
            pass
        raise


class SessionLayout:
    """Resolve the historical and extended files of one session.

    ``video.avi``/``audio.wav`` and the first environment pair are reserved
    compatibility names.  Additional environment tracks are disambiguated
    by their stable track id and never by device-array position.
    """

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self._session_dirs: dict[str, Path] = {}
        self._lock = threading.RLock()

    def _validate_dir_name(self, name: str) -> str:
        value = str(name or "").strip()
        if not value or value in {".", ".."} or Path(value).name != value:
            raise ValueError("human_dir_name must be a single relative directory name")
        return value

    def session_dir(self, human_dir_name: str) -> Path:
        value = self._validate_dir_name(human_dir_name)
        return self.root / value

    def reserve(self, human_dir_name: str) -> Path:
        path = self.session_dir(human_dir_name)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def bind(self, session: SessionRef, human_dir_name: str) -> Path:
        path = self.reserve(human_dir_name)
        with self._lock:
            for key in (session.session_id, session.training_session_id, session.media_session_id):
                if key:
                    existing = self._session_dirs.get(str(key))
                    if existing is not None and existing != path:
                        raise ValueError(f"session_identity_already_bound:{key}")
                    self._session_dirs[str(key)] = path
        return path

    def resolve(self, session: SessionRef) -> Optional[Path]:
        with self._lock:
            for key in (session.media_session_id, session.session_id, session.training_session_id):
                if key and str(key) in self._session_dirs:
                    return self._session_dirs[str(key)]
        return None

    def track_filename(self, track: TrackRef) -> str:
        if track.filename:
            filename = Path(track.filename).name
            if filename != track.filename:
                raise ValueError("track filename must not contain a directory")
            return filename
        kind = str(track.kind).lower()
        role = str(track.role).lower()
        is_environment = "environment" in role or role in {"ambient", "space"}
        if kind.startswith("video"):
            if is_environment:
                if role in {"primary_environment", "environment_primary", "ambient_primary"}:
                    return "video.environment.avi"
                return f"video.environment.{_safe_track_id(track.track_id)}.avi"
            return "video.avi"
        if kind.startswith("audio"):
            if is_environment:
                if role in {"primary_environment", "environment_primary", "ambient_primary"}:
                    return "audio.environment.wav"
                return f"audio.environment.{_safe_track_id(track.track_id)}.wav"
            return "audio.wav"
        return f"{_safe_track_id(kind)}.{_safe_track_id(track.track_id)}"

    def manifest_entry(self, track: TrackRef) -> dict[str, Any]:
        return {
            "trackId": track.track_id,
            "kind": track.kind,
            "role": track.role,
            "deviceId": track.device_id,
            "runtimeId": track.runtime_id,
            "required": bool(track.required),
            "filename": self.track_filename(track),
            "format": track.format,
            "clockDomain": track.clock_domain,
        }


def default_session_layout() -> SessionLayout:
    """Build the default layout lazily to avoid import-time filesystem work."""

    from app.config import Config

    return SessionLayout(Path(Config.RECORDINGS_DIR) / "sessions")


__all__ = ["SessionLayout", "atomic_write_json", "default_session_layout"]
