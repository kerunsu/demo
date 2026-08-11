"""动作/表情库的 staging -> validate -> commit 批量导入。

这是资源库适配器，旧的单文件接口仍由原路由处理。默认冲突策略是 skip，
提交前不会修改动作、表情或 course_map；提交失败会回滚本次新写入。
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from app.config import Config
from app.robot.config import MOTIONS_FILE, ROBOT_DATA_DIR
from app.robot.motion_storage import (
    CURRENT_SCHEMA_VERSION,
    _is_dollser_motion_document,
    convert_dollser_motion_to_frames,
    extract_dollser_motion_metadata,
    load_document,
)
from app.storage.repositories.asset_index import JsonAssetIndex
from app.storage.session_layout import atomic_write_json
from app.robot.mp4_validation import inspect_mp4


_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_VALID_AXES = {"pitch", "yaw", "armL", "armR"}
ASSET_INDEX_FILE = os.path.join(ROBOT_DATA_DIR, "asset_index.json")


class BatchAssetImporter:
    def __init__(self, *, max_item_bytes: int = 20 * 1024 * 1024, max_total_bytes: int = 100 * 1024 * 1024, asset_index_path: Optional[str] = None) -> None:
        self.max_item_bytes = max_item_bytes
        self.max_total_bytes = max_total_bytes
        self._staging: Dict[str, Dict[str, Any]] = {}
        self._completed: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._asset_index = JsonAssetIndex(Path(asset_index_path or ASSET_INDEX_FILE))

    @staticmethod
    def _safe_filename(raw: str, kind: str) -> str:
        name = os.path.basename(str(raw or "").replace("\\", "/"))
        if not name or name != str(raw or "").replace("\\", "/") or not _SAFE_NAME.fullmatch(name):
            raise ValueError("unsafe_asset_filename")
        if kind == "motions" and not name.lower().endswith(".json"):
            raise ValueError("motion_asset_must_be_json")
        if kind == "emotions" and not name.lower().endswith(".mp4"):
            raise ValueError("emotion_asset_must_be_mp4")
        return name

    def _validate_one(self, kind: str, filename: str, content: bytes, mime_type: Optional[str] = None) -> Dict[str, Any]:
        name = self._safe_filename(filename, kind)
        if not content:
            raise ValueError("asset_empty")
        if len(content) > self.max_item_bytes:
            raise ValueError("asset_too_large")
        mime = str(mime_type or "").lower().split(";", 1)[0].strip()
        if mime and mime not in {"application/octet-stream", "application/json", "text/json", "video/mp4"}:
            raise ValueError("asset_mime_invalid")
        checksum = hashlib.sha256(content).hexdigest()
        result: Dict[str, Any] = {
            "filename": name,
            "checksum": checksum,
            "assetId": f"{kind}:{checksum[:24]}",
            "version": checksum[:12],
            "kind": kind,
            "sizeBytes": len(content),
            "status": "ready",
        }
        if kind == "emotions":
            media_info = inspect_mp4(content, max_bytes=self.max_item_bytes)
            result.update({
                "sourceFormat": "mp4",
                "compatibility": "single-play-video",
                **media_info,
            })
        else:
            try:
                raw = json.loads(content.decode("utf-8"))
            except Exception as exc:
                raise ValueError(f"motion_invalid_json:{exc}") from exc
            if not _is_dollser_motion_document(raw):
                raise ValueError("motion_not_dollser_v2")
            for command in raw.get("commands", []):
                if not isinstance(command, dict) or command.get("axis") not in _VALID_AXES:
                    raise ValueError("motion_axis_invalid")
                angle = command.get("angle")
                if not isinstance(angle, (int, float)) or not 0 <= angle <= 360:
                    raise ValueError("motion_angle_out_of_range")
                for field in ("time", "moveMs"):
                    value = command.get(field, 0 if field == "time" else 100)
                    if not isinstance(value, (int, float)) or value < 0:
                        raise ValueError("motion_timing_invalid")
            result.update({
                "sourceFormat": "dollser-motion",
                "compatibility": "legacy-motion-storage-v2",
                "durationMs": int(raw.get("durationMs") or 0),
            })
        return result

    def expand_zip(self, kind: str, content: bytes) -> list[dict[str, Any]]:
        """Expand a ZIP into bounded staging items.

        Archive names must be plain asset names.  We reject directories,
        traversal components, symlinks and entries larger than the same
        per-item limit used by normal multipart uploads.  Reading is bounded
        by ``max_item_bytes + 1`` so a ZIP cannot bypass the upload limit.
        """

        if not isinstance(content, (bytes, bytearray)):
            raise ValueError("zip_content_must_be_bytes")
        try:
            archive = zipfile.ZipFile(io.BytesIO(bytes(content)))
        except (OSError, zipfile.BadZipFile) as exc:
            raise ValueError(f"zip_invalid:{exc}") from exc
        items: list[dict[str, Any]] = []
        total = 0
        with archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                # Unix mode 0120000 denotes a symbolic link.  Do not follow
                # links even if a producer accidentally includes one.
                mode = (info.external_attr >> 16) & 0xF000
                if mode == 0xA000:
                    items.append({"filename": info.filename, "content": b"", "oversized": False,
                                  "error": "zip_symlink_not_allowed"})
                    continue
                if len(items) >= 1000:
                    items.append({"filename": info.filename, "content": b"", "oversized": False,
                                  "error": "zip_entry_count_exceeded"})
                    break
                try:
                    filename = self._safe_filename(info.filename, kind)
                except ValueError as exc:
                    items.append({"filename": info.filename, "content": b"", "oversized": False,
                                  "error": str(exc)})
                    continue
                total += int(info.file_size or 0)
                if info.file_size > self.max_item_bytes or total > self.max_total_bytes:
                    items.append({"filename": filename, "content": b"", "oversized": True})
                    continue
                with archive.open(info, "r") as handle:
                    raw = handle.read(self.max_item_bytes + 1)
                items.append({
                    "filename": filename,
                    "content": raw,
                    "mimeType": "video/mp4" if kind == "emotions" else "application/json",
                    "oversized": len(raw) > self.max_item_bytes,
                })
        return items

    @staticmethod
    def _progress(items: Iterable[Mapping[str, Any]]) -> dict[str, int]:
        values = list(items)
        return {
            "total": len(values),
            "processed": sum(1 for item in values if item.get("status") in {"ready", "failed", "skipped", "success"}),
            "ready": sum(1 for item in values if item.get("status") == "ready"),
            "failed": sum(1 for item in values if item.get("status") == "failed"),
        }

    def stage(self, *, kind: str, items: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
        kind = str(kind or "").strip().lower()
        if kind not in {"motions", "emotions"}:
            raise ValueError("asset_kind_must_be_motions_or_emotions")
        staged_items = []
        total = 0
        for item in items:
            filename = str(item.get("filename") or "")
            content = item.get("content")
            if item.get("error"):
                staged_items.append({"filename": filename, "status": "failed", "error": str(item["error"])})
                continue
            if not isinstance(content, (bytes, bytearray)):
                staged_items.append({"filename": filename, "status": "failed", "error": "asset_content_must_be_bytes"})
                continue
            raw_content = bytes(content)
            total += len(raw_content)
            if item.get("oversized"):
                staged_items.append({"filename": filename, "status": "failed", "error": "asset_too_large"})
                continue
            try:
                info = self._validate_one(kind, filename, raw_content, item.get("mimeType") or item.get("mime_type"))
                info["content"] = raw_content
                staged_items.append(info)
            except (TypeError, ValueError) as exc:
                staged_items.append({"filename": filename, "status": "failed", "error": str(exc)})
        if total > self.max_total_bytes:
            for item in staged_items:
                if item.get("status") == "ready":
                    item["status"] = "failed"
                    item["error"] = "batch_too_large"
        staging_id = f"asset-stage-{uuid.uuid4().hex}"
        record = {
            "stagingId": staging_id,
            "kind": kind,
            "items": staged_items,
            "progress": self._progress(staged_items),
        }
        with self._lock:
            self._staging[staging_id] = record
        return self._public(record)

    @staticmethod
    def _public(record: Mapping[str, Any]) -> Dict[str, Any]:
        result = copy.deepcopy(dict(record))
        if "items" in result:
            for item in result.get("items", []):
                item.pop("content", None)
        else:
            result.pop("content", None)
        return result

    def preview(self, staging_id: str) -> Dict[str, Any]:
        with self._lock:
            record = self._staging.get(str(staging_id))
            if record is None:
                raise KeyError("asset_staging_not_found")
            return self._public(record)

    @staticmethod
    def _unique_name(name: str, existing: set[str]) -> str:
        if name not in existing:
            return name
        stem, suffix = Path(name).stem, Path(name).suffix
        index = 2
        while f"{stem}-{index}{suffix}" in existing:
            index += 1
        return f"{stem}-{index}{suffix}"

    @staticmethod
    def _write_bytes_atomic(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass
            raise

    def _commit_motion_items(self, items: list[dict[str, Any]], conflict: str) -> list[dict[str, Any]]:
        motion_path = Path(MOTIONS_FILE)
        motion_before_exists = motion_path.exists()
        motion_before_bytes = motion_path.read_bytes() if motion_before_exists else None
        document = load_document()
        index_before = self._asset_index.list()
        index_before_exists = self._asset_index.path.exists()
        motions = dict(document.get("motions") or {})
        metas = dict(document.get("motionMeta") or {})
        results = []
        index_records = []
        for item in items:
            raw = json.loads(item["content"].decode("utf-8"))
            detected_name, frames = convert_dollser_motion_to_frames(raw)
            name = Path(item["filename"]).stem or detected_name
            if name in motions:
                if conflict == "skip":
                    results.append({**self._public(item), "status": "skipped", "error": "asset_exists"})
                    continue
                if conflict == "rename":
                    name = self._unique_name(name, set(motions))
                elif conflict == "overwrite":
                    pass
                else:
                    results.append({**self._public(item), "status": "failed", "error": "conflict_policy_invalid"})
                    continue
            motions[name] = frames
            metas[name] = extract_dollser_motion_metadata(raw, frames)
            result = {**self._public(item), "status": "success", "assetId": name, "filename": name,
                      "logicalAssetId": item["assetId"], "physicalFilename": Path(MOTIONS_FILE).name}
            results.append(result)
            index_records.append({
                "assetId": item["assetId"],
                "version": item["version"],
                "kind": "motion",
                "filename": name,
                "physicalFilename": Path(MOTIONS_FILE).name,
                "checksum": item["checksum"],
            })
        if any(result.get("status") == "success" for result in results):
            updated_document = {
                "version": CURRENT_SCHEMA_VERSION,
                "updatedAt": document.get("updatedAt"),
                "motions": motions,
                "motionMeta": metas,
            }
            try:
                atomic_write_json(motion_path, updated_document)
                self._asset_index.upsert(index_records)
            except Exception:
                # The media file and logical index are one commit from the
                # control plane's point of view. Restore both snapshots when
                # the second write fails.
                if motion_before_exists and motion_before_bytes is not None:
                    self._write_bytes_atomic(motion_path, motion_before_bytes)
                else:
                    motion_path.unlink(missing_ok=True)
                if index_before_exists:
                    self._asset_index.replace(index_before)
                else:
                    self._asset_index.path.unlink(missing_ok=True)
                raise
        return results

    def _commit_emotion_items(self, items: list[dict[str, Any]], conflict: str) -> list[dict[str, Any]]:
        root = Path(Config.STATIC_DIR) / "resources" / "Emotions"
        root.mkdir(parents=True, exist_ok=True)
        committed: list[Path] = []
        backups: dict[Path, bytes] = {}
        results = []
        index_records = []
        index_before = self._asset_index.list()
        index_before_exists = self._asset_index.path.exists()
        try:
            existing = {path.name for path in root.iterdir() if path.is_file() and path.suffix.lower() in {".mp4", ".gif"}}
            for item in items:
                name = item["filename"]
                target = name
                if name in existing:
                    if conflict == "skip":
                        results.append({**self._public(item), "status": "skipped", "error": "asset_exists"})
                        continue
                    if conflict == "rename":
                        target = self._unique_name(name, existing)
                    elif conflict != "overwrite":
                        results.append({**self._public(item), "status": "failed", "error": "conflict_policy_invalid"})
                        continue
                path = root / target
                if path.exists():
                    backups[path] = path.read_bytes()
                self._write_bytes_atomic(path, item["content"])
                committed.append(path)
                existing.add(target)
                result = {**self._public(item), "status": "success", "filename": target,
                          "logicalAssetId": item["assetId"], "physicalFilename": f"resources/Emotions/{target}"}
                results.append(result)
                index_records.append({
                    "assetId": item["assetId"],
                    "version": item["version"],
                    "kind": "emotion",
                    "filename": target,
                    "physicalFilename": f"resources/Emotions/{target}",
                    "checksum": item["checksum"],
                })
            if index_records:
                self._asset_index.upsert(index_records)
            return results
        except Exception:
            try:
                if index_before_exists:
                    self._asset_index.replace(index_before)
                else:
                    self._asset_index.path.unlink(missing_ok=True)
            except Exception:
                pass
            for path in committed:
                try:
                    if path in backups:
                        self._write_bytes_atomic(path, backups[path])
                    else:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    def commit(self, staging_id: str, *, conflict: str = "skip") -> Dict[str, Any]:
        conflict = str(conflict or "skip").lower()
        if conflict not in {"skip", "rename", "overwrite"}:
            raise ValueError("conflict_policy_invalid")
        with self._lock:
            record = self._staging.get(str(staging_id))
            if record is None:
                completed = self._completed.get(str(staging_id))
                if completed is not None:
                    return copy.deepcopy(completed)
                raise KeyError("asset_staging_not_found")
            ready = [item for item in record["items"] if item.get("status") == "ready"]
            failed = [self._public(item) for item in record["items"] if item.get("status") != "ready"]
            if record["kind"] == "motions":
                committed = self._commit_motion_items(ready, conflict)
            else:
                committed = self._commit_emotion_items(ready, conflict)
            result = {
                "stagingId": record["stagingId"],
                "kind": record["kind"],
                "items": failed + committed,
                "success": all(item.get("status") != "failed" for item in failed + committed),
            }
            result["progress"] = self._progress(result["items"])
            self._completed[str(staging_id)] = copy.deepcopy(result)
            del self._staging[str(staging_id)]
            return result

    def rollback(self, staging_id: str) -> Dict[str, Any]:
        with self._lock:
            record = self._staging.pop(str(staging_id), None)
            if record is None:
                raise KeyError("asset_staging_not_found")
            return {
                "stagingId": record["stagingId"],
                "kind": record["kind"],
                "status": "rolled_back",
                "items": [self._public(item) for item in record["items"]],
                "success": True,
            }


_batch_importer: Optional[BatchAssetImporter] = None
_batch_lock = threading.Lock()


def get_batch_asset_importer() -> BatchAssetImporter:
    global _batch_importer
    with _batch_lock:
        if _batch_importer is None:
            _batch_importer = BatchAssetImporter()
        return _batch_importer


__all__ = ["BatchAssetImporter", "get_batch_asset_importer"]
