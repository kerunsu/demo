"""CSV timeline repository with monotonic and atomic write guarantees."""

from __future__ import annotations

import csv
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Mapping, Optional

from app.contracts.models import SessionRef
from app.storage.session_layout import SessionLayout


TIMELINE_COLUMNS = [
    "seg_index", "seg_kind", "course_type_id", "course_item_id", "course_id",
    "question_id", "t_start_sec", "t_end_sec", "t_start_hms", "t_end_hms",
    "wall_start_iso", "wall_end_iso",
]


def _hms(value: Optional[float]) -> str:
    if value is None:
        return ""
    total = max(0, int(round(float(value))))
    hour, remainder = divmod(total, 3600)
    minute, second = divmod(remainder, 60)
    return f"{hour}:{minute:02d}:{second:02d}" if hour else f"{minute}:{second:02d}"


class FileTimelineRepository:
    def __init__(self, layout: SessionLayout):
        self.layout = layout
        self._lock = threading.RLock()
        self._last_start: dict[str, float] = {}

    def _path(self, session: SessionRef) -> Path:
        directory = self.layout.resolve(session)
        if directory is None:
            raise KeyError("session is not bound to a session directory")
        return directory / "timeline.csv"

    @staticmethod
    def _key(session: SessionRef) -> str:
        key = session.media_session_id or session.session_id or session.training_session_id
        if not key:
            raise ValueError("session_identity_required")
        return str(key)

    def append(self, session: SessionRef, entry: Mapping[str, Any]) -> None:
        with self._lock:
            path = self._path(session)
            start = float(entry.get("t_start_sec", 0.0))
            key = self._key(session)
            rows = self.read(session)
            previous = self._last_start.get(key)
            if previous is None and path.exists():
                if rows:
                    previous = float(rows[-1].get("t_start_sec") or 0.0)
            if previous is not None and start < previous:
                raise ValueError("timeline timestamps must be monotonic")
            row = {column: entry.get(column, "") for column in TIMELINE_COLUMNS}
            row["seg_index"] = entry.get("seg_index", len(self.read(session)))
            row["t_start_sec"] = f"{start:.3f}"
            end = entry.get("t_end_sec")
            if end not in (None, "") and float(end) < start:
                raise ValueError("timeline segment end precedes start")
            row["t_end_sec"] = "" if end in (None, "") else f"{float(end):.3f}"
            row["t_start_hms"] = entry.get("t_start_hms") or _hms(start)
            row["t_end_hms"] = entry.get("t_end_hms") or _hms(None if end in (None, "") else float(end))
            if rows and rows[-1].get("t_end_sec", "") == "":
                rows[-1]["t_end_sec"] = f"{start:.3f}"
                rows[-1]["t_end_hms"] = _hms(start)
                rows[-1]["wall_end_iso"] = entry.get("wall_start_iso") or rows[-1].get("wall_end_iso", "")
            self._write_rows(path, rows + [row])
            self._last_start[key] = start

    def read(self, session: SessionRef) -> list[dict[str, str]]:
        path = self._path(session)
        if not path.exists():
            return []
        with path.open("r", newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def finalize(self, session: SessionRef, end_relative_seconds: float) -> None:
        with self._lock:
            path = self._path(session)
            rows = self.read(session)
            if rows:
                last = rows[-1]
                if last.get("t_end_sec", "") == "":
                    end = float(end_relative_seconds)
                    start = float(last.get("t_start_sec") or 0.0)
                    if end < start:
                        raise ValueError("timeline finalization precedes last segment")
                    last["t_end_sec"] = f"{end:.3f}"
                    last["t_end_hms"] = _hms(end)
                    self._write_rows(path, rows)

    @staticmethod
    def _write_rows(path: Path, rows: list[Mapping[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=TIMELINE_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass
            raise


__all__ = ["FileTimelineRepository", "TIMELINE_COLUMNS"]
