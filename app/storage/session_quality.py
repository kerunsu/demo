"""Read-only session health inspection for the control plane.

This module deliberately does not call ``Config.get_recording_path`` because
that legacy helper creates a directory when it cannot resolve a live session.
The quality view must be safe to use for old, finalized sessions and for a
non-existent session id.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path
from typing import Any, Mapping

from app.storage.session_validator import LEGACY_FILES, validate_session_directory


def _file_info(root: Path, filename: str, *, include_hash: bool) -> dict[str, Any]:
    path = root / filename
    info: dict[str, Any] = {
        "filename": filename,
        "present": path.is_file(),
        "sizeBytes": 0,
    }
    if not path.is_file():
        return info
    try:
        info["sizeBytes"] = path.stat().st_size
        if include_hash:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            info["sha256"] = digest.hexdigest()
    except OSError as exc:
        info["readError"] = str(exc)
    return info


def _track_quality(track: Mapping[str, Any]) -> dict[str, Any]:
    """Copy only stable, observable quality fields from a track manifest."""

    allowed = (
        "trackId", "kind", "role", "deviceId", "runtimeId", "required",
        "filename", "format", "clockDomain", "offsetMs", "offsetSec",
        "firstSampleAt", "firstFrameAt", "firstChunkAt", "frameCount",
        "chunkCount", "droppedFrames", "droppedChunks", "quality",
        "degradationReasons", "status",
    )
    return {key: track[key] for key in allowed if key in track}


def inspect_session_directory(directory: Path, *, include_hash: bool = False) -> dict[str, Any]:
    """Return a non-mutating, JSON-serializable health summary.

    No repair, directory creation, lock acquisition, or media decoding occurs.
    Fields such as drop counters and clock offsets are reported only when the
    capture writer has recorded them; this inspector never invents values.
    """

    root = Path(directory)
    report = validate_session_directory(root)
    if not root.is_dir():
        report["storage"] = {"exists": False, "totalBytes": 0, "writable": False}
        return report

    filenames = set(LEGACY_FILES.values())
    filenames.update(path.name for path in root.iterdir() if path.is_file())
    files = {
        name: _file_info(root, name, include_hash=include_hash)
        for name in sorted(filenames)
    }
    total_bytes = sum(int(value.get("sizeBytes") or 0) for value in files.values())

    reasons: list[str] = []
    meta = report.get("sessionMeta")
    if isinstance(meta, dict):
        raw_reasons = meta.get("degradationReasons") or meta.get("degradation_reasons") or []
        if isinstance(raw_reasons, (list, tuple)):
            reasons.extend(str(item) for item in raw_reasons if item)
        elif raw_reasons:
            reasons.append(str(raw_reasons))

    tracks: list[dict[str, Any]] = []
    by_identity: dict[tuple[str, str], int] = {}
    for raw_track in report.get("tracks", []):
        if not isinstance(raw_track, dict):
            continue
        track = _track_quality(raw_track)
        track_id = str(track.get("trackId") or "")
        filename = str(track.get("filename") or "")
        key = (track_id, filename)
        matching_index = by_identity.get(key)
        if matching_index is None and filename:
            matching_index = next(
                (index for index, item in enumerate(tracks) if item.get("filename") == filename),
                None,
            )
        if matching_index is not None:
            tracks[matching_index].update(track)
        else:
            matching_index = len(tracks)
            tracks.append(track)
        if track_id or filename:
            by_identity[key] = matching_index
        track_reasons = track.get("degradationReasons") or []
        if isinstance(track_reasons, (list, tuple)):
            reasons.extend(str(item) for item in track_reasons if item)

    try:
        usage = shutil.disk_usage(root)
        free_bytes = usage.free
    except OSError:
        free_bytes = None

    report["files"] = files
    report["tracks"] = tracks
    report["storage"] = {
        "exists": True,
        "totalBytes": total_bytes,
        "freeBytes": free_bytes,
        "writable": bool(os.access(root, os.W_OK)),
        "readOnlyInspection": True,
    }
    report["quality"] = {
        "timelineRows": int(report.get("timelineRows") or 0),
        "durationSec": (meta or {}).get("durationSec") if isinstance(meta, dict) else None,
        "degradationReasons": sorted(set(reasons)),
    }
    return report


__all__ = ["inspect_session_directory"]
