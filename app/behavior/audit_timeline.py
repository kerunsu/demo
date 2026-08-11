"""Persistent, server-ordered audit timeline for classroom interaction.

This is intentionally separate from ``timeline.csv`` (recording chapters) and
``interaction_timeline.jsonl`` (question state machine).  It records observable
commands and acknowledgements from every UI and robot modality without changing
either legacy contract.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import threading
import time
from typing import Any, Dict, Iterable, Mapping, Optional
import uuid

from app.config import BASE_DIR
from app.storage.process_lock import InterProcessMutex


SCHEMA_VERSION = "full-interaction-timeline-v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
_BINARY_KEYS = {
    "audiobase64", "audio_base64", "dataurl", "data_url", "frame",
    "videoframe", "video_frame", "blob", "bytes",
}
_SECRET_PARTS = ("token", "secret", "password", "authorization", "cookie", "api_key")
CSV_FIELDS = (
    "sequence", "eventId", "timestamp", "serverEpochMs", "serverMonotonicMs",
    "trainingSessionId", "sessionId", "questionId", "requestId", "behaviorId",
    "actor", "source", "category", "event", "phase", "status", "modality",
    "clientTimestamp", "clockOffsetMs", "degraded", "error", "details",
)


def _safe_id(value: Any, *, fallback: Optional[str] = None) -> Optional[str]:
    text = str(value or "").strip()
    if text and _SAFE_ID.fullmatch(text):
        return text
    return fallback


def _summarize_binary(value: Any) -> Dict[str, Any]:
    if isinstance(value, str):
        raw = value.encode("utf-8", errors="replace")
    elif isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
    else:
        raw = repr(value).encode("utf-8", errors="replace")
    return {"omitted": True, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def sanitize_details(value: Any, *, key: str = "", depth: int = 0) -> Any:
    """Bound audit payload size and never persist credentials or raw media."""
    lowered = key.lower()
    if lowered in _BINARY_KEYS:
        return _summarize_binary(value)
    if any(part in lowered for part in _SECRET_PARTS):
        return "[redacted]"
    if depth >= 6:
        return "[max-depth]"
    if isinstance(value, Mapping):
        return {
            str(k)[:100]: sanitize_details(v, key=str(k), depth=depth + 1)
            for k, v in list(value.items())[:100]
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_details(v, depth=depth + 1) for v in list(value)[:100]]
    if isinstance(value, str):
        return value if len(value) <= 2000 else value[:2000] + "…[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:2000]


class FullInteractionTimeline:
    def __init__(
        self,
        root: Optional[Path] = None,
        *,
        recording_root: Optional[Path] = None,
    ):
        # An explicit ``root`` keeps the small direct layout used by unit tests.
        # Production resolves the human-readable per-course recording folder.
        self._direct_layout = root is not None and recording_root is None
        self._allow_runtime_registry = root is None and recording_root is None
        self.root = Path(
            root
            if self._direct_layout
            else recording_root or (BASE_DIR / "static" / "recordings" / "sessions")
        )
        self._lock = threading.RLock()
        self._sequences: Dict[str, int] = {}
        self._resolved_paths: Dict[str, Path] = {}
        self._process_lock = InterProcessMutex(self.root / ".full_timeline.lock")

    def _path(self, training_session_id: str) -> Optional[Path]:
        safe = _safe_id(training_session_id)
        if not safe:
            raise ValueError("invalid_training_session_id")
        if self._direct_layout:
            return self.root / safe / "full_interaction_timeline.jsonl"
        cached = self._resolved_paths.get(safe)
        if cached is not None:
            return cached / "full_interaction_timeline.jsonl"
        if self._allow_runtime_registry:
            try:
                from app.services.recording_timeline import get_recording_session_by_training
                recording = get_recording_session_by_training(safe)
                if recording is not None:
                    directory = Path(recording.dir_path)
                    self._resolved_paths[safe] = directory
                    return directory / "full_interaction_timeline.jsonl"
            except Exception:
                pass
        # Completed sessions are no longer in the active registry. Resolve the
        # same folder from its durable session_meta instead of creating a second
        # tree keyed by an internal UUID.
        if self.root.is_dir():
            for directory in self.root.iterdir():
                if not directory.is_dir():
                    continue
                meta_path = directory / "session_meta.json"
                if not meta_path.is_file():
                    continue
                try:
                    meta = json.loads(meta_path.read_text(encoding="utf-8"))
                except (OSError, ValueError, TypeError):
                    continue
                training_id = meta.get("trainingSessionId") or meta.get("training_session_id")
                if str(training_id or "") == safe:
                    self._resolved_paths[safe] = directory
                    return directory / "full_interaction_timeline.jsonl"
        return None

    @staticmethod
    def resolve_training_id(
        training_session_id: Any = None, runtime_session_id: Any = None
    ) -> Optional[str]:
        explicit = _safe_id(training_session_id)
        if explicit:
            return explicit
        runtime_id = _safe_id(runtime_session_id)
        if not runtime_id:
            return None
        try:
            from app.session import get_session_manager
            runtime = get_session_manager().get_session(runtime_id)
            return _safe_id(getattr(runtime, "training_session_id", None)) if runtime else None
        except Exception:
            return None

    def _next_sequence(self, training_id: str, path: Path) -> int:
        current = self._sequences.get(training_id, 0)
        if path.is_file():
            try:
                disk_sequence = 0
                # Read only the tail. Timeline size must not make a live robot
                # status update progressively slower during a long class.
                with path.open("rb") as stream:
                    stream.seek(0, 2)
                    end = stream.tell()
                    stream.seek(max(0, end - 65536))
                    tail = stream.read().decode("utf-8", errors="ignore")
                for line in reversed(tail.splitlines()):
                    if not line.strip():
                        continue
                    try:
                        disk_sequence = int(json.loads(line).get("sequence") or 0)
                        break
                    except (ValueError, TypeError, AttributeError):
                        continue
                current = max(current, disk_sequence)
            except OSError:
                pass
        current += 1
        self._sequences[training_id] = current
        return current

    def record(
        self,
        event: str,
        *,
        training_session_id: Any = None,
        runtime_session_id: Any = None,
        question_id: Any = None,
        request_id: Any = None,
        behavior_id: Any = None,
        actor: str = "server",
        source: str = "server",
        category: str = "system",
        phase: Optional[str] = None,
        status: Optional[str] = None,
        modality: Optional[str] = None,
        client_timestamp: Any = None,
        degraded: bool = False,
        error: Any = None,
        details: Any = None,
    ) -> Optional[Dict[str, Any]]:
        training_id = self.resolve_training_id(training_session_id, runtime_session_id)
        if not training_id:
            return None
        epoch_ns = time.time_ns()
        monotonic_ns = time.monotonic_ns()
        client_ms = None
        try:
            client_ms = float(client_timestamp) if client_timestamp is not None else None
        except (TypeError, ValueError):
            client_ms = None
        path = self._path(training_id)
        if path is None:
            return None
        with self._lock, self._process_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            item = {
                "schemaVersion": SCHEMA_VERSION,
                "sequence": self._next_sequence(training_id, path),
                "eventId": str(uuid.uuid4()),
                "timestamp": datetime.fromtimestamp(
                    epoch_ns / 1_000_000_000, tz=timezone.utc
                ).isoformat().replace("+00:00", "Z"),
                "serverEpochMs": epoch_ns / 1_000_000,
                "serverMonotonicMs": monotonic_ns / 1_000_000,
                "trainingSessionId": training_id,
                "sessionId": _safe_id(runtime_session_id),
                "questionId": _safe_id(question_id),
                "requestId": _safe_id(request_id),
                "behaviorId": _safe_id(behavior_id),
                "actor": str(actor or "server")[:80],
                "source": str(source or "server")[:80],
                "category": str(category or "system")[:80],
                "event": str(event or "unknown")[:160],
                "phase": str(phase)[:80] if phase is not None else None,
                "status": str(status)[:80] if status is not None else None,
                "modality": str(modality)[:80] if modality is not None else None,
                "clientTimestamp": client_timestamp,
                "clockOffsetMs": (
                    epoch_ns / 1_000_000 - client_ms if client_ms is not None else None
                ),
                "degraded": bool(degraded),
                "error": str(error)[:2000] if error else None,
                "details": sanitize_details(details or {}),
            }
            with path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n")
                stream.flush()
            return item

    def read(self, training_session_id: str) -> list[Dict[str, Any]]:
        path = self._path(training_session_id)
        if path is None or not path.is_file():
            return []
        rows = []
        with self._lock, path.open("r", encoding="utf-8") as stream:
            for line in stream:
                try:
                    value = json.loads(line)
                    if isinstance(value, dict):
                        rows.append(value)
                except (ValueError, TypeError):
                    continue
        return rows

    def export_csv(self, training_session_id: str) -> str:
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for item in self.read(training_session_id):
            row = dict(item)
            row["details"] = json.dumps(row.get("details") or {}, ensure_ascii=False)
            writer.writerow(row)
        return output.getvalue()


_timeline: Optional[FullInteractionTimeline] = None
_timeline_lock = threading.Lock()


def get_full_interaction_timeline() -> FullInteractionTimeline:
    global _timeline
    with _timeline_lock:
        if _timeline is None:
            _timeline = FullInteractionTimeline()
        return _timeline


def record_audit_event(event: str, **kwargs: Any) -> Optional[Dict[str, Any]]:
    return get_full_interaction_timeline().record(event, **kwargs)
