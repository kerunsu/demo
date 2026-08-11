"""Minimal, monotonic recording gate used before a class starts.

Starting a class is a media lifecycle operation, not a resource audit.  The
only blocking condition is proof that the formal recording session exists and
the server has accepted a real video sample.  Course assets, audio, analysis,
presence and optional devices are deliberately outside this gate and may be
diagnosed by their own pages after the class is running.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app.utils.logger import setup_logger

logger = setup_logger("readiness_service")

RECORDING_MODULE = "M2"
MODULE_LABELS = {RECORDING_MODULE: "本场录制与视频采集"}

DEFAULT_TIMEOUT_MS = 30_000
MEDIA_META_STALE_MS = 15_000
MIN_WARMUP_FRAMES = 1


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class ModuleState:
    """Wire-compatible view of the one blocking recording module."""

    module_id: str
    status: str = "pending"  # pending|running|success|failed|degraded
    detail: str = ""
    progress01: float = 0.0
    failed_paths: List[str] = field(default_factory=list)
    updated_at_ms: int = field(default_factory=_now_ms)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "moduleId": self.module_id,
            "name": MODULE_LABELS.get(self.module_id, self.module_id),
            "status": self.status,
            "detail": self.detail,
            "progress01": max(0.0, min(1.0, float(self.progress01))),
            "failedPaths": list(self.failed_paths),
            "updatedAtMs": self.updated_at_ms,
            "ageMs": max(0, _now_ms() - self.updated_at_ms),
        }


@dataclass
class ReadinessGate:
    training_session_id: str
    student_id: int
    teacher_sid: str
    items: List[Dict[str, Any]] = field(default_factory=list)
    modules: Dict[str, ModuleState] = field(default_factory=dict)
    started_at_ms: int = field(default_factory=_now_ms)
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    generation: int = 1
    status: str = "STARTING"  # STARTING|RECORDING_CONFIRMED|FAILED|CANCELLED
    session_id: Optional[str] = None
    capture_start_attempted: bool = False
    capture_started: bool = False
    server_sample_accepted: bool = False
    cancelled: bool = False

    def __post_init__(self) -> None:
        if not self.modules:
            self.modules = {
                RECORDING_MODULE: ModuleState(
                    RECORDING_MODULE, "running", "正在启动本场录制", 0.1
                )
            }
        elif RECORDING_MODULE not in self.modules:
            self.modules[RECORDING_MODULE] = ModuleState(RECORDING_MODULE)

    @property
    def deadline_at_ms(self) -> int:
        return self.started_at_ms + max(1000, self.timeout_ms)

    def snapshot(self) -> Dict[str, Any]:
        module = self.modules[RECORDING_MODULE]
        return {
            "trainingSessionId": self.training_session_id,
            "studentId": self.student_id,
            "sessionId": self.session_id,
            "ok": self.status == "RECORDING_CONFIRMED",
            "status": self.status,
            "criticalModules": [RECORDING_MODULE],
            "degraded": [],
            "failed": [RECORDING_MODULE] if self.status == "FAILED" else [],
            "modules": [module.to_dict()],
            "progress01": module.progress01,
            "anyRunning": self.status == "STARTING",
            "anyFailed": self.status == "FAILED",
            "preflightOnly": self.status == "STARTING" and not self.capture_started,
            "captureStarted": self.capture_started,
            "serverSampleAccepted": self.server_sample_accepted,
            "forced": False,
            "forceReason": None,
            "startedAtMs": self.started_at_ms,
            "elapsedMs": max(0, _now_ms() - self.started_at_ms),
            "timeoutMs": self.timeout_ms,
            "deadlineAtMs": self.deadline_at_ms,
            # Kept small and deterministic. Resource selection is performed on
            # demand by the child playback path, never in the start gate.
            "plan": {"items": len(self.items)},
        }


EmitFn = Callable[[str, Dict[str, Any], Optional[str]], None]
CaptureStartFn = Callable[[str], Dict[str, Any]]


class ReadinessService:
    """One idempotent recording coordinator per training session."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._gates: Dict[str, ReadinessGate] = {}
        self._emit: Optional[EmitFn] = None
        self._child_emit: Optional[Callable[[str, Dict[str, Any]], None]] = None
        self._capture_start_callback: Optional[CaptureStartFn] = None

    def set_emitter(self, emit_fn: EmitFn, socketio=None) -> None:
        self._emit = emit_fn

    def set_capture_start_callback(self, callback: Optional[CaptureStartFn]) -> None:
        self._capture_start_callback = callback

    def set_child_emitter(self, callback: Optional[Callable[[str, Dict[str, Any]], None]]) -> None:
        self._child_emit = callback

    def _emit_to_teacher(self, event: str, payload: Dict[str, Any], teacher_sid: str) -> None:
        if not self._emit:
            return
        try:
            self._emit(event, payload, teacher_sid)
        except Exception:
            logger.exception("readiness emit failed: %s", event)

    def _push(self, gate: ReadinessGate, event: str = "readiness_update") -> None:
        self._emit_to_teacher(
            event,
            {**gate.snapshot(), "moduleId": RECORDING_MODULE,
             "status": gate.modules[RECORDING_MODULE].status,
             "detail": gate.modules[RECORDING_MODULE].detail},
            gate.teacher_sid,
        )

    def get_gate(self, training_session_id: str) -> Optional[ReadinessGate]:
        with self._lock:
            return self._gates.get(str(training_session_id))

    def get_active_gate(self) -> Optional[ReadinessGate]:
        with self._lock:
            active = [g for g in self._gates.values() if not g.cancelled]
            return max(active, key=lambda g: g.started_at_ms) if active else None

    def cancel(self, training_session_id: Optional[str] = None, student_id: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            targets = []
            if training_session_id and str(training_session_id) in self._gates:
                targets = [str(training_session_id)]
            elif student_id is not None:
                targets = [tid for tid, g in self._gates.items() if g.student_id == int(student_id)]
            for tid in targets:
                gate = self._gates.pop(tid)
                gate.cancelled = True
                gate.status = "CANCELLED"
                gate.modules[RECORDING_MODULE].status = "degraded"
            return {"success": True, "cancelled": targets}

    def start(self, teacher_sid: str, data: Dict[str, Any]) -> Dict[str, Any]:
        student = data.get("studentId") or data.get("student_id")
        training = data.get("trainingSessionId") or data.get("training_session_id")
        items = data.get("items") or []
        if student is None:
            return {"success": False, "error": "missing_student_id"}
        if not training:
            return {"success": False, "error": "missing_training_session_id"}
        if not items:
            return {"success": False, "error": "missing_items"}
        training = str(training)
        student = int(student)
        with self._lock:
            existing = self._gates.get(training)
            if existing and not existing.cancelled and existing.student_id == student:
                if existing.status == "FAILED" and bool(data.get("retry")):
                    existing.status = "STARTING"
                    existing.started_at_ms = _now_ms()
                    existing.session_id = None
                    existing.capture_start_attempted = False
                    existing.capture_started = False
                    existing.server_sample_accepted = False
                    existing.modules[RECORDING_MODULE] = ModuleState(
                        RECORDING_MODULE, "running", "正在重试本场录制", 0.1
                    )
                    existing.teacher_sid = str(teacher_sid)
                    gate = existing
                else:
                    existing.teacher_sid = str(teacher_sid)
                    result = {"success": True, "idempotentReplay": True, **existing.snapshot()}
                    logger.info("readiness replay training=%s status=%s", training, existing.status)
                    return result
            else:
                gate = ReadinessGate(
                    training_session_id=training,
                    student_id=student,
                    teacher_sid=str(teacher_sid),
                    items=[dict(item) for item in items if isinstance(item, dict)],
                    timeout_ms=max(5000, min(int(data.get("timeoutMs") or DEFAULT_TIMEOUT_MS), 120000)),
                )
                self._gates[training] = gate
        self._push(gate)
        self._start_capture(gate)
        self._schedule_poll(gate)
        self._schedule_timeout(gate)
        return {"success": True, **gate.snapshot()}

    def _start_capture(self, gate: ReadinessGate) -> None:
        with self._lock:
            if gate.cancelled or gate.capture_start_attempted:
                return
            gate.capture_start_attempted = True
        if self._capture_start_callback is None:
            self._fail(gate, "正式录制启动服务未配置")
            return
        try:
            result = dict(self._capture_start_callback(gate.training_session_id) or {})
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        if not result.get("ok"):
            self._fail(gate, f"正式录制启动失败: {result.get('error') or 'unknown'}")
            return
        gate.session_id = result.get("sessionId") or result.get("session_id")
        gate.capture_started = True
        gate.modules[RECORDING_MODULE].detail = "录制已启动，等待服务器收到视频"
        gate.modules[RECORDING_MODULE].progress01 = 0.35
        self._push(gate)
        if gate.session_id and self._child_emit:
            self._child_emit("readiness_complete", {
                "trainingSessionId": gate.training_session_id,
                "sessionId": gate.session_id,
                "studentId": gate.student_id,
                "captureStart": True,
                "captureStarted": False,
                "generation": gate.generation,
            })
        elif not gate.session_id:
            self._fail(gate, "正式录制未返回会话标识")

    def _find_capture_session(self, student_id: int, training_session_id: Optional[str] = None):
        from app.session import get_session_manager
        sessions = get_session_manager().get_sessions_by_student(int(student_id))
        candidates = (
            [s for s in sessions if str(getattr(s, "training_session_id", "")) == str(training_session_id)]
            if training_session_id
            else list(sessions)
        )
        for sess in candidates:
            meta = sess.metadata or {}
            if meta.get("continuous_recording") or meta.get("recording_mode") == "continuous":
                if sess.is_active() or meta.get("preflight_only"):
                    return sess
        return None

    def check_capture(self, student_id: int, training_session_id: str, child_report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Accept only server-owned video evidence, never client counters/audio."""
        capture = self._find_capture_session(int(student_id), str(training_session_id))
        if capture is None:
            return {"ok": False, "pending": True, "detail": "录制会话尚未建立"}
        meta = capture.metadata or {}
        if meta.get("preflight_only") and not meta.get("capture_started"):
            return {"ok": False, "pending": True, "sessionId": capture.session_id, "detail": "录制正在启动"}
        accepted = int(getattr(capture, "total_frames", 0) or 0)
        last_video_accepted = 0
        last_video_at = None
        try:
            from app.routes.media_upload import get_media_session_meta
            upload = get_media_session_meta(capture.session_id) or {}
            last_video_accepted = int(upload.get("lastVideoAccepted") or 0)
            last_video_at = upload.get("lastFrameAt")
            accepted = max(accepted, last_video_accepted)
        except Exception:
            pass
        if accepted >= MIN_WARMUP_FRAMES and (not last_video_at or _now_ms() - int(last_video_at) <= MEDIA_META_STALE_MS):
            return {"ok": True, "sessionId": capture.session_id, "frameCount": accepted, "detail": "服务器已收到有效视频"}
        return {"ok": False, "pending": True, "sessionId": capture.session_id, "detail": "等待服务器收到有效视频"}

    def _poll_capture(self, gate: ReadinessGate) -> None:
        result = self.check_capture(gate.student_id, gate.training_session_id)
        if result.get("ok"):
            with self._lock:
                if gate.status == "RECORDING_CONFIRMED":
                    return
                gate.server_sample_accepted = True
                gate.status = "RECORDING_CONFIRMED"
                module = gate.modules[RECORDING_MODULE]
                module.status = "success"
                module.progress01 = 1.0
                module.detail = result.get("detail") or "服务器已收到有效视频"
            self._push(gate, "readiness_complete")
            return
        with self._lock:
            if gate.status != "STARTING" or gate.cancelled:
                return
            module = gate.modules[RECORDING_MODULE]
            module.status = "running"
            module.detail = result.get("detail") or module.detail
            module.progress01 = max(module.progress01, 0.4 if gate.capture_started else 0.1)
        self._push(gate)

    def _schedule_poll(self, gate: ReadinessGate) -> None:
        training = gate.training_session_id
        def loop() -> None:
            while True:
                time.sleep(0.5)
                with self._lock:
                    current = self._gates.get(training)
                    if not current or current.cancelled or current.status != "STARTING":
                        return
                    if _now_ms() >= current.deadline_at_ms:
                        return
                self._poll_capture(current)
        threading.Thread(target=loop, daemon=True, name=f"recording-gate-{training[:8]}").start()

    def _schedule_timeout(self, gate: ReadinessGate) -> None:
        def timeout() -> None:
            with self._lock:
                current = self._gates.get(gate.training_session_id)
                if not current or current.cancelled or current.status != "STARTING":
                    return
            self._fail(gate, "录制启动超时：服务器仍未收到视频，请检查儿童端采集连接")
        timer = threading.Timer(max(1, gate.timeout_ms / 1000), timeout)
        timer.daemon = True
        timer.start()

    def _fail(self, gate: ReadinessGate, detail: str) -> None:
        with self._lock:
            if gate.cancelled or gate.status == "RECORDING_CONFIRMED":
                return
            gate.status = "FAILED"
            module = gate.modules[RECORDING_MODULE]
            module.status = "failed"
            module.progress01 = 0.0
            module.detail = str(detail)
        self._push(gate)

    def handle_child_report(self, data: Dict[str, Any]) -> Dict[str, Any]:
        training = str(data.get("trainingSessionId") or data.get("training_session_id") or "")
        if not training:
            return {"success": False, "error": "missing_training_session_id"}
        with self._lock:
            gate = self._gates.get(training)
            if not gate or gate.cancelled:
                return {"success": False, "error": "no_active_gate"}
            if data.get("captureStartError") and gate.status == "STARTING":
                self._fail(gate, str(data.get("captureStartError")))
        self._poll_capture(gate)
        return {"success": True, "snapshot": gate.snapshot()}

    def force_enter(self, training_session_id: str, *, teacher_sid: str, reason: str = "") -> Dict[str, Any]:
        # Compatibility endpoint intentionally cannot bypass real recording.
        gate = self.get_gate(training_session_id)
        if not gate:
            return {"success": False, "error": "readiness_gate_missing"}
        gate.teacher_sid = str(teacher_sid)
        if gate.status == "RECORDING_CONFIRMED":
            return {"success": True, "forced": False, **gate.snapshot()}
        return {"success": False, "error": "recording_not_ready", "snapshot": gate.snapshot()}


_readiness_service: Optional[ReadinessService] = None
_readiness_lock = threading.Lock()


def get_readiness_service() -> ReadinessService:
    global _readiness_service
    with _readiness_lock:
        if _readiness_service is None:
            _readiness_service = ReadinessService()
        return _readiness_service
