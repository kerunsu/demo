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


def _number_for_sort(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


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
        # A training can be retried into more than one media folder.  Cache an
        # exact media binding only; caching by training id alone makes every
        # later retry append to the first folder that happened to be resolved.
        self._resolved_paths: Dict[tuple[str, str], Path] = {}
        self._process_lock = InterProcessMutex(self.root / ".full_timeline.lock")

    def _path(
        self,
        training_session_id: str,
        runtime_session_id: Any = None,
    ) -> Optional[Path]:
        safe = _safe_id(training_session_id)
        if not safe:
            raise ValueError("invalid_training_session_id")
        runtime_safe = _safe_id(runtime_session_id)
        if runtime_session_id not in (None, "") and not runtime_safe:
            raise ValueError("invalid_runtime_session_id")
        if self._direct_layout:
            return self.root / safe / "full_interaction_timeline.jsonl"
        cache_key = (safe, runtime_safe or "")
        cached = self._resolved_paths.get(cache_key) if runtime_safe else None
        if cached is not None:
            return cached / "full_interaction_timeline.jsonl"
        if self._allow_runtime_registry:
            try:
                from app.services.recording_timeline import (
                    get_recording_session,
                    get_recording_session_by_training,
                )
                recording = (
                    get_recording_session(runtime_safe)
                    if runtime_safe
                    else get_recording_session_by_training(safe)
                )
                if recording is not None:
                    if str(recording.training_session_id or "") != safe:
                        return None
                    directory = Path(recording.dir_path)
                    if runtime_safe:
                        self._resolved_paths[cache_key] = directory
                    return directory / "full_interaction_timeline.jsonl"
            except Exception:
                pass
        # Completed sessions are no longer in the active registry. Resolve the
        # same folder from its durable session_meta instead of creating a second
        # tree keyed by an internal UUID.
        matches: list[tuple[float, Path]] = []
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
                media_id = meta.get("mediaSessionId") or meta.get("sessionId")
                if str(training_id or "") != safe:
                    continue
                if runtime_safe and str(media_id or "") != runtime_safe:
                    continue
                started = meta.get("recordingStartedAtUnix")
                try:
                    order = float(started)
                except (TypeError, ValueError):
                    try:
                        order = float(meta_path.stat().st_mtime)
                    except OSError:
                        order = 0.0
                matches.append((order, directory))
        if matches:
            # An unqualified legacy query resolves the latest media attempt;
            # exact runtime queries remain stable and cacheable.
            directory = max(matches, key=lambda item: item[0])[1]
            if runtime_safe:
                self._resolved_paths[cache_key] = directory
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

    def _next_sequence(self, path: Path) -> int:
        sequence_key = str(path.resolve())
        current = self._sequences.get(sequence_key, 0)
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
        self._sequences[sequence_key] = current
        return current

    def _media_id_for_path(self, path: Path) -> Optional[str]:
        """Resolve the durable media id for an already selected audit file."""
        if self._direct_layout:
            return None
        meta_path = path.parent / "session_meta.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return None
        return _safe_id(meta.get("mediaSessionId") or meta.get("sessionId"))

    def _audit_paths_for_training(self, training_session_id: str) -> list[Path]:
        """Return durable audit files for legacy recovery, newest first."""
        safe = _safe_id(training_session_id)
        if not safe or self._direct_layout or not self.root.is_dir():
            return []
        matches: list[tuple[float, Path]] = []
        for directory in self.root.iterdir():
            if not directory.is_dir():
                continue
            meta_path = directory / "session_meta.json"
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                continue
            training_id = meta.get("trainingSessionId") or meta.get(
                "training_session_id"
            )
            if str(training_id or "") != safe:
                continue
            try:
                order = float(meta.get("recordingStartedAtUnix"))
            except (TypeError, ValueError):
                try:
                    order = float(meta_path.stat().st_mtime)
                except OSError:
                    order = 0.0
            matches.append(
                (order, directory / "full_interaction_timeline.jsonl")
            )
        return [path for _order, path in sorted(matches, reverse=True)]

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
        runtime_id = _safe_id(runtime_session_id)
        path = self._path(training_id, runtime_id)
        if path is None:
            return None
        # Several internal milestones historically carried only the training
        # id.  Once the recording folder has been selected, persist its durable
        # media id so an exact dashboard query neither drops the row nor mixes
        # it into a later retry of the same training id.
        runtime_id = runtime_id or self._media_id_for_path(path)
        with self._lock, self._process_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            item = {
                "schemaVersion": SCHEMA_VERSION,
                "sequence": self._next_sequence(path),
                "eventId": str(uuid.uuid4()),
                "timestamp": datetime.fromtimestamp(
                    epoch_ns / 1_000_000_000, tz=timezone.utc
                ).isoformat().replace("+00:00", "Z"),
                "serverEpochMs": epoch_ns / 1_000_000,
                "serverMonotonicMs": monotonic_ns / 1_000_000,
                "trainingSessionId": training_id,
                "sessionId": runtime_id,
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

    def read(
        self,
        training_session_id: str,
        runtime_session_id: Any = None,
    ) -> list[Dict[str, Any]]:
        runtime_id = _safe_id(runtime_session_id)
        path = self._path(training_session_id, runtime_id)
        if path is None:
            return []
        candidates = [path]
        if runtime_id:
            # Before media-scoped path caching, retries that reused a training
            # id could write into the first attempt's file. Recover only rows
            # whose persisted sessionId proves they belong to this exact media
            # session; never infer unlabelled rows from a different folder.
            candidates.extend(
                candidate
                for candidate in self._audit_paths_for_training(
                    training_session_id
                )
                if candidate != path
            )
        rows = []
        seen: set[str] = set()
        with self._lock:
            for candidate in candidates:
                if not candidate.is_file():
                    continue
                with candidate.open("r", encoding="utf-8") as stream:
                    for line in stream:
                        try:
                            value = json.loads(line)
                        except (ValueError, TypeError):
                            continue
                        if not isinstance(value, dict):
                            continue
                        row_runtime_id = str(value.get("sessionId") or "")
                        belongs = (
                            not runtime_id
                            or row_runtime_id == runtime_id
                            or (candidate == path and not row_runtime_id)
                        )
                        if not belongs:
                            continue
                        event_id = str(value.get("eventId") or "")
                        dedupe_key = event_id or hashlib.sha256(
                            line.encode("utf-8", errors="replace")
                        ).hexdigest()
                        if dedupe_key in seen:
                            continue
                        seen.add(dedupe_key)
                        if candidate != path:
                            value["_legacyMisplacedAuditRow"] = True
                        rows.append(value)
        rows.sort(
            key=lambda item: (
                _number_for_sort(item.get("serverEpochMs")),
                int(item.get("sequence") or 0),
            )
        )
        return rows

    def export_csv(
        self,
        training_session_id: str,
        runtime_session_id: Any = None,
    ) -> str:
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for item in self.read(training_session_id, runtime_session_id):
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
