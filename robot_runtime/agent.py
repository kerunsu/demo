"""
Robot Runtime（机器人端 Windows 本机统一进程）

能力：
1. 媒体：独占摄像头/麦克风、本地落盘、实时上行、会话补传、MJPEG 预览
2. OSC：转发动作到本机 DollSer.exe（原 doll/robot_agent）
3. 向后端 register/heartbeat，供 robot_runtime 模式直连控制
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import wave
import webbrowser
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import cv2
import numpy as np
import requests
from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS

from robot_runtime import register_client
from robot_runtime.osc_bridge import (
    DEFAULT_MOVE_MS,
    osc_status,
    playback_state,
    send_pose,
)
from robot_runtime import updater as runtime_updater

try:
    import pyaudio
except ImportError:  # pragma: no cover
    pyaudio = None


AGENT_HOST = os.environ.get(
    "ROBOT_RUNTIME_HOST",
    os.environ.get("CHILD_MEDIA_AGENT_HOST", "0.0.0.0"),
)
AGENT_PORT = int(
    os.environ.get(
        "ROBOT_RUNTIME_PORT",
        os.environ.get("CHILD_MEDIA_AGENT_PORT", 19091),
    )
)
AGENT_KEY = (
    os.environ.get("ROBOT_RUNTIME_KEY")
    or os.environ.get("CHILD_MEDIA_AGENT_KEY")
    or os.environ.get("ROBOT_AGENT_KEY")
    or ""
)

FPS = int(os.environ.get("CHILD_MEDIA_FPS", 5))
WIDTH = int(os.environ.get("CHILD_MEDIA_WIDTH", 320))
HEIGHT = int(os.environ.get("CHILD_MEDIA_HEIGHT", 240))
JPEG_QUALITY = int(os.environ.get("CHILD_MEDIA_JPEG_QUALITY", 50))
CAMERA_INDEX = int(os.environ.get("CHILD_MEDIA_CAMERA_INDEX", 0))
AUDIO_RATE = int(os.environ.get("CHILD_MEDIA_AUDIO_RATE", 16000))
AUDIO_CHANNELS = int(os.environ.get("CHILD_MEDIA_AUDIO_CHANNELS", 1))
AUDIO_CHUNK = int(os.environ.get("CHILD_MEDIA_AUDIO_CHUNK", 1024))
DEFAULT_BACKEND = (
    os.environ.get("ROBOT_RUNTIME_BACKEND_URL")
    or os.environ.get("CHILD_MEDIA_BACKEND_URL")
    or ""
).rstrip("/")
UPLINK_QUEUE_MAX = int(os.environ.get("CHILD_MEDIA_UPLINK_QUEUE_MAX", 200))
UPLINK_RETRY_SEC = float(os.environ.get("CHILD_MEDIA_UPLINK_RETRY_SEC", 1.0))

_default_data = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EIArt" / "child_media"
_DATA_DIR_ENV = os.environ.get("CHILD_MEDIA_DATA_DIR", "").strip()
_data_dir_lock = threading.Lock()
_DATA_DIR = Path(_DATA_DIR_ENV) if _DATA_DIR_ENV else _default_data
_DATA_DIR.mkdir(parents=True, exist_ok=True)
# Backward-compatible alias (prefer get_data_dir() for runtime reads)
DATA_DIR = _DATA_DIR

_prepared_motion_lock = threading.RLock()
_prepared_motion: Optional[Dict[str, Any]] = None
_active_motion_envelope: Optional[Dict[str, Any]] = None
_motion_event_history: Deque[Dict[str, Any]] = deque(maxlen=100)
PREPARED_MOTION_TTL_MS = max(
    3000,
    int(os.environ.get("ROBOT_RUNTIME_PREPARED_MOTION_TTL_MS", 15000)),
)


def _expire_prepared_motion_locked(now_ms: Optional[int] = None) -> Optional[str]:
    """Drop an abandoned prepare so one lost commit cannot brick later courses."""
    global _prepared_motion
    if not _prepared_motion:
        return None
    prepared_at = int(_prepared_motion.get("preparedAtRuntimeMs") or 0)
    current_ms = int(now_ms or time.time() * 1000)
    if prepared_at and current_ms - prepared_at < PREPARED_MOTION_TTL_MS:
        return None
    envelope = _prepared_motion.get("envelope") or {}
    behavior_id = str(envelope.get("behaviorId") or "") or None
    _prepared_motion = None
    return behavior_id


def _behavior_envelope(payload: Dict[str, Any], *, modality: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    envelope = {
        "protocolVersion": str(payload.get("protocolVersion") or ""),
        "sessionId": str(payload.get("sessionId") or ""),
        "requestId": str(payload.get("requestId") or ""),
        "behaviorId": str(payload.get("behaviorId") or ""),
        "startAtServerMs": payload.get("startAtServerMs"),
        "modality": str(payload.get("modality") or ""),
    }
    if envelope["protocolVersion"] != "1":
        return None, "behavior_protocol_unsupported"
    if envelope["modality"] != modality:
        return None, "behavior_modality_invalid"
    if not all(envelope[key] for key in ("sessionId", "requestId", "behaviorId")):
        return None, "behavior_identity_incomplete"
    try:
        envelope["startAtServerMs"] = int(envelope["startAtServerMs"])
    except (TypeError, ValueError):
        return None, "behavior_anchor_invalid"
    return envelope, None


def _emit_motion_event(envelope: Dict[str, Any], status: str, reason: Optional[str]) -> None:
    global _active_motion_envelope
    payload = {
        **envelope,
        "modality": "motion",
        "status": status,
        "terminalStatus": status if status != "started" else None,
        "reason": reason,
        "actualAtRuntimeMs": int(time.time() * 1000),
    }
    with _prepared_motion_lock:
        _motion_event_history.append(dict(payload))
        if (
            status in {"ended", "failed", "stopped", "timeout"}
            and _active_motion_envelope == envelope
        ):
            _active_motion_envelope = None

    def _post() -> None:
        base = (register_client.BACKEND_URL or "").rstrip("/")
        if not base:
            return
        headers = {"Content-Type": "application/json"}
        if register_client.RUNTIME_KEY:
            headers["X-Robot-Runtime-Key"] = register_client.RUNTIME_KEY
            headers["X-Child-Media-Agent-Key"] = register_client.RUNTIME_KEY
        try:
            requests.post(
                f"{base}/api/robot/runtime/behavior/event",
                json=payload,
                headers=headers,
                timeout=3,
            )
        except Exception as exc:
            app.logger.warning(
                "[RobotRuntime] motion event callback failed behaviorId=%s status=%s error=%s",
                envelope.get("behaviorId"),
                status,
                exc,
            )

    threading.Thread(
        target=_post,
        daemon=True,
        name=f"RobotRuntime-BehaviorEvent-{status}",
    ).start()

STATIC_DIR = Path(__file__).resolve().parent / "static"
if getattr(sys, "frozen", False):  # PyInstaller
    STATIC_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "robot_runtime" / "static"
    if not STATIC_DIR.is_dir():
        STATIC_DIR = Path(getattr(sys, "_MEIPASS", ".")) / "static"


def _emotion_assets_dir() -> Path:
    configured = str(os.environ.get("ROBOT_RUNTIME_EMOTIONS_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "Emotions"
    return Path(__file__).resolve().parent.parent / "static" / "resources" / "Emotions"


_emotion_prewarm_lock = threading.RLock()
_emotion_prewarm: Dict[str, Any] = {
    "instanceId": None,
    "phase": "waiting",
    "total": 0,
    "completed": 0,
    "current": None,
    "failed": [],
    "updatedAt": 0,
}


def _emotion_package_summary() -> Dict[str, Any]:
    root = _emotion_assets_dir()
    files = []
    if root.is_dir():
        files = [
            item for item in root.iterdir()
            if item.is_file() and item.suffix.lower() in {'.mp4', '.gif', '.webm', '.ogg'}
        ]
    return {
        "packagedCount": len(files),
        "packagedBytes": sum(item.stat().st_size for item in files),
    }


def emotion_prewarm_status() -> Dict[str, Any]:
    now_ms = int(time.time() * 1000)
    with _emotion_prewarm_lock:
        result = dict(_emotion_prewarm)
        result["failed"] = list(_emotion_prewarm.get("failed") or [])
    updated_at = int(result.get("updatedAt") or 0)
    result["stale"] = not updated_at or now_ms - updated_at > 15000
    result["ready"] = (
        result.get("phase") == "ready"
        and int(result.get("total") or 0) > 0
        and int(result.get("completed") or 0) >= int(result.get("total") or 0)
        and not result["failed"]
        and not result["stale"]
    )
    result.update(_emotion_package_summary())
    return result


def get_data_dir() -> Path:
    with _data_dir_lock:
        return _DATA_DIR


def _sanitize_human_dir_name(name: Optional[str]) -> Optional[str]:
    """与服务端 recording_timeline.sanitize 对齐的轻量净化。"""
    if not name:
        return None
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(name).strip())
    cleaned = cleaned.strip(" .")
    return cleaned or None


def _safe_track_component(value: Any) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip()).strip("._")
    if not cleaned:
        raise ValueError("trackId required")
    return cleaned[:80]


def resolve_local_session_dir(session_id: str, human_dir_name: Optional[str] = None) -> Path:
    """
    本地落盘目录：优先 sessions/{姓名-年龄-日期-N}/，与服务端一致；
    未提供 humanDirName 时回退到 legacy {sessionId}/。
    """
    root = get_data_dir()
    safe = _sanitize_human_dir_name(human_dir_name)
    if safe:
        return root / "sessions" / safe
    return root / session_id


def set_data_dir(path: Path | str, *, persist: bool = True) -> Path:
    """Switch local media save root. Env CHILD_MEDIA_DATA_DIR always wins if set."""
    global DATA_DIR, _DATA_DIR
    if _DATA_DIR_ENV:
        raise RuntimeError(
            "CHILD_MEDIA_DATA_DIR env is set; unset it to change path from UI"
        )
    target = Path(str(path).strip().strip('"'))
    if not str(target):
        raise ValueError("path required")
    target.mkdir(parents=True, exist_ok=True)
    # probe write
    probe = target / ".eiart_write_probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        raise RuntimeError(f"cannot write to path: {exc}") from exc
    with _data_dir_lock:
        _DATA_DIR = target
        DATA_DIR = target
    if persist:
        register_client.save_persisted_config(media_data_dir=str(target))
    return target


def data_dir_editable() -> bool:
    return not bool(_DATA_DIR_ENV)


def _runtime_version() -> str:
    return runtime_updater.read_runtime_version()

app = Flask(__name__)
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    allow_headers=[
        "Content-Type",
        "X-Child-Media-Agent-Key",
        "X-Robot-Runtime-Key",
        "X-Robot-Agent-Key",
    ],
    methods=["GET", "POST", "OPTIONS"],
)


@app.after_request
def _allow_local_asset_access(response):
    # Chrome may preflight a LAN page before it reads 127.0.0.1 resources.
    response.headers['Access-Control-Allow-Private-Network'] = 'true'
    return response

# 环境变量优先；否则读取上次在运维 UI 保存的后端地址 / 媒体目录
if DEFAULT_BACKEND:
    register_client.set_backend_url(DEFAULT_BACKEND)
_persisted = register_client.load_persisted_config()
_persisted_backend = register_client.get_registry_status().get("backendUrl") or ""
if _persisted_backend and not DEFAULT_BACKEND:
    DEFAULT_BACKEND = str(_persisted_backend).rstrip("/")
    register_client.set_backend_url(DEFAULT_BACKEND)
if not _DATA_DIR_ENV and _persisted.get("mediaDataDir"):
    try:
        set_data_dir(str(_persisted["mediaDataDir"]), persist=False)
    except Exception:
        pass


def check_agent_key() -> bool:
    if not AGENT_KEY:
        return True
    provided = (
        request.headers.get("X-Robot-Runtime-Key")
        or request.headers.get("X-Child-Media-Agent-Key")
        or request.headers.get("X-Robot-Agent-Key")
        or ""
    )
    return provided == AGENT_KEY


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class MediaRecorderState:
    """本机会话录制 + 预览 + 上行队列。"""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.session_id: Optional[str] = None
        self.human_dir_name: Optional[str] = None
        self.recording_mode: str = "continuous"
        self.backend_base: Optional[str] = None
        self.recording = False
        self.device_open = False
        self.start_ts: Optional[float] = None
        self.session_dir: Optional[Path] = None
        self.video_path: Optional[Path] = None
        self.audio_path: Optional[Path] = None

        self._cap: Optional[cv2.VideoCapture] = None
        self._writer: Optional[cv2.VideoWriter] = None
        self._wave: Optional[wave.Wave_write] = None
        self._pa = None
        self._audio_stream = None

        self._capture_thread: Optional[threading.Thread] = None
        self._audio_thread: Optional[threading.Thread] = None
        self._uplink_thread: Optional[threading.Thread] = None
        self._uplink_stop_event = threading.Event()
        self._extra_threads: List[threading.Thread] = []
        self._extra_tracks: List[Dict[str, Any]] = []
        self._stop_event = threading.Event()

        self._preview_jpeg: Optional[bytes] = None
        self._preview_cond = threading.Condition()

        self._video_seq = 0
        self._audio_seq = 0
        self._uplink_q: Deque[Tuple[str, Dict[str, Any]]] = deque(maxlen=UPLINK_QUEUE_MAX)
        self._uplink_gap_start: Optional[float] = None
        self.upload_state = "idle"
        self.last_error: Optional[str] = None
        self.frame_count = 0
        self.audio_chunk_count = 0
        self._session_gone_stopping = False

    def status(self) -> Dict[str, Any]:
        with self._lock:
            gap = None
            if self._uplink_gap_start is not None:
                gap = time.time() - self._uplink_gap_start
            base = {
                "ok": True,
                "service": "robot_runtime",
                "recording": self.recording,
                "deviceOpen": self.device_open,
                "sessionId": self.session_id,
                "humanDirName": getattr(self, "human_dir_name", None),
                "recordingMode": getattr(self, "recording_mode", None),
                "elapsedMs": int((time.time() - self.start_ts) * 1000) if (self.recording and self.start_ts) else 0,
                "sessionDir": str(self.session_dir) if self.session_dir else None,
                "backendBaseUrl": self.backend_base,
                "frameCount": self.frame_count,
                "audioChunkCount": self.audio_chunk_count,
                "uplinkQueue": len(self._uplink_q),
                "uplinkGapSeconds": gap,
                "uploadState": self.upload_state,
                "lastError": self.last_error,
                "dataDir": str(get_data_dir()),
                "dataDirEditable": data_dir_editable(),
                "runtimeVersion": _runtime_version(),
                "frozen": bool(getattr(sys, "frozen", False)),
                "agentHost": AGENT_HOST,
                "agentPort": AGENT_PORT,
                "fps": FPS,
                "resolution": f"{WIDTH}x{HEIGHT}",
                "tracks": self._public_track_manifest(),
            }
            base.update(osc_status())
            base.update(register_client.get_registry_status())
            base["emotionPrewarm"] = emotion_prewarm_status()
            return base

    def start(
        self,
        session_id: str,
        backend_base: Optional[str] = None,
        recording_mode: str = "continuous",
        human_dir_name: Optional[str] = None,
        capture_devices: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        superseded_result: Optional[Dict[str, Any]] = None
        with self._lock:
            if self.recording:
                if self.session_id == session_id:
                    return {
                        "ok": True,
                        "already": True,
                        "sessionId": session_id,
                        "humanDirName": self.human_dir_name,
                        "sessionDir": str(self.session_dir) if self.session_dir else None,
                        "recordingMode": getattr(self, "recording_mode", recording_mode),
                        "elapsedMs": int((time.time() - self.start_ts) * 1000) if self.start_ts else 0,
                    }
                # 单儿童端模式：新 session 接管旧 session，避免误触后继续录入旧目录。
                superseded_result = self._stop_unlocked()

            self.session_id = session_id
            self.human_dir_name = _sanitize_human_dir_name(human_dir_name)
            self.recording_mode = (recording_mode or "continuous").lower()
            self.backend_base = (backend_base or DEFAULT_BACKEND or "").rstrip("/") or None
            if self.backend_base:
                register_client.set_backend_url(self.backend_base)
                register_client.register_once()
            self.session_dir = resolve_local_session_dir(session_id, self.human_dir_name)
            if self.session_dir.exists():
                shutil.rmtree(self.session_dir, ignore_errors=True)
            self.session_dir.mkdir(parents=True, exist_ok=True)
            self.video_path = self.session_dir / "video.avi"
            self.audio_path = self.session_dir / "audio.wav"
            self._extra_tracks = self._prepare_extra_tracks(capture_devices or [])
            self._stop_event.clear()
            self._video_seq = 0
            self._audio_seq = 0
            self.frame_count = 0
            self.audio_chunk_count = 0
            self.upload_state = "recording"
            self.last_error = None
            self._session_gone_stopping = False
            # A stopped session may still have a request finishing in its old
            # uplink thread.  Give every session its own queue/stop token so
            # that thread can never consume a later course's frames.
            self._uplink_q = deque(maxlen=UPLINK_QUEUE_MAX)
            self._uplink_stop_event = threading.Event()
            self._uplink_gap_start = None

            try:
                self._open_devices()
            except Exception:
                self._close_devices()
                raise
            self.recording = True
            self.start_ts = time.time()
            self._write_local_session_meta()

            self._capture_thread = threading.Thread(
                target=self._video_loop, daemon=True, name=f"CMA-Video-{session_id}"
            )
            self._audio_thread = threading.Thread(
                target=self._audio_loop, daemon=True, name=f"CMA-Audio-{session_id}"
            )
            self._uplink_thread = threading.Thread(
                target=self._uplink_loop,
                args=(
                    session_id,
                    self.backend_base,
                    self._uplink_q,
                    self._uplink_stop_event,
                ),
                daemon=True,
                name=f"CMA-Uplink-{session_id}",
            )
            self._capture_thread.start()
            self._audio_thread.start()
            self._start_extra_track_threads(session_id)
            self._uplink_thread.start()

            result = {
                "ok": True,
                "sessionId": session_id,
                "humanDirName": self.human_dir_name,
                "sessionDir": str(self.session_dir),
                "recordingMode": self.recording_mode,
                "videoPath": str(self.video_path),
                "audioPath": str(self.audio_path),
                "backendBaseUrl": self.backend_base,
                "tracks": self._public_track_manifest(),
            }
            if superseded_result and superseded_result.get("sessionId"):
                result["supersededSessionId"] = superseded_result.get("sessionId")
                self._schedule_archive_upload(superseded_result)
            return result

    def _prepare_extra_tracks(self, devices: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        tracks: List[Dict[str, Any]] = []
        used_ids = set()
        primary_used = {"video": False, "audio": False}
        for raw in devices:
            if not isinstance(raw, dict) or not raw.get("enabled", True):
                continue
            if str(raw.get("owner") or "runtime") != "runtime":
                continue
            kind = str(raw.get("kind") or "").lower()
            role = str(raw.get("role") or "environment_secondary")
            if kind not in {"video", "audio"} or role == "primary_child":
                continue
            track_id = _safe_track_component(raw.get("trackId") or raw.get("track_id"))
            if track_id in used_ids:
                raise ValueError(f"duplicate trackId: {track_id}")
            used_ids.add(track_id)
            primary = role == "primary_environment" and not primary_used[kind]
            primary_used[kind] = primary_used[kind] or primary
            if kind == "video":
                filename = "video.environment.avi" if primary else f"video.environment.{track_id}.avi"
            else:
                filename = "audio.environment.wav" if primary else f"audio.environment.{track_id}.wav"
            tracks.append({
                "trackId": track_id,
                "deviceId": str(raw.get("deviceId") or raw.get("device_id") or track_id),
                "kind": kind,
                "role": role,
                "required": bool(raw.get("required")),
                "selector": dict(raw.get("selector") or {}),
                "filename": filename,
                "format": "avi" if kind == "video" else "wav",
                "clockDomain": "runtime.session.monotonic",
                "status": "pending",
                "frameCount": 0,
                "chunkCount": 0,
            })
        return tracks

    def _public_track_manifest(self) -> List[Dict[str, Any]]:
        hidden = {"cap", "writer", "stream", "wave"}
        return [{key: value for key, value in track.items() if key not in hidden and key != "selector"}
                for track in self._extra_tracks]

    def _write_local_session_meta(self) -> None:
        """机器人端只写轻量 meta（含 mediaSessionId），不写 timeline.csv（权威在服务端）。"""
        if not self.session_dir:
            return
        meta = {
            "mediaSessionId": self.session_id,
            "humanDirName": self.human_dir_name,
            "recordingMode": self.recording_mode,
            "recordingStartedAt": datetime.fromtimestamp(
                self.start_ts or time.time()
            ).isoformat(timespec="seconds"),
            "note": "timeline.csv is authored on server; local folder mirrors humanDirName for media backup",
            "tracks": self._public_track_manifest(),
        }
        try:
            (self.session_dir / "session_meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            app.logger.warning("write local session_meta failed: %s", exc)

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            result = self._stop_unlocked()
        self._schedule_archive_upload(result)
        return result

    def _schedule_archive_upload(self, result: Dict[str, Any]) -> None:
        """Upload a stopped session without blocking a replacement capture."""
        # 补传放到后台：先让儿童页有机会 emit stop_recording 关闭服务端写盘
        session_id = result.get("sessionId")
        video_path = result.get("videoPath")
        if session_id and video_path:
            threading.Thread(
                target=self._upload_archive,
                args=(
                    session_id,
                    Path(video_path),
                    Path(result["audioPath"]) if result.get("audioPath") else None,
                    result.get("duration"),
                    result.get("backendBaseUrl"),
                    result.get("tracks") or [],
                ),
                daemon=True,
                name=f"CMA-Upload-{session_id}",
            ).start()
            result["upload"] = {"ok": True, "started": True, "async": True}

    def _stop_unlocked(self) -> Dict[str, Any]:
        session_id = self.session_id
        video_path = self.video_path
        audio_path = self.audio_path
        backend = self.backend_base
        duration = (time.time() - self.start_ts) if self.start_ts else None

        self._stop_event.set()
        uplink_queue = self._uplink_q
        uplink_stop_event = self._uplink_stop_event
        uplink_stop_event.set()
        self.recording = False

        # 等待采集线程结束
        for t in (self._capture_thread, self._audio_thread):
            if t and t.is_alive() and t is not threading.current_thread():
                t.join(timeout=2.0)
        for thread in self._extra_threads:
            if thread.is_alive() and thread is not threading.current_thread():
                thread.join(timeout=2.0)

        self._close_devices()

        # 给上行线程一点时间排空
        if self._uplink_thread and self._uplink_thread.is_alive():
            self._uplink_thread.join(timeout=3.0)
        if self._uplink_thread and self._uplink_thread.is_alive():
            dropped = len(uplink_queue)
            uplink_queue.clear()
            if dropped:
                app.logger.warning(
                    "discarded %s realtime uplink items after session stop; "
                    "the complete local archive will be uploaded instead "
                    "(session=%s)",
                    dropped,
                    session_id,
                )

        self.device_open = False
        self._capture_thread = None
        self._audio_thread = None
        self._uplink_thread = None
        self._extra_threads = []

        tracks = self._public_track_manifest()
        self._write_local_session_meta()

        return {
            "ok": True,
            "sessionId": session_id,
            "videoPath": str(video_path) if video_path else None,
            "audioPath": str(audio_path) if audio_path else None,
            "duration": duration,
            "frameCount": self.frame_count,
            "audioChunkCount": self.audio_chunk_count,
            "backendBaseUrl": backend,
            "tracks": tracks,
        }

    def _open_devices(self) -> None:
        self._cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
        if not self._cap or not self._cap.isOpened():
            # 回退默认后端
            self._cap = cv2.VideoCapture(CAMERA_INDEX)
        if not self._cap or not self._cap.isOpened():
            raise RuntimeError(f"无法打开摄像头 index={CAMERA_INDEX}")

        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        self._cap.set(cv2.CAP_PROP_FPS, FPS)

        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        self._writer = cv2.VideoWriter(
            str(self.video_path), fourcc, float(FPS), (WIDTH, HEIGHT)
        )
        if not self._writer.isOpened():
            raise RuntimeError(f"无法创建视频文件: {self.video_path}")

        if pyaudio is None:
            app.logger.warning("pyaudio 未安装，跳过音频采集")
        else:
            self._pa = pyaudio.PyAudio()
            self._wave = wave.open(str(self.audio_path), "wb")
            self._wave.setnchannels(AUDIO_CHANNELS)
            self._wave.setsampwidth(self._pa.get_sample_size(pyaudio.paInt16))
            self._wave.setframerate(AUDIO_RATE)
            self._audio_stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=AUDIO_CHANNELS,
                rate=AUDIO_RATE,
                input=True,
                frames_per_buffer=AUDIO_CHUNK,
            )

        self._open_extra_tracks()
        self.device_open = True

    def _open_extra_tracks(self) -> None:
        for track in self._extra_tracks:
            try:
                selector = track.get("selector") or {}
                raw_index = selector.get("index", selector.get("deviceIndex"))
                index = int(raw_index) if raw_index is not None else 0
                path = self.session_dir / track["filename"]
                if track["kind"] == "video":
                    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
                    if not cap or not cap.isOpened():
                        if cap:
                            cap.release()
                        cap = cv2.VideoCapture(index)
                    if not cap or not cap.isOpened():
                        raise RuntimeError(f"camera_open_failed:{index}")
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
                    cap.set(cv2.CAP_PROP_FPS, FPS)
                    writer = cv2.VideoWriter(
                        str(path), cv2.VideoWriter_fourcc(*"MJPG"), float(FPS), (WIDTH, HEIGHT)
                    )
                    if not writer.isOpened():
                        cap.release()
                        raise RuntimeError(f"video_writer_failed:{track['filename']}")
                    track.update({"cap": cap, "writer": writer, "status": "ready"})
                else:
                    if pyaudio is None:
                        raise RuntimeError("pyaudio_not_installed")
                    if self._pa is None:
                        self._pa = pyaudio.PyAudio()
                    wave_file = wave.open(str(path), "wb")
                    wave_file.setnchannels(AUDIO_CHANNELS)
                    wave_file.setsampwidth(self._pa.get_sample_size(pyaudio.paInt16))
                    wave_file.setframerate(AUDIO_RATE)
                    kwargs = {
                        "format": pyaudio.paInt16,
                        "channels": AUDIO_CHANNELS,
                        "rate": AUDIO_RATE,
                        "input": True,
                        "frames_per_buffer": AUDIO_CHUNK,
                    }
                    if raw_index is not None:
                        kwargs["input_device_index"] = index
                    stream = self._pa.open(**kwargs)
                    track.update({"stream": stream, "wave": wave_file, "status": "ready"})
            except Exception as exc:
                track["status"] = "failed"
                track["error"] = str(exc)
                if track.get("required"):
                    raise RuntimeError(
                        f"required_device_failed:{track.get('deviceId')}:{track.get('trackId')}:{exc}"
                    ) from exc

    def _start_extra_track_threads(self, session_id: str) -> None:
        self._extra_threads = []
        for track in self._extra_tracks:
            if track.get("status") != "ready":
                continue
            target = self._extra_video_loop if track["kind"] == "video" else self._extra_audio_loop
            thread = threading.Thread(
                target=target,
                args=(track,),
                daemon=True,
                name=f"CMA-{track['kind']}-{track['trackId']}-{session_id}",
            )
            self._extra_threads.append(thread)
            thread.start()

    def _extra_video_loop(self, track: Dict[str, Any]) -> None:
        interval = 1.0 / max(1, FPS)
        while not self._stop_event.is_set():
            started = time.time()
            try:
                ok, frame = track["cap"].read()
                if not ok or frame is None:
                    track["status"] = "degraded"
                    track["error"] = "frame_read_failed"
                    time.sleep(0.2)
                    continue
                if frame.shape[1] != WIDTH or frame.shape[0] != HEIGHT:
                    frame = cv2.resize(frame, (WIDTH, HEIGHT))
                track["writer"].write(frame)
                track["frameCount"] = int(track.get("frameCount") or 0) + 1
                if not track.get("firstFrameAt") and self.start_ts:
                    track["firstFrameAt"] = max(0.0, time.time() - self.start_ts)
            except Exception as exc:
                track["status"] = "degraded"
                track["error"] = str(exc)
            time.sleep(max(0.0, interval - (time.time() - started)))

    def _extra_audio_loop(self, track: Dict[str, Any]) -> None:
        while not self._stop_event.is_set():
            try:
                chunk = track["stream"].read(AUDIO_CHUNK, exception_on_overflow=False)
                track["wave"].writeframes(chunk)
                track["chunkCount"] = int(track.get("chunkCount") or 0) + 1
                if not track.get("firstChunkAt") and self.start_ts:
                    track["firstChunkAt"] = max(0.0, time.time() - self.start_ts)
            except Exception as exc:
                track["status"] = "degraded"
                track["error"] = str(exc)
                time.sleep(0.1)

    def _close_devices(self) -> None:
        for track in self._extra_tracks:
            for name, action in (
                ("stream", lambda value: (value.stop_stream(), value.close())),
                ("wave", lambda value: value.close()),
                ("writer", lambda value: value.release()),
                ("cap", lambda value: value.release()),
            ):
                value = track.pop(name, None)
                if value is not None:
                    try:
                        action(value)
                    except Exception:
                        pass
            if track.get("status") == "ready":
                track["status"] = "finalized"
        try:
            if self._audio_stream:
                self._audio_stream.stop_stream()
                self._audio_stream.close()
        except Exception:
            pass
        self._audio_stream = None

        try:
            if self._wave:
                self._wave.close()
        except Exception:
            pass
        self._wave = None

        try:
            if self._pa:
                self._pa.terminate()
        except Exception:
            pass
        self._pa = None

        try:
            if self._writer:
                self._writer.release()
        except Exception:
            pass
        self._writer = None

        try:
            if self._cap:
                self._cap.release()
        except Exception:
            pass
        self._cap = None

    def _video_loop(self) -> None:
        interval = 1.0 / max(1, FPS)
        while not self._stop_event.is_set():
            loop_start = time.time()
            try:
                if not self._cap:
                    break
                ok, frame = self._cap.read()
                if not ok or frame is None:
                    time.sleep(0.05)
                    continue

                if frame.shape[1] != WIDTH or frame.shape[0] != HEIGHT:
                    frame = cv2.resize(frame, (WIDTH, HEIGHT))

                if self._writer:
                    self._writer.write(frame)

                encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY]
                ok_j, buf = cv2.imencode(".jpg", frame, encode_param)
                if ok_j:
                    jpeg_bytes = buf.tobytes()
                    with self._preview_cond:
                        self._preview_jpeg = jpeg_bytes
                        self._preview_cond.notify_all()

                    self._video_seq += 1
                    self.frame_count += 1
                    b64 = base64.b64encode(jpeg_bytes).decode("ascii")
                    self._enqueue_uplink("video", {
                        "frame": b64,
                        "seq": self._video_seq,
                        "timestamp": int(time.time() * 1000),
                    })
            except Exception as exc:
                self.last_error = f"video: {exc}"
                app.logger.error("video loop error: %s", exc)

            elapsed = time.time() - loop_start
            sleep_for = interval - elapsed
            if sleep_for > 0:
                self._stop_event.wait(sleep_for)

    def _audio_loop(self) -> None:
        if not self._audio_stream:
            return
        while not self._stop_event.is_set():
            try:
                data = self._audio_stream.read(AUDIO_CHUNK, exception_on_overflow=False)
                if self._wave:
                    self._wave.writeframes(data)
                self._audio_seq += 1
                self.audio_chunk_count += 1
                b64 = base64.b64encode(data).decode("ascii")
                self._enqueue_uplink("audio", {
                    "chunk": b64,
                    "seq": self._audio_seq,
                    "timestamp": int(time.time() * 1000),
                })
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                self.last_error = f"audio: {exc}"
                app.logger.error("audio loop error: %s", exc)
                time.sleep(0.05)

    def _enqueue_uplink(self, kind: str, payload: Dict[str, Any]) -> None:
        if not self.backend_base or not self.session_id:
            return
        self._uplink_q.append((kind, payload))

    def _uplink_loop(
        self,
        session_id: str,
        backend_base: Optional[str],
        queue: Deque[Tuple[str, Dict[str, Any]]],
        stop_event: threading.Event,
    ) -> None:
        """断线时不停录，只积压队列；恢复后继续发送。"""
        while not stop_event.is_set() or queue:
            if not queue:
                time.sleep(0.05)
                if stop_event.is_set():
                    break
                continue

            item = queue[0]
            kind, payload = item
            ok = self._send_one(
                kind,
                payload,
                session_id=session_id,
                backend_base=backend_base,
                stop_event=stop_event,
                queue=queue,
            )
            if ok:
                # stop/session-gone may have cleared the captured queue while
                # the HTTP request was in flight.
                if queue and queue[0] is item:
                    queue.popleft()
                if self.session_id == session_id:
                    self._uplink_gap_start = None
            else:
                if self.session_id == session_id and self._uplink_gap_start is None:
                    self._uplink_gap_start = time.time()
                time.sleep(UPLINK_RETRY_SEC)

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if AGENT_KEY:
            headers["X-Child-Media-Agent-Key"] = AGENT_KEY
        return headers

    def _handle_session_gone(
        self,
        status_code: int,
        session_id: str,
        stop_event: threading.Event,
        queue: Deque[Tuple[str, Dict[str, Any]]],
    ) -> None:
        """服务端会话已不存在：丢弃积压上行并异步停录（避免在上行线程里 join 自己）。"""
        stop_event.set()
        queue.clear()
        # A late response for the previous course must never stop the current
        # course or overwrite its diagnostics.
        if self.session_id != session_id:
            return
        self.last_error = f"session_gone HTTP {status_code}"
        if self._session_gone_stopping:
            return
        self._session_gone_stopping = True
        self._stop_event.set()

        def _stop_async() -> None:
            try:
                app.logger.warning(
                    "backend session gone (HTTP %s); stopping local recording session=%s",
                    status_code,
                    self.session_id,
                )
                self.stop()
            except Exception:
                app.logger.exception("stop after session_gone failed")
            finally:
                self._session_gone_stopping = False

        threading.Thread(
            target=_stop_async, daemon=True, name="CMA-SessionGone"
        ).start()

    def _send_one(
        self,
        kind: str,
        payload: Dict[str, Any],
        *,
        session_id: str,
        backend_base: Optional[str],
        stop_event: threading.Event,
        queue: Deque[Tuple[str, Dict[str, Any]]],
    ) -> bool:
        if not backend_base or not session_id:
            return True  # 无后端则丢弃上行（本地仍在录）
        try:
            if kind == "video":
                url = f"{backend_base}/api/media/{session_id}/frames"
            else:
                url = f"{backend_base}/api/media/{session_id}/audio-chunks"
            resp = requests.post(url, json=payload, headers=self._headers(), timeout=5)
            if resp.status_code in (404, 410):
                self._handle_session_gone(
                    resp.status_code, session_id, stop_event, queue
                )
                return True  # 丢弃本条，不再重试
            if resp.status_code == 200:
                body = resp.json() if resp.content else {}
                if body.get("error") == "session_gone":
                    self._handle_session_gone(resp.status_code)
                    return True
                return bool(body.get("ok", True))
            if self.session_id == session_id:
                self.last_error = f"uplink HTTP {resp.status_code}"
            return False
        except Exception as exc:
            if self.session_id == session_id:
                self.last_error = f"uplink: {exc}"
            return False

    def _upload_archive(
        self,
        session_id: str,
        video_path: Path,
        audio_path: Optional[Path],
        duration: Optional[float],
        backend_base: Optional[str],
        tracks: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        base = (backend_base or self.backend_base or DEFAULT_BACKEND or "").rstrip("/")
        if not base:
            self._set_upload_result(session_id, "skipped_no_backend")
            return {"ok": False, "error": "no backendBaseUrl"}

        self._set_upload_result(session_id, "uploading")
        # 给服务端 MediaService.stop 一点时间释放文件句柄
        time.sleep(1.0)
        url = f"{base}/api/media/{session_id}/upload"
        headers = {}
        if AGENT_KEY:
            headers["X-Child-Media-Agent-Key"] = AGENT_KEY

        data = {}
        if duration is not None:
            data["duration"] = str(duration)
        if video_path and video_path.exists():
            data["sha256_video"] = _sha256_file(video_path)
        if audio_path and audio_path.exists():
            data["sha256_audio"] = _sha256_file(audio_path)
        track_uploads = []
        for track in tracks or []:
            filename = str(track.get("filename") or "")
            track_id = str(track.get("trackId") or "")
            path = (video_path.parent if video_path else get_data_dir()) / filename
            if not track_id or not filename or not path.is_file():
                continue
            item = dict(track)
            item["sha256"] = _sha256_file(path)
            item["sizeBytes"] = path.stat().st_size
            track_uploads.append((item, path))
        if track_uploads:
            data["trackManifest"] = json.dumps(
                [item for item, _ in track_uploads], ensure_ascii=False
            )

        expected_checksums = {}
        if data.get("sha256_video"):
            expected_checksums["video"] = data["sha256_video"]
        if data.get("sha256_audio"):
            expected_checksums["audio"] = data["sha256_audio"]
        for item, _ in track_uploads:
            expected_checksums[f"track:{item['trackId']}"] = item["sha256"]

        # A prior request can have reached disk while its HTTP acknowledgement
        # was lost.  Confirm by checksum before retransmitting a large archive.
        confirmed = self._confirm_archive_upload(base, session_id, expected_checksums)
        if confirmed:
            self._set_upload_result(session_id, "completed")
            return {
                "ok": True,
                "sessionId": session_id,
                "confirmedAfterLostResponse": True,
            }

        last_err = None
        for attempt in range(5):
            files = {}
            opened = []
            try:
                if video_path and video_path.exists():
                    fh = open(video_path, "rb")
                    opened.append(fh)
                    files["video"] = (video_path.name, fh, "video/x-msvideo")
                if audio_path and audio_path.exists():
                    fh = open(audio_path, "rb")
                    opened.append(fh)
                    files["audio"] = (audio_path.name, fh, "audio/wav")
                for item, path in track_uploads:
                    fh = open(path, "rb")
                    opened.append(fh)
                    mime = "video/x-msvideo" if item.get("kind") == "video" else "audio/wav"
                    files[f"track__{item['trackId']}"] = (path.name, fh, mime)
                if not files:
                    self._set_upload_result(
                        session_id, "failed", "no local media files"
                    )
                    return {"ok": False, "error": "no local media files"}

                resp = requests.post(
                    url, files=files, data=data, headers=headers, timeout=120
                )
                if resp.status_code == 200:
                    body = resp.json() if resp.content else {}
                    if body.get("ok"):
                        self._set_upload_result(session_id, "completed")
                        return body
                last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except Exception as exc:
                last_err = str(exc)
            finally:
                for fh in opened:
                    try:
                        fh.close()
                    except Exception:
                        pass
            if self._confirm_archive_upload(base, session_id, expected_checksums):
                self._set_upload_result(session_id, "completed")
                return {
                    "ok": True,
                    "sessionId": session_id,
                    "confirmedAfterLostResponse": True,
                }
            time.sleep(1.5 * (attempt + 1))

        self._set_upload_result(session_id, "failed", last_err)
        return {"ok": False, "error": last_err}

    def _set_upload_result(
        self,
        session_id: str,
        upload_state: str,
        error: Optional[str] = None,
    ) -> None:
        """Keep a late archive worker from overwriting a newer course status."""
        with self._lock:
            if self.session_id != session_id:
                return
            self.upload_state = upload_state
            if error is not None:
                self.last_error = error

    def _confirm_archive_upload(
        self,
        base: str,
        session_id: str,
        expected_checksums: Dict[str, str],
    ) -> bool:
        if not expected_checksums:
            return False
        try:
            resp = requests.get(
                f"{base}/api/media/{session_id}/status",
                params={"includeArchive": "1"},
                headers=self._headers(),
                timeout=5,
            )
            if resp.status_code != 200:
                return False
            archive = (resp.json() or {}).get("archive") or {}
            actual = archive.get("checksums") or {}
            return bool(archive.get("completed")) and all(
                actual.get(name) == digest
                for name, digest in expected_checksums.items()
            )
        except Exception:
            return False

    def get_preview_jpeg(self, timeout: float = 1.0) -> Optional[bytes]:
        with self._preview_cond:
            if self._preview_jpeg is None:
                self._preview_cond.wait(timeout=timeout)
            return self._preview_jpeg


state = MediaRecorderState()


def _probe_video(index: int) -> Dict[str, Any]:
    cap = None
    try:
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not cap or not cap.isOpened():
            if cap:
                cap.release()
            cap = cv2.VideoCapture(index)
        if not cap or not cap.isOpened():
            return {"connected": False, "error": f"camera_open_failed:{index}"}
        ok, frame = cap.read()
        if not ok or frame is None:
            return {"connected": False, "error": f"camera_first_frame_failed:{index}"}
        return {"connected": True, "sample": "first_frame", "index": index}
    except Exception as exc:
        return {"connected": False, "error": str(exc), "index": index}
    finally:
        if cap:
            cap.release()


def _probe_audio(index: Optional[int]) -> Dict[str, Any]:
    if pyaudio is None:
        return {"connected": False, "error": "pyaudio_not_installed", "index": index}
    pa = None
    stream = None
    try:
        pa = pyaudio.PyAudio()
        kwargs = {
            "format": pyaudio.paInt16,
            "channels": AUDIO_CHANNELS,
            "rate": AUDIO_RATE,
            "input": True,
            "frames_per_buffer": AUDIO_CHUNK,
        }
        if index is not None:
            kwargs["input_device_index"] = index
        stream = pa.open(**kwargs)
        sample = stream.read(AUDIO_CHUNK, exception_on_overflow=False)
        if not sample:
            return {"connected": False, "error": "microphone_first_chunk_empty", "index": index}
        return {"connected": True, "sample": "first_audio_chunk", "index": index}
    except Exception as exc:
        return {"connected": False, "error": str(exc), "index": index}
    finally:
        try:
            if stream:
                stream.stop_stream()
                stream.close()
        finally:
            if pa:
                pa.terminate()


@app.get("/health")
def health():
    return jsonify(state.status())


@app.get("/ready")
def ready():
    """Operational readiness used by the packaged idempotent launcher."""
    status = state.status()
    failures = []
    if not status.get("backendUrl"):
        failures.append("backend_url_missing")
    if not status.get("backendRegistered"):
        failures.append("backend_not_registered")
    if status.get("protocolCompatible") is not True:
        failures.append(
            status.get("protocolCompatibilityReason")
            or "protocol_compatibility_pending"
        )
    data_dir = get_data_dir()
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        if not os.access(str(data_dir), os.W_OK):
            failures.append("data_dir_not_writable")
    except OSError:
        failures.append("data_dir_unavailable")
    payload = {
        **status,
        "ok": not failures,
        "ready": not failures,
        "failures": failures,
    }
    return jsonify(payload), 200 if not failures else 503


@app.post("/devices/check")
def check_devices():
    """Open each requested source and require a real first frame/chunk."""
    if not check_agent_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    payload = request.get_json(silent=True) or {}
    requested = payload.get("devices") or []
    if not isinstance(requested, list):
        return jsonify({"ok": False, "error": "devices_must_be_array"}), 400
    checks = []
    defaults = [
        {"deviceId": "default.child.camera", "kind": "video", "selector": {"index": CAMERA_INDEX}},
        {"deviceId": "default.child.microphone", "kind": "audio", "selector": {}},
    ]
    for device in defaults + requested:
        kind = str(device.get("kind") or "")
        selector = device.get("selector") if isinstance(device.get("selector"), dict) else {}
        raw_index = selector.get("index", selector.get("deviceIndex"))
        try:
            index = int(raw_index) if raw_index is not None else None
        except (TypeError, ValueError):
            checks.append({**device, "connected": False, "error": "device_index_invalid"})
            continue
        result = _probe_video(CAMERA_INDEX if index is None else index) if kind == "video" else _probe_audio(index)
        checks.append({"deviceId": device.get("deviceId"), "kind": kind, **result})
    return jsonify({"ok": True, "checks": checks, "checkedAt": datetime.now().isoformat(timespec="seconds")})


@app.post("/record/start")
def record_start():
    if not check_agent_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    session_id = data.get("sessionId")
    if not session_id:
        return jsonify({"ok": False, "error": "sessionId required"}), 400
    backend = data.get("backendBaseUrl") or data.get("backendUrl")
    recording_mode = data.get("recordingMode") or "continuous"
    human_dir_name = data.get("humanDirName") or data.get("human_dir_name")
    capture_devices = data.get("captureDevices") or data.get("capture_devices") or []
    if not isinstance(capture_devices, list):
        return jsonify({"ok": False, "error": "captureDevices must be an array"}), 400
    try:
        result = state.start(
            str(session_id),
            backend_base=backend,
            recording_mode=str(recording_mode),
            human_dir_name=str(human_dir_name) if human_dir_name else None,
            capture_devices=capture_devices,
        )
        app.logger.info(
            "[RobotRuntime] start session=%s human=%s mode=%s dir=%s kept=%s",
            result.get("sessionId"),
            result.get("humanDirName"),
            result.get("recordingMode"),
            result.get("sessionDir"),
            result.get("kept"),
        )
        return jsonify(result)
    except Exception as exc:
        app.logger.exception("record start failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.post("/record/stop")
def record_stop():
    if not check_agent_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        result = state.stop()
        app.logger.info(
            "[RobotRuntime] stop session=%s upload=%s",
            result.get("sessionId"),
            (result.get("upload") or {}).get("ok"),
        )
        return jsonify(result)
    except Exception as exc:
        app.logger.exception("record stop failed")
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.get("/preview.mjpeg")
def preview_mjpeg():
    boundary = b"frame"

    def generate():
        while True:
            jpeg = state.get_preview_jpeg(timeout=1.0)
            if jpeg is None:
                blank = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
                ok, buf = cv2.imencode(".jpg", blank, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
                jpeg = buf.tobytes() if ok else b""
                time.sleep(0.2)
            yield (
                b"--" + boundary + b"\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                + jpeg + b"\r\n"
            )

    return Response(
        generate(),
        mimetype=f"multipart/x-mixed-replace; boundary={boundary.decode()}",
    )


@app.post("/osc/frame")
def osc_frame():
    if not check_agent_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    pose = data.get("pose", {})
    move_ms = int(data.get("moveMs", DEFAULT_MOVE_MS))
    try:
        send_pose(pose, move_ms)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    app.logger.info("[RobotRuntime] frame requestId=%s moveMs=%s", data.get("requestId"), move_ms)
    return jsonify({"ok": True, "requestId": data.get("requestId")})


@app.post("/osc/play")
def osc_play():
    if not check_agent_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    frames = data.get("frames", [])
    if not isinstance(frames, list) or not frames:
        return jsonify({"ok": False, "error": "frames required"}), 400
    request_id = str(data.get("requestId") or int(time.time() * 1000))
    playback_state.start(request_id, frames, neutral_pose=data.get("neutralPose"))
    app.logger.info("[RobotRuntime] play requestId=%s frames=%s", request_id, len(frames))
    return jsonify({
        "ok": True,
        "requestId": request_id,
        "accepted": True,
        "frameCount": len(frames),
    })


@app.post("/behavior/prepare")
def behavior_prepare():
    """Stage a correlated motion before the shared multimodal anchor."""
    global _prepared_motion
    if not check_agent_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    envelope, error = _behavior_envelope(data, modality="motion")
    if error:
        return jsonify({"ok": False, "ready": False, "error": error}), 400
    frames = data.get("frames")
    if not isinstance(frames, list) or not frames:
        return jsonify({"ok": False, "ready": False, "error": "frames required"}), 400
    with _prepared_motion_lock:
        expired_behavior_id = _expire_prepared_motion_locked()
        if expired_behavior_id:
            app.logger.warning(
                "[RobotRuntime] expired abandoned prepared behavior behaviorId=%s",
                expired_behavior_id,
            )
        if _prepared_motion:
            current = _prepared_motion["envelope"]
            if current == envelope:
                return jsonify({
                    "ok": True,
                    "ready": True,
                    "idempotentReplay": True,
                    "envelope": current,
                    "runtimeEpochMs": int(time.time() * 1000),
                })
            if current.get("sessionId") != envelope.get("sessionId"):
                app.logger.warning(
                    "[RobotRuntime] superseding prepared behavior old=%s new=%s",
                    current.get("behaviorId"),
                    envelope.get("behaviorId"),
                )
                _prepared_motion = None
            else:
                return jsonify({
                    "ok": False,
                    "ready": False,
                    "error": "another_behavior_prepared",
                    "activeBehaviorId": current.get("behaviorId"),
                }), 409
        _prepared_motion = {
            "envelope": envelope,
            "frames": frames,
            "neutralPose": data.get("neutralPose"),
            "motionName": data.get("motionName"),
            "preparedAtRuntimeMs": int(time.time() * 1000),
            "expiresAtRuntimeMs": int(time.time() * 1000) + PREPARED_MOTION_TTL_MS,
        }
    app.logger.info(
        "[RobotRuntime] behavior prepared behaviorId=%s requestId=%s sessionId=%s frames=%s",
        envelope["behaviorId"], envelope["requestId"], envelope["sessionId"], len(frames),
    )
    return jsonify({
        "ok": True,
        "ready": True,
        "idempotentReplay": False,
        "envelope": envelope,
        "runtimeEpochMs": int(time.time() * 1000),
    })


@app.post("/behavior/commit")
def behavior_commit():
    """Commit the prepared motion; Runtime waits locally for the translated anchor."""
    global _prepared_motion, _active_motion_envelope
    if not check_agent_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    envelope, error = _behavior_envelope(data, modality="motion")
    if error:
        return jsonify({"ok": False, "committed": False, "error": error}), 400
    try:
        start_at_runtime_ms = int(data.get("startAtRuntimeMs"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "committed": False, "error": "runtime_anchor_invalid"}), 400
    with _prepared_motion_lock:
        prepared = _prepared_motion
        if not prepared or prepared.get("envelope") != envelope:
            return jsonify({"ok": False, "committed": False, "error": "behavior_not_prepared"}), 409
        _prepared_motion = None
        _active_motion_envelope = dict(envelope)
    playback_state.start(
        envelope["requestId"],
        prepared["frames"],
        start_at_epoch_ms=start_at_runtime_ms,
        on_event=lambda status, reason: _emit_motion_event(envelope, status, reason),
        neutral_pose=prepared.get("neutralPose"),
    )
    app.logger.info(
        "[RobotRuntime] behavior committed behaviorId=%s requestId=%s startAtServerMs=%s startAtRuntimeMs=%s",
        envelope["behaviorId"], envelope["requestId"], envelope["startAtServerMs"], start_at_runtime_ms,
    )
    return jsonify({
        "ok": True,
        "committed": True,
        "envelope": envelope,
        "startAtRuntimeMs": start_at_runtime_ms,
        "runtimeEpochMs": int(time.time() * 1000),
    })


@app.post("/behavior/cancel")
def behavior_cancel():
    global _prepared_motion, _active_motion_envelope
    if not check_agent_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    envelope, error = _behavior_envelope(data, modality="motion")
    if error:
        return jsonify({"ok": False, "cancelled": False, "error": error}), 400
    cancel_prepared = False
    cancel_active = False
    with _prepared_motion_lock:
        if _prepared_motion and _prepared_motion.get("envelope") == envelope:
            _prepared_motion = None
            cancel_prepared = True
        if _active_motion_envelope == envelope:
            cancel_active = True
    if not cancel_prepared and not cancel_active:
        return jsonify({
            "ok": False,
            "cancelled": False,
            "error": "behavior_identity_mismatch",
            "behaviorId": envelope["behaviorId"],
        }), 409
    if cancel_active:
        playback_state.stop()
        with _prepared_motion_lock:
            if _active_motion_envelope == envelope:
                _active_motion_envelope = None
    return jsonify({
        "ok": True,
        "cancelled": True,
        "behaviorId": envelope["behaviorId"],
        "requestId": envelope["requestId"],
    })


@app.get("/behavior/status/<behavior_id>")
def behavior_status(behavior_id: str):
    """Read-only Runtime-side timing evidence for one behavior transaction."""
    with _prepared_motion_lock:
        _expire_prepared_motion_locked()
        prepared = (
            dict(_prepared_motion)
            if _prepared_motion
            and _prepared_motion["envelope"].get("behaviorId") == behavior_id
            else None
        )
        events = [
            dict(item)
            for item in _motion_event_history
            if item.get("behaviorId") == behavior_id
        ]
    if prepared:
        prepared.pop("frames", None)
    return jsonify({
        "ok": True,
        "behaviorId": behavior_id,
        "prepared": prepared,
        "currentRequestId": playback_state.current_request_id,
        "events": events,
    })


@app.post("/osc/stop")
def osc_stop():
    if not check_agent_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.get_json(silent=True) or {}
    request_id = str(data.get("requestId") or "") or None
    expected_request_id = request_id if data.get("onlyIfCurrent") is True else None
    stopped = playback_state.stop(expected_request_id=expected_request_id)
    app.logger.info(
        "[RobotRuntime] stop requestId=%s conditional=%s stopped=%s current=%s",
        request_id,
        expected_request_id is not None,
        stopped,
        playback_state.current_request_id,
    )
    return jsonify({
        "ok": True,
        "requestId": request_id,
        "stopped": stopped,
        "currentRequestId": playback_state.current_request_id,
    })


@app.post("/register/now")
def register_now():
    """立即向后端注册；可附带 backendUrl / runtimeKey，并写入本地配置。"""
    # 运维 UI 本机调用：无密钥时也允许改配置（仅本机 127.0.0.1 场景）
    # 若配置了 AGENT_KEY，仍要求带 key（远程调用）
    if not _ui_local_ok():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    backend = data.get("backendUrl") or data.get("backendBaseUrl")
    if backend:
        register_client.set_backend_url(str(backend), persist=True)
    if "runtimeKey" in data and data.get("runtimeKey") is not None:
        register_client.set_runtime_key(str(data.get("runtimeKey") or ""), persist=True)
    ok = register_client.register_once()
    return jsonify({"ok": ok, **register_client.get_registry_status()})


@app.get("/ui")
def ui_page():
    return send_from_directory(str(STATIC_DIR), "ui.html")


@app.get("/assets/emotions/manifest.json")
def local_emotion_manifest():
    root = _emotion_assets_dir()
    files = []
    if root.is_dir():
        files = sorted(
            item.name
            for item in root.iterdir()
            if item.is_file() and item.suffix.lower() in {'.mp4', '.gif', '.webm', '.ogg'}
        )
    return jsonify({
        "ok": True,
        "local": True,
        "count": len(files),
        "emotions": files,
    })


@app.route("/assets/emotions/prewarm/status", methods=["GET", "POST"])
def local_emotion_prewarm_status():
    if request.method == "POST":
        if not _ui_local_ok():
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        payload = request.get_json(silent=True) or {}
        phase = str(payload.get("phase") or "preparing").strip().lower()
        if phase not in {"waiting", "preparing", "ready", "failed"}:
            return jsonify({"ok": False, "error": "invalid_phase"}), 400
        instance_id = str(payload.get("instanceId") or "").strip() or None
        with _emotion_prewarm_lock:
            if instance_id != _emotion_prewarm.get("instanceId"):
                _emotion_prewarm.update({
                    "instanceId": instance_id,
                    "phase": "waiting",
                    "total": 0,
                    "completed": 0,
                    "current": None,
                    "failed": [],
                })
            total = max(0, int(payload.get("total") or 0))
            completed = min(total, max(0, int(payload.get("completed") or 0)))
            failed = payload.get("failed") if isinstance(payload.get("failed"), list) else []
            _emotion_prewarm.update({
                "phase": phase,
                "total": total,
                "completed": completed,
                "current": str(payload.get("current") or "").strip() or None,
                "failed": [str(item) for item in failed[:50]],
                "updatedAt": int(time.time() * 1000),
            })
    return jsonify({"ok": True, **emotion_prewarm_status()})


@app.get("/assets/emotions/<path:filename>")
def local_emotion_asset(filename: str):
    root = _emotion_assets_dir()
    if not root.is_dir():
        return jsonify({"ok": False, "error": "local_emotions_missing"}), 404
    response = send_from_directory(str(root), filename, conditional=True)
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response


@app.get("/ui/status.json")
def ui_status():
    return jsonify(state.status())


def _ui_local_ok() -> bool:
    """Allow local UI without key; remote still needs key when configured."""
    remote = request.remote_addr not in ("127.0.0.1", "::1", "localhost")
    if AGENT_KEY and remote and not check_agent_key():
        return False
    if AGENT_KEY and not remote:
        provided = (
            request.headers.get("X-Robot-Runtime-Key")
            or request.headers.get("X-Child-Media-Agent-Key")
            or request.headers.get("X-Robot-Agent-Key")
            or ""
        )
        if provided and provided != AGENT_KEY:
            return False
    return True


def _resolve_open_child_lan_mic_script() -> Optional[Path]:
    """Locate Open-ChildLanMic.ps1 for source installs or packaged Runtime."""
    candidates: List[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "Open-ChildLanMic.ps1")
        appdata = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EIArt" / "robot_runtime"
        candidates.append(appdata / "Open-ChildLanMic.ps1")
    else:
        # robot_runtime/agent.py → server_demo/scripts/...
        pkg_root = Path(__file__).resolve().parent
        repo_root = pkg_root.parent
        candidates.append(repo_root / "scripts" / "Open-ChildLanMic.ps1")
        candidates.append(pkg_root / "packaging" / "Open-ChildLanMic.ps1")
    for path in candidates:
        if path.is_file():
            return path
    return None


def _backend_child_target(backend_url: str) -> Tuple[str, str, int]:
    """Return (child_url, lan_host, port) from a backend base URL."""
    base = (backend_url or "").rstrip("/")
    parsed = urlparse(base if "://" in base else f"http://{base}")
    host = parsed.hostname or ""
    if parsed.port:
        port = int(parsed.port)
    elif parsed.scheme == "https":
        port = 443
    else:
        port = 8080
    scheme = parsed.scheme or "http"
    child_url = f"{scheme}://{host}:{port}/child" if host else f"{base}/child"
    return child_url, host, port


def open_child_lan_mic(backend_url: str) -> Dict[str, Any]:
    """
    Launch Open-ChildLanMic.ps1 so /child can use mic over LAN HTTP.
    Falls back to webbrowser.open if the script is missing or exits non-zero.
    """
    child_url, lan_host, port = _backend_child_target(backend_url)
    if not lan_host:
        return {"ok": False, "error": "backend URL has no host", "url": child_url}

    script = _resolve_open_child_lan_mic_script()
    script_error: Optional[str] = None
    if script and sys.platform == "win32":
        log_path = (
            Path(os.environ.get("TEMP") or os.environ.get("TMP") or ".")
            / "eiart-open-child-lan-mic.log"
        )
        try:
            creationflags = (
                subprocess.CREATE_NO_WINDOW
                if hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            )
            with open(log_path, "w", encoding="utf-8") as logf:
                logf.write(
                    f"script={script}\nLanHost={lan_host} Port={port}\nurl={child_url}\n---\n"
                )
                logf.flush()
                proc = subprocess.Popen(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(script),
                        "-LanHost",
                        lan_host,
                        "-Port",
                        str(port),
                    ],
                    cwd=str(script.parent),
                    stdin=subprocess.DEVNULL,
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )
            try:
                proc.wait(timeout=25)
            except subprocess.TimeoutExpired:
                # Start-Process should return quickly; treat hang as failure.
                try:
                    proc.kill()
                except Exception:
                    pass
                script_error = f"Open-ChildLanMic.ps1 timed out (log: {log_path})"
            else:
                if proc.returncode == 0:
                    return {
                        "ok": True,
                        "mode": "lan_mic_script",
                        "script": str(script),
                        "lanHost": lan_host,
                        "port": port,
                        "url": child_url,
                        "log": str(log_path),
                    }
                tail = ""
                try:
                    tail = log_path.read_text(encoding="utf-8", errors="replace")[-800:]
                except Exception:
                    pass
                script_error = (
                    f"Open-ChildLanMic.ps1 exit {proc.returncode}"
                    + (f": {tail.strip()}" if tail.strip() else f" (log: {log_path})")
                )
            app.logger.warning("[RobotRuntime] %s", script_error)
        except Exception as exc:
            script_error = str(exc)
            app.logger.warning("[RobotRuntime] Open-ChildLanMic.ps1 failed: %s", exc)
    elif not script:
        script_error = "Open-ChildLanMic.ps1 not found next to RobotRuntime.exe"

    try:
        webbrowser.open(child_url)
        hint = (
            "未能用 LAN mic 脚本打开，已用普通浏览器打开（局域网 HTTP 下对话麦克风通常不可用）。"
            + (f" 原因: {script_error}" if script_error else "")
            + " 请确认 Open-ChildLanMic.ps1 与 RobotRuntime.exe 同目录，或手动运行该脚本并传入后端 -LanHost。"
        )
        return {
            "ok": True,
            "mode": "browser_fallback",
            "script": str(script) if script else None,
            "lanHost": lan_host,
            "port": port,
            "url": child_url,
            "hint": hint,
            "scriptError": script_error,
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "mode": "browser_fallback",
            "url": child_url,
            "scriptError": script_error,
        }


@app.post("/ui/open-child")
def ui_open_child():
    """Ops UI: open /child via LAN-mic helper script (or browser fallback)."""
    if not _ui_local_ok():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    status = register_client.get_registry_status()
    backend = (
        body.get("backendUrl")
        or body.get("backendBaseUrl")
        or status.get("backendPublicUrl")
        or status.get("backendUrl")
        or register_client.BACKEND_URL
        or ""
    )
    backend = str(backend).rstrip("/")
    if not backend:
        return jsonify({"ok": False, "error": "backend URL not set"}), 400
    result = open_child_lan_mic(backend)
    code = 200 if result.get("ok") else 400
    return jsonify(result), code


@app.post("/ui/open-emotion")
def ui_open_emotion():
    if not _ui_local_ok():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    body = request.get_json(silent=True) or {}
    status = register_client.get_registry_status()
    backend = str(
        body.get("backendUrl")
        or body.get("backendBaseUrl")
        or status.get("backendPublicUrl")
        or status.get("backendUrl")
        or register_client.BACKEND_URL
        or ""
    ).rstrip("/")
    if not backend:
        return jsonify({"ok": False, "error": "backend URL not set"}), 400
    url = f"{backend}/robot/emotion"
    try:
        webbrowser.open(url)
        return jsonify({"ok": True, "url": url})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc), "url": url}), 500


@app.post("/config/media-dir")
def config_media_dir():
    if not _ui_local_ok():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if state.recording:
        return jsonify({"ok": False, "error": "recording in progress; stop first"}), 409
    if not data_dir_editable():
        return jsonify({
            "ok": False,
            "error": "CHILD_MEDIA_DATA_DIR env is set; unset it to change from UI",
            "dataDir": str(get_data_dir()),
        }), 400
    data = request.get_json(silent=True) or {}
    path = data.get("path") or data.get("mediaDataDir")
    if not path:
        return jsonify({"ok": False, "error": "path required"}), 400
    try:
        new_dir = set_data_dir(str(path), persist=True)
        return jsonify({
            "ok": True,
            "dataDir": str(new_dir),
            "dataDirEditable": data_dir_editable(),
            "configPath": str(register_client.config_path()),
        })
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@app.get("/update/check")
def update_check():
    if not _ui_local_ok():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    data = request.args
    backend = data.get("backendUrl") or None
    result = runtime_updater.check_update(backend)
    status_code = 200 if result.get("ok") else 400
    return jsonify(result), status_code


@app.post("/update/apply")
def update_apply():
    if not _ui_local_ok():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if state.recording:
        return jsonify({"ok": False, "error": "recording in progress; stop first"}), 409
    body = request.get_json(silent=True) or {}
    backend = body.get("backendUrl") or None
    prepared = runtime_updater.download_and_prepare_update(backend)
    if not prepared.get("ok"):
        return jsonify(prepared), 400
    if not runtime_updater.is_frozen():
        return jsonify({
            "ok": False,
            "error": prepared.get("error")
            or "auto-update only for RobotRuntime.exe; source mode: re-pack and replace manually",
            "preparedDir": prepared.get("preparedDir"),
            "hint": "开发/源码模式请重新运行 scripts/pack_robot_release.ps1，将 zip 放到服务器后在测试机用 exe 包更新。",
        }), 400
    swap = runtime_updater.launch_swap_and_exit(prepared)
    if not swap.get("ok"):
        return jsonify({**prepared, **swap}), 400

    def _exit_soon() -> None:
        time.sleep(0.8)
        os._exit(0)

    threading.Thread(target=_exit_soon, daemon=True, name="RobotRuntime-UpdateExit").start()
    return jsonify({
        "ok": True,
        "restarting": True,
        "message": "update prepared; process will restart shortly",
        **swap,
        "preparedDir": prepared.get("preparedDir"),
    })


if __name__ == "__main__":
    runtime_updater.cleanup_stale_update_files()
    print(f"[RobotRuntime] listen on http://{AGENT_HOST}:{AGENT_PORT}")
    print(f"[RobotRuntime] data dir {get_data_dir()}")
    print(f"[RobotRuntime] version { _runtime_version() }")
    print(f"[RobotRuntime] UI http://127.0.0.1:{AGENT_PORT}/ui")
    cfg = register_client.get_registry_status()
    if cfg.get("backendUrl"):
        print(f"[RobotRuntime] backend {cfg.get('backendUrl')}")
    else:
        print("[RobotRuntime] backend URL 未设置 — 请在 /ui 填写并「应用并注册」")
    print(f"[RobotRuntime] config {cfg.get('configPath')}")
    register_client.start_background(AGENT_PORT)
    app.run(host=AGENT_HOST, port=AGENT_PORT, debug=False, threaded=True)
