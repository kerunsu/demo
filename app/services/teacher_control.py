"""Authenticated teacher control leases for training sessions."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
import json
from pathlib import Path
import threading
import time
from typing import Any, Dict, Optional

from app.storage.process_lock import InterProcessMutex
from app.storage.session_layout import atomic_write_json


@dataclass
class TeacherLease:
    training_session_id: str
    teacher_id: int
    teacher_username: str
    sid: str
    generation: int
    acquired_at_ms: int
    last_seen_monotonic: float
    disconnected_at_monotonic: Optional[float] = None
    last_seen_epoch_ms: int = 0
    disconnected_at_epoch_ms: Optional[int] = None

    def to_dict(self, *, requester_teacher_id: Optional[int] = None) -> Dict[str, Any]:
        return {
            "trainingSessionId": self.training_session_id,
            "ownerTeacherId": self.teacher_id,
            "ownerUsername": self.teacher_username,
            "generation": self.generation,
            "acquiredAtMs": self.acquired_at_ms,
            "controlRole": (
                "controller"
                if requester_teacher_id == self.teacher_id
                else "observer"
            ),
        }


class TeacherControlRegistry:
    """Process-local lease registry; persistence is handled in the P2 phase."""

    def __init__(
        self,
        lease_ttl_seconds: float = 30.0,
        *,
        state_path: Optional[Path] = None,
    ):
        self.lease_ttl_seconds = max(float(lease_ttl_seconds), 5.0)
        self._lock = threading.RLock()
        self._leases: Dict[str, TeacherLease] = {}
        self._generation = 0
        self._state_path = Path(state_path) if state_path else None
        self._process_lock = (
            InterProcessMutex(self._state_path.with_suffix('.lock'))
            if self._state_path else None
        )

    def _load_persisted(self) -> None:
        if not self._state_path or not self._state_path.is_file():
            return
        try:
            payload = json.loads(self._state_path.read_text(encoding='utf-8'))
            leases = {}
            for item in payload.get('leases') or []:
                lease = TeacherLease(
                    training_session_id=str(item['trainingSessionId']),
                    teacher_id=int(item['teacherId']),
                    teacher_username=str(item.get('teacherUsername') or ''),
                    sid=str(item.get('sid') or ''),
                    generation=int(item.get('generation') or 0),
                    acquired_at_ms=int(item.get('acquiredAtMs') or 0),
                    last_seen_monotonic=time.monotonic(),
                    disconnected_at_monotonic=(
                        time.monotonic()
                        if item.get('disconnectedAtEpochMs') is not None else None
                    ),
                    last_seen_epoch_ms=int(item.get('lastSeenEpochMs') or 0),
                    disconnected_at_epoch_ms=item.get('disconnectedAtEpochMs'),
                )
                leases[lease.training_session_id] = lease
                self._generation = max(self._generation, lease.generation)
            self._leases = leases
        except (OSError, ValueError, KeyError, TypeError):
            self._leases = {}

    def _save_persisted(self) -> None:
        if not self._state_path:
            return
        atomic_write_json(self._state_path, {
            'schemaVersion': 'teacher-control-leases-v1',
            'generation': self._generation,
            'leases': [{
                'trainingSessionId': lease.training_session_id,
                'teacherId': lease.teacher_id,
                'teacherUsername': lease.teacher_username,
                'sid': lease.sid,
                'generation': lease.generation,
                'acquiredAtMs': lease.acquired_at_ms,
                'lastSeenEpochMs': lease.last_seen_epoch_ms,
                'disconnectedAtEpochMs': lease.disconnected_at_epoch_ms,
            } for lease in self._leases.values()],
        })

    @contextmanager
    def _coordinated(self):
        with self._lock:
            process_lock_acquired = False
            if self._process_lock:
                process_lock_acquired = self._process_lock.acquire(blocking=True)
                if not process_lock_acquired:
                    raise RuntimeError("teacher_control_temporarily_unavailable")
            try:
                self._load_persisted()
                yield
                self._save_persisted()
            finally:
                if self._process_lock and process_lock_acquired:
                    self._process_lock.release()

    def _expired(self, lease: TeacherLease, now: float) -> bool:
        disconnected_expired = bool(
            lease.disconnected_at_monotonic is not None
            and now - lease.disconnected_at_monotonic > self.lease_ttl_seconds
        )
        epoch_now = int(time.time() * 1000)
        persisted_disconnected_expired = bool(
            lease.disconnected_at_epoch_ms is not None
            and epoch_now - int(lease.disconnected_at_epoch_ms)
            > self.lease_ttl_seconds * 1000
        )
        crashed_owner_expired = bool(
            lease.last_seen_epoch_ms
            and epoch_now - lease.last_seen_epoch_ms
            > self.lease_ttl_seconds * 3000
        )
        return disconnected_expired or persisted_disconnected_expired or crashed_owner_expired

    def claim(
        self,
        training_session_id: Any,
        *,
        teacher_id: Any,
        teacher_username: str,
        sid: str,
        replace_existing_for_teacher: bool = False,
    ) -> Dict[str, Any]:
        training_id = str(training_session_id or "").strip()
        socket_sid = str(sid or "").strip()
        if not training_id or not socket_sid:
            return {"ok": False, "error": "training_session_id_missing"}
        try:
            normalized_teacher_id = int(teacher_id)
        except (TypeError, ValueError):
            return {"ok": False, "error": "teacher_auth_required"}

        now = time.monotonic()
        with self._coordinated():
            if replace_existing_for_teacher:
                # A newly prepared workflow from the same authenticated
                # teacher is the sole controller. Old tabs immediately become
                # observers instead of continuing to mutate superseded state.
                for existing_id, existing in list(self._leases.items()):
                    if (
                        existing_id != training_id
                        and existing.teacher_id == normalized_teacher_id
                    ):
                        self._leases.pop(existing_id, None)
            current = self._leases.get(training_id)
            if current and not self._expired(current, now):
                if current.teacher_id != normalized_teacher_id:
                    return {
                        "ok": True,
                        "writable": False,
                        "lease": current.to_dict(
                            requester_teacher_id=normalized_teacher_id
                        ),
                    }
                # 同一教师的旧连接被本连接替换：把旧 sid 交还给调用方，
                # 由事件层主动通知旧窗口降级为 observer（接管闭环）。
                replaced_sid = current.sid if current.sid != socket_sid else None
                current.sid = socket_sid
                current.teacher_username = str(teacher_username or "")
                current.last_seen_monotonic = now
                current.last_seen_epoch_ms = int(time.time() * 1000)
                current.disconnected_at_monotonic = None
                current.disconnected_at_epoch_ms = None
                result: Dict[str, Any] = {
                    "ok": True,
                    "writable": True,
                    "lease": current.to_dict(
                        requester_teacher_id=normalized_teacher_id
                    ),
                }
                if replaced_sid:
                    result["replacedSid"] = replaced_sid
                return result

            self._generation += 1
            lease = TeacherLease(
                training_session_id=training_id,
                teacher_id=normalized_teacher_id,
                teacher_username=str(teacher_username or ""),
                sid=socket_sid,
                generation=self._generation,
                acquired_at_ms=int(time.time() * 1000),
                last_seen_monotonic=now,
                last_seen_epoch_ms=int(time.time() * 1000),
            )
            self._leases[training_id] = lease
            return {
                "ok": True,
                "writable": True,
                "lease": lease.to_dict(
                    requester_teacher_id=normalized_teacher_id
                ),
            }

    def authorize(
        self,
        training_session_id: Any,
        *,
        teacher_id: Any,
        sid: str,
    ) -> Dict[str, Any]:
        training_id = str(training_session_id or "").strip()
        try:
            normalized_teacher_id = int(teacher_id)
        except (TypeError, ValueError):
            return {"ok": False, "writable": False, "error": "teacher_auth_required"}
        if not training_id:
            return {"ok": False, "writable": False, "error": "training_session_id_missing"}

        now = time.monotonic()
        with self._coordinated():
            lease = self._leases.get(training_id)
            if lease and self._expired(lease, now):
                self._leases.pop(training_id, None)
                lease = None
            if lease is None:
                return {"ok": False, "writable": False, "error": "control_lease_missing"}
            if lease.teacher_id != normalized_teacher_id or lease.sid != str(sid):
                return {
                    "ok": False,
                    "writable": False,
                    "error": "observer_read_only",
                    "lease": lease.to_dict(
                        requester_teacher_id=normalized_teacher_id
                    ),
                }
            lease.last_seen_monotonic = now
            lease.last_seen_epoch_ms = int(time.time() * 1000)
            lease.disconnected_at_monotonic = None
            lease.disconnected_at_epoch_ms = None
            return {
                "ok": True,
                "writable": True,
                "lease": lease.to_dict(
                    requester_teacher_id=normalized_teacher_id
                ),
            }

    def release(self, training_session_id: Any, *, teacher_id: Any, sid: str) -> bool:
        training_id = str(training_session_id or "").strip()
        with self._coordinated():
            lease = self._leases.get(training_id)
            if not lease:
                return False
            if lease.teacher_id != int(teacher_id) or lease.sid != str(sid):
                return False
            self._leases.pop(training_id, None)
            return True

    def disconnect(self, sid: str) -> None:
        """Keep the lease until TTL so a transient reconnect cannot be stolen."""
        socket_sid = str(sid or "")
        with self._coordinated():
            now = time.monotonic()
            for lease in self._leases.values():
                if lease.sid == socket_sid:
                    lease.last_seen_monotonic = now
                    lease.disconnected_at_monotonic = now
                    lease.last_seen_epoch_ms = int(time.time() * 1000)
                    lease.disconnected_at_epoch_ms = int(time.time() * 1000)

    def touch(self, sid: str) -> None:
        """Heartbeat refresh: a live socket proves the owner is still active.

        Lease expiry must not be triggered by teacher idle time — the 10s
        client_presence heartbeat keeps the lease fresh while the page is
        open, so only real disconnects (handled by `disconnect`) age it out.
        """
        socket_sid = str(sid or "")
        with self._coordinated():
            now = time.monotonic()
            for lease in self._leases.values():
                if lease.sid == socket_sid:
                    lease.last_seen_monotonic = now
                    lease.last_seen_epoch_ms = int(time.time() * 1000)
                    lease.disconnected_at_monotonic = None
                    lease.disconnected_at_epoch_ms = None

    def controller_sids(self) -> Dict[str, str]:
        """Return mapping of socket sid -> training_session_id for live controllers."""
        with self._lock:
            now = time.monotonic()
            return {
                lease.sid: lease.training_session_id
                for lease in self._leases.values()
                if not self._expired(lease, now)
            }

    def clear(self) -> None:
        with self._coordinated():
            self._leases.clear()


_registry = TeacherControlRegistry(
    state_path=Path('.runtime') / 'coordination' / 'teacher_leases.json'
)


def get_teacher_control_registry() -> TeacherControlRegistry:
    return _registry
