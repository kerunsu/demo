"""Read-only validation for legacy and extended session directories."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


LEGACY_FILES = {
    "child_video": "video.avi",
    "child_audio": "audio.wav",
    "environment_video": "video.environment.avi",
    "environment_audio": "audio.environment.wav",
    "timeline": "timeline.csv",
    "session_meta": "session_meta.json",
    "archive_meta": "archive_meta.json",
}


def _json_file(path: Path) -> tuple[Any, str | None]:
    if not path.exists():
        return None, None
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, str(exc)


def validate_session_directory(directory: Path) -> dict[str, Any]:
    """Inspect files without creating, changing or repairing anything."""

    root = Path(directory)
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "directory": str(root),
        "exists": root.is_dir(),
        "readOnly": True,
        "files": {},
        "legacyFiles": {},
        "tracks": [],
        "errors": [],
        "warnings": [],
    }
    if not root.is_dir():
        result["errors"].append("session directory does not exist")
        result["status"] = "invalid"
        return result
    for key, filename in LEGACY_FILES.items():
        present = (root / filename).is_file()
        result["legacyFiles"][key] = {"filename": filename, "present": present}
        result["files"][filename] = present
    for path in sorted(root.iterdir()):
        if path.is_file() and path.name not in result["files"]:
            result["files"][path.name] = True
            if path.name.startswith(("video.environment.", "audio.environment.")):
                result["tracks"].append({"filename": path.name, "kind": "video" if path.name.startswith("video") else "audio"})
    meta, error = _json_file(root / "session_meta.json")
    if error:
        result["errors"].append(f"session_meta.json: {error}")
    if isinstance(meta, dict):
        result["sessionMeta"] = meta
        metadata_tracks = meta.get("tracks", [])
        if metadata_tracks is None:
            metadata_tracks = []
        if not isinstance(metadata_tracks, list):
            result["errors"].append("session_meta.json tracks must be an array")
        else:
            seen_track_ids = set()
            seen_filenames = set()
            for index, track in enumerate(metadata_tracks):
                if not isinstance(track, dict):
                    result["errors"].append(f"session_meta.json tracks[{index}] must be an object")
                    continue
                track_id = str(track.get("trackId") or "")
                filename = str(track.get("filename") or "")
                if not track_id:
                    result["errors"].append(f"session_meta.json tracks[{index}] missing trackId")
                elif track_id in seen_track_ids:
                    result["errors"].append(f"duplicate trackId: {track_id}")
                else:
                    seen_track_ids.add(track_id)
                if filename:
                    if Path(filename).name != filename:
                        result["errors"].append(f"unsafe track filename: {filename}")
                    elif filename in seen_filenames:
                        result["errors"].append(f"duplicate track filename: {filename}")
                    else:
                        seen_filenames.add(filename)
                result["tracks"].append(track)
    timeline = root / "timeline.csv"
    if timeline.is_file():
        try:
            with timeline.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
                required_columns = {"seg_index", "seg_kind", "t_start_sec", "t_end_sec"}
                missing_columns = sorted(required_columns - set(reader.fieldnames or ()))
                if missing_columns:
                    result["errors"].append("timeline.csv missing columns: " + ", ".join(missing_columns))
            result["timelineRows"] = len(rows)
            previous = None
            previous_end = None
            for row in rows:
                raw = row.get("t_start_sec", "")
                if raw in (None, ""):
                    continue
                current = float(raw)
                if previous is not None and current < previous:
                    result["errors"].append("timeline.csv timestamps are not monotonic")
                    break
                end_raw = row.get("t_end_sec", "")
                end = None if end_raw in (None, "") else float(end_raw)
                if end is not None and end < current:
                    result["errors"].append("timeline.csv segment end precedes start")
                    break
                if previous_end is not None and current < previous_end:
                    result["errors"].append("timeline.csv segments overlap")
                    break
                previous = current
                previous_end = end
        except (OSError, ValueError) as exc:
            result["errors"].append(f"timeline.csv: {exc}")
    result["status"] = "valid" if not result["errors"] else "invalid"
    return result


__all__ = ["validate_session_directory", "LEGACY_FILES"]
