"""Atomic metadata repository for the session dataset."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Mapping, Optional

from app.contracts.models import SessionRef
from app.storage.session_layout import SessionLayout, atomic_write_json


class FileMetadataRepository:
    def __init__(self, layout: SessionLayout):
        self.layout = layout
        self._lock = threading.RLock()

    def _path(self, session: SessionRef, filename: str = "session_meta.json") -> Path:
        directory = self.layout.resolve(session)
        if directory is None:
            raise KeyError("session is not bound to a session directory")
        return directory / filename

    def read(self, session: SessionRef) -> Optional[dict[str, Any]]:
        with self._lock:
            path = self._path(session)
            if not path.exists():
                return None
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ValueError(f"invalid metadata: {path}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"invalid metadata object: {path}")
            return value

    def write(self, session: SessionRef, metadata: Mapping[str, Any]) -> None:
        with self._lock:
            atomic_write_json(self._path(session), dict(metadata))

    def merge(self, session: SessionRef, updates: Mapping[str, Any]) -> dict[str, Any]:
        with self._lock:
            current = self.read(session) or {}
            current.update(dict(updates))
            self.write(session, current)
            return current

    def write_archive_meta(self, session: SessionRef, metadata: Mapping[str, Any]) -> None:
        """Write archive metadata without changing the legacy filename."""

        with self._lock:
            atomic_write_json(self._path(session, "archive_meta.json"), dict(metadata))


__all__ = ["FileMetadataRepository"]
