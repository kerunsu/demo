"""Composition of layout, manifest metadata and timeline repositories."""

from __future__ import annotations

from datetime import datetime, timezone
import threading
import time
from typing import Any, Mapping, Sequence

from app.contracts.models import SessionRef, TrackRef
from app.contracts.ports import Clock
from app.storage.repositories.metadata_repository import FileMetadataRepository
from app.storage.repositories.timeline_repository import FileTimelineRepository
from app.storage.session_layout import SessionLayout


class FileRecordingRepository:
    """Repository boundary; media codecs remain behind CapturePort."""

    def __init__(self, layout: SessionLayout, *, clock: Clock | None = None):
        self.layout = layout
        self.metadata = FileMetadataRepository(layout)
        self.timeline = FileTimelineRepository(layout)
        self.clock = clock
        self._started_monotonic: dict[str, float] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _key(session: SessionRef) -> str:
        key = session.media_session_id or session.session_id or session.training_session_id
        if not key:
            raise ValueError("session_identity_required")
        return str(key)

    def _now(self) -> float:
        return self.clock.monotonic_seconds() if self.clock else time.monotonic()

    def begin(self, session: SessionRef, tracks: Sequence[TrackRef]) -> Mapping[str, Any]:
        with self._lock:
            key = self._key(session)
            current = self.metadata.read(session) or {}
            if current.get("recordingStatus") == "recording" and key in self._started_monotonic:
                return current
            filenames: dict[str, str] = {}
            manifest = []
            for track in tracks:
                filename = self.layout.track_filename(track)
                previous = filenames.setdefault(filename, track.track_id)
                if previous != track.track_id:
                    raise ValueError(f"duplicate_track_filename:{filename}")
                manifest.append(self.layout.manifest_entry(track))
            current.update({
                "schemaVersion": max(int(current.get("schemaVersion") or 1), 1),
                "tracks": manifest,
                "recordingStatus": "recording",
                "recordingStartedAtUtc": datetime.now(timezone.utc).isoformat(),
            })
            self.metadata.write(session, current)
            self._started_monotonic[key] = self._now()
            return current

    def append_timeline(self, session: SessionRef, entry: Mapping[str, Any]) -> None:
        self.timeline.append(session, entry)

    def finalize(self, session: SessionRef, status: str = "finalized") -> Mapping[str, Any]:
        with self._lock:
            key = self._key(session)
            rows = self.timeline.read(session)
            timeline_end = 0.0
            if rows:
                timeline_end = max(float(row.get("t_end_sec") or row.get("t_start_sec") or 0.0) for row in rows)
            started = self._started_monotonic.get(key)
            elapsed = max(0.0, self._now() - started) if started is not None else 0.0
            current = self.metadata.read(session) or {}
            end = max(timeline_end, elapsed, float(current.get("durationSec") or 0.0))
            self.timeline.finalize(session, end)
            current.update({"recordingStatus": status, "status": status, "durationSec": end})
            self.metadata.write(session, current)
            self._started_monotonic.pop(key, None)
            return current


__all__ = ["FileRecordingRepository"]
