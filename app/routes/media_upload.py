"""儿童端媒体上行 / 补传 API（供 child_media_agent 调用）。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional

from flask import Blueprint, jsonify, request

from app.config import Config
from app.session import get_session_manager
from app.sockets.handlers import AudioChunkHandler, VideoFrameHandler
from app.utils.logger import setup_logger
from app.storage.session_quality import inspect_session_directory
from app.storage.session_layout import atomic_write_json

logger = setup_logger("media_upload")


def _session_gone_response(session_id: str):
    """实时上行要求 SessionManager 中仍有会话；已结束/重启后应 410，便于 agent 停传。"""
    _update_meta(
        session_id,
        uplinkState="session_gone",
        updatedAt=int(time.time() * 1000),
        source="agent_realtime",
    )
    return jsonify({
        "ok": False,
        "error": "session_gone",
        "sessionId": session_id,
    }), 410


def _require_live_session(session_id: str):
    if get_session_manager().get_session(session_id):
        return None
    return _session_gone_response(session_id)

media_bp = Blueprint("media_upload", __name__, url_prefix="/api/media")

# session_id -> 最近一次补传/上行元数据（供 /server 状态展示）
_media_session_meta: Dict[str, Dict[str, Any]] = {}
# 供就绪门 / 监控预览：session_id -> { frame, updatedAt }
_last_probe_frames: Dict[str, Dict[str, Any]] = {}


def get_media_session_meta(session_id: Optional[str] = None) -> Dict[str, Any]:
    if session_id:
        return dict(_media_session_meta.get(session_id, {}))
    return {k: dict(v) for k, v in _media_session_meta.items()}


def reset_media_session_meta(session_id: str) -> None:
    """Discard stale uplink evidence before retrying the same media session."""
    _media_session_meta.pop(str(session_id), None)
    _last_probe_frames.pop(str(session_id), None)


def remember_probe_frame(session_id: str, frame_data: Optional[str]) -> None:
    """缓存会话最近一帧，供 readiness probe / 监控预览（不落盘）。"""
    if not session_id or not frame_data:
        return
    # 限制体积：超大帧跳过（避免内存暴涨）；正常 JPEG base64 通常远小于此
    if len(frame_data) > 2_500_000:
        return
    _last_probe_frames[session_id] = {
        "frame": frame_data,
        "updatedAt": int(time.time() * 1000),
    }


def get_last_probe_frame(session_id: Optional[str]) -> Optional[str]:
    if not session_id:
        return None
    entry = _last_probe_frames.get(session_id)
    if isinstance(entry, dict):
        return entry.get("frame")
    # 兼容旧结构（纯 str）
    return entry if isinstance(entry, str) else None


def get_last_probe_meta(session_id: Optional[str]) -> Optional[Dict[str, Any]]:
    if not session_id:
        return None
    entry = _last_probe_frames.get(session_id)
    if isinstance(entry, dict):
        return dict(entry)
    if isinstance(entry, str):
        return {"frame": entry, "updatedAt": None}
    return None


def _update_meta(session_id: str, **kwargs) -> None:
    meta = _media_session_meta.setdefault(session_id, {})
    meta.update(kwargs)
    meta["updatedAt"] = kwargs.get("updatedAt") or meta.get("updatedAt")


def _check_agent_key() -> bool:
    expected = Config.CHILD_MEDIA_AGENT_KEY or ""
    if not expected:
        return True
    return request.headers.get("X-Child-Media-Agent-Key") == expected


@media_bp.before_request
def _auth_media_agent():
    if request.method == "OPTIONS":
        return None
    if not _check_agent_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    return None


@media_bp.route("/<session_id>/frames", methods=["POST"])
def upload_frames(session_id: str):
    """
    实时视频帧上行。

    JSON:
      { frame: base64, seq?: int, timestamp?: number }
    或批量:
      { frames: [{ frame, seq, timestamp }, ...] }
    """
    data = request.get_json(silent=True) or {}
    frames = data.get("frames")
    if frames is None:
        frames = [{
            "frame": data.get("frame"),
            "seq": data.get("seq"),
            "timestamp": data.get("timestamp"),
        }]

    if not isinstance(frames, list) or not frames:
        return jsonify({"ok": False, "error": "frame(s) required"}), 400

    gone = _require_live_session(session_id)
    if gone is not None:
        return gone

    last_seq = None
    accepted = 0
    for item in frames:
        if not isinstance(item, dict):
            continue
        frame = item.get("frame")
        if not frame:
            continue
        seq = item.get("seq")
        ts = item.get("timestamp")
        ok = VideoFrameHandler.handle({
            "sessionId": session_id,
            "frame": frame,
            "timestamp": ts,
            "seq": seq,
        })
        if ok:
            accepted += 1
            if seq is not None:
                last_seq = seq
            remember_probe_frame(session_id, frame)

    _update_meta(
        session_id,
        uplinkState="streaming",
        lastVideoSeq=last_seq,
        lastVideoAccepted=accepted,
        lastFrameAt=int(time.time() * 1000),
        updatedAt=int(time.time() * 1000),
        source="agent_realtime",
    )
    return jsonify({"ok": True, "accepted": accepted, "lastSeq": last_seq})


@media_bp.route("/<session_id>/audio-chunks", methods=["POST"])
def upload_audio_chunks(session_id: str):
    """
    实时音频块上行。

    JSON:
      { chunk: base64, seq?: int, timestamp?: number }
    或批量:
      { chunks: [{ chunk, seq, timestamp }, ...] }
    """
    data = request.get_json(silent=True) or {}
    chunks = data.get("chunks")
    if chunks is None:
        chunks = [{
            "chunk": data.get("chunk"),
            "seq": data.get("seq"),
            "timestamp": data.get("timestamp"),
        }]

    if not isinstance(chunks, list) or not chunks:
        return jsonify({"ok": False, "error": "chunk(s) required"}), 400

    gone = _require_live_session(session_id)
    if gone is not None:
        return gone

    last_seq = None
    accepted = 0
    for item in chunks:
        if not isinstance(item, dict):
            continue
        chunk = item.get("chunk")
        if not chunk:
            continue
        seq = item.get("seq")
        ts = item.get("timestamp")
        ok = AudioChunkHandler.handle({
            "sessionId": session_id,
            "chunk": chunk,
            "timestamp": ts,
            "seq": seq,
        })
        if ok:
            accepted += 1
            if seq is not None:
                last_seq = seq

    _update_meta(
        session_id,
        uplinkState="streaming",
        lastAudioSeq=last_seq,
        lastAudioAccepted=accepted,
        lastAudioAt=int(time.time() * 1000),
        updatedAt=int(time.time() * 1000),
        source="agent_realtime",
    )
    return jsonify({"ok": True, "accepted": accepted, "lastSeq": last_seq})


@media_bp.route("/<session_id>/upload", methods=["POST"])
def upload_session_files(session_id: str):
    """
    会话结束后补传本地完整文件。

    multipart:
      video: file (optional)
      audio: file (optional)
      sha256_video / sha256_audio: form fields (optional)
      duration: form field (optional)
    """
    session_dir = Config.get_recording_path(session_id)
    video_file = request.files.get("video")
    audio_file = request.files.get("audio")
    raw_manifest = request.form.get("trackManifest")
    try:
        track_manifest = json.loads(raw_manifest) if raw_manifest else []
    except ValueError:
        return jsonify({"ok": False, "error": "trackManifest invalid JSON"}), 400
    if not isinstance(track_manifest, list) or len(track_manifest) > 32:
        return jsonify({"ok": False, "error": "trackManifest must be an array of at most 32 tracks"}), 400

    if not video_file and not audio_file and not track_manifest:
        return jsonify({"ok": False, "error": "video or audio file required"}), 400

    saved = {}
    checksums = {}
    saved_tracks = []

    seen_track_ids = set()
    seen_track_filenames = set()
    safe_track_id = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
    pending_tracks = []
    try:
        for raw_track in track_manifest:
            if not isinstance(raw_track, dict):
                raise ValueError("trackManifest item must be an object")
            track_id = str(raw_track.get("trackId") or "")
            filename = str(raw_track.get("filename") or "")
            kind = str(raw_track.get("kind") or "")
            field = f"track__{track_id}"
            uploaded = request.files.get(field)
            valid_filename = (
                Path(filename).name == filename
                and (
                    (kind == "video" and filename.startswith("video.environment") and filename.endswith(".avi"))
                    or (kind == "audio" and filename.startswith("audio.environment") and filename.endswith(".wav"))
                )
            )
            if (
                not safe_track_id.fullmatch(track_id)
                or not valid_filename
                or track_id in seen_track_ids
                or filename in seen_track_filenames
                or uploaded is None
            ):
                raise ValueError(f"invalid or missing environment track:{track_id}")
            seen_track_ids.add(track_id)
            seen_track_filenames.add(filename)

            target = session_dir / filename
            temporary = session_dir / f".{filename}.{time.time_ns()}.upload"
            uploaded.save(str(temporary))
            digest = _sha256_file(temporary)
            expected = str(raw_track.get("sha256") or "")
            if expected and digest != expected:
                raise ValueError(f"track checksum mismatch:{track_id}")
            pending_tracks.append((raw_track, track_id, filename, target, temporary, digest))

        # All track files and hashes are valid before any final filename changes.
        for raw_track, track_id, filename, target, temporary, digest in pending_tracks:
            os.replace(temporary, target)
            entry = dict(raw_track)
            entry["filename"] = filename
            entry["sha256"] = digest
            entry["sizeBytes"] = target.stat().st_size
            saved_tracks.append(entry)
            saved[f"track:{track_id}"] = str(target)
            checksums[f"track:{track_id}"] = digest
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    finally:
        for _, _, _, _, temporary, _ in pending_tracks:
            temporary.unlink(missing_ok=True)

    if video_file and video_file.filename:
        target = Config.get_video_file_path(session_id)
        realtime_backup = session_dir / f"video.realtime{Config.VIDEO_FILE_EXTENSION}"
        if target.exists() and not realtime_backup.exists():
            try:
                shutil.move(str(target), str(realtime_backup))
            except Exception as exc:
                logger.warning("备份实时视频失败: %s", exc)
        video_file.save(str(target))
        digest = _sha256_file(target)
        expected = request.form.get("sha256_video")
        if expected and expected != digest:
            logger.warning(
                "视频 sha256 不匹配: session=%s expected=%s got=%s",
                session_id, expected, digest,
            )
        saved["video"] = str(target)
        checksums["video"] = digest

    if audio_file and audio_file.filename:
        target = Config.get_audio_file_path(session_id)
        realtime_backup = session_dir / f"audio.realtime{Config.AUDIO_FILE_EXTENSION}"
        if target.exists() and not realtime_backup.exists():
            try:
                shutil.move(str(target), str(realtime_backup))
            except Exception as exc:
                logger.warning("备份实时音频失败: %s", exc)
        audio_file.save(str(target))
        digest = _sha256_file(target)
        expected = request.form.get("sha256_audio")
        if expected and expected != digest:
            logger.warning(
                "音频 sha256 不匹配: session=%s expected=%s got=%s",
                session_id, expected, digest,
            )
        saved["audio"] = str(target)
        checksums["audio"] = digest

    # 元数据标记
    meta_path = session_dir / "archive_meta.json"
    try:
        meta = {
            "source": "agent_local",
            "sessionId": session_id,
            "duration": request.form.get("duration"),
            "checksums": checksums,
            "saved": saved,
        }
        if saved_tracks:
            meta["tracks"] = saved_tracks
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("写入 archive_meta 失败: %s", exc)

    _update_meta(
        session_id,
        uploadState="completed",
        uplinkState="uploaded",
        source="agent_local",
        localBytes=sum(Path(p).stat().st_size for p in saved.values() if Path(p).exists()),
        checksums=checksums,
        tracks=saved_tracks,
    )

    if saved_tracks:
        session_meta_path = session_dir / "session_meta.json"
        try:
            current = json.loads(session_meta_path.read_text(encoding="utf-8")) if session_meta_path.exists() else {}
            if not isinstance(current, dict):
                current = {}
            by_track = {
                str(item.get("trackId")): dict(item)
                for item in (current.get("tracks") or [])
                if isinstance(item, dict) and item.get("trackId")
            }
            for item in saved_tracks:
                by_track[str(item["trackId"])] = item
            current["tracks"] = list(by_track.values())
            atomic_write_json(session_meta_path, current)
        except Exception as exc:
            logger.warning("合并动态轨道 session_meta 失败: %s", exc)

    logger.info("会话媒体补传完成: session_id=%s files=%s", session_id, list(saved.keys()))
    return jsonify({
        "ok": True,
        "sessionId": session_id,
        "saved": saved,
        "checksums": checksums,
        "source": "agent_local",
        "tracks": saved_tracks,
    })


@media_bp.route("/<session_id>/status", methods=["GET"])
def media_session_status(session_id: str):
    response = {"ok": True, "sessionId": session_id, "meta": get_media_session_meta(session_id)}
    # The default response is byte-for-byte compatible with the old status
    # shape.  The control plane opts in to the read-only storage view.
    if request.args.get("includeArchive") in {"1", "true", "yes"}:
        archive_path = _existing_session_dir(session_id) / "archive_meta.json"
        archive = None
        try:
            if archive_path.is_file():
                raw_archive = json.loads(archive_path.read_text(encoding="utf-8"))
                if isinstance(raw_archive, dict):
                    # The Runtime only needs an acknowledgement and hashes.
                    # Do not expose server-local absolute paths from `saved`.
                    archive = {
                        "completed": raw_archive.get("source") == "agent_local",
                        "source": raw_archive.get("source"),
                        "checksums": raw_archive.get("checksums") or {},
                        "tracks": raw_archive.get("tracks") or [],
                    }
        except (OSError, ValueError, TypeError) as exc:
            logger.warning(
                "read archive acknowledgement failed: session=%s error=%s",
                session_id,
                exc,
            )
        response["archive"] = archive
    if request.args.get("includeQuality") in {"1", "true", "yes"}:
        session_dir = _existing_session_dir(session_id)
        response["quality"] = inspect_session_directory(
            session_dir,
            include_hash=request.args.get("includeHash") in {"1", "true", "yes"},
        )
    return jsonify(response)


def _existing_session_dir(session_id: str) -> Path:
    """Resolve a session directory without creating it."""

    root = Path(Config.RECORDINGS_DIR).resolve()
    raw = str(session_id or "")
    if not raw or raw in {".", ".."} or Path(raw).name != raw or "\x00" in raw:
        return root / "__missing_session__"

    try:
        from app.services.recording_timeline import resolve_recording_dir

        mapped = resolve_recording_dir(session_id)
        if mapped is not None:
            resolved = Path(mapped).resolve()
            if resolved == root or root in resolved.parents:
                return resolved
    except Exception:
        pass
    candidate = (root / raw).resolve()
    return candidate if candidate == root or root in candidate.parents else root / "__missing_session__"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()
