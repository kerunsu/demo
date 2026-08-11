"""Readiness and capture start barrier orchestration.

The orchestrator owns the decision to start a formal capture.  It does not
open devices or write media itself; those effects are delegated to ports so
that real hardware, Runtime and CI fakes share the same rules.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence

from app.acquisition.device_registry import SystemClock
from app.contracts.models import (
    DeploymentProfile,
    DeviceProfile,
    DeviceProfileSnapshot,
    PreflightCheck,
    PreflightResult,
    SessionRef,
    TrackRef,
)
from app.contracts.ports import CapturePort, Clock, DeviceBroker, DeviceRegistry, SessionLayoutPort


ModuleProbe = Callable[["PreflightPlan"], Mapping[str, Any]]


@dataclass(frozen=True)
class PreflightPlan:
    session: SessionRef
    human_dir_name: str
    deployment: DeploymentProfile
    snapshot: DeviceProfileSnapshot
    tracks: tuple[TrackRef, ...] = ()
    schema_version: int = 1


@dataclass
class _RunState:
    result: Optional[PreflightResult] = None
    started: bool = False
    stopped: bool = False
    reserved_device_ids: set[str] = field(default_factory=set)


class PreflightOrchestrator:
    """Prepare, check and atomically start a capture session.

    ``prepare`` only freezes configuration and reserves the directory name;
    it never calls ``open`` or ``CapturePort.start``.  ``start_barrier`` is
    the only method that can begin formal capture.
    """

    def __init__(
        self,
        *,
        registry: DeviceRegistry,
        broker: DeviceBroker,
        capture: CapturePort,
        layout: SessionLayoutPort,
        clock: Optional[Clock] = None,
        module_probes: Optional[Mapping[str, ModuleProbe]] = None,
    ) -> None:
        self.registry = registry
        self.broker = broker
        self.capture = capture
        self.layout = layout
        self.clock = clock or SystemClock()
        self.module_probes = dict(module_probes or {})
        self._plans: dict[str, PreflightPlan] = {}
        self._states: dict[str, _RunState] = {}
        self._lock = threading.RLock()

    @staticmethod
    def _key(session: SessionRef) -> str:
        key = session.training_session_id or session.media_session_id or session.session_id
        if not key:
            raise ValueError("session_identity_required")
        return str(key)

    def prepare(
        self,
        session: SessionRef,
        *,
        human_dir_name: str,
        deployment: Optional[DeploymentProfile] = None,
    ) -> PreflightPlan:
        deployment = deployment or DeploymentProfile()
        snapshot = self.registry.freeze(deployment)
        tracks = tuple(
            TrackRef(
                track_id=device.track_id,
                kind=device.kind,
                role=device.role,
                device_id=device.device_id,
                runtime_id=device.runtime_id,
                required=device.required,
                format=(
                    str(device.format.get("container") or device.format.get("format") or device.format.get("codec"))
                    if device.format else None
                ),
            )
            for device in snapshot.devices
        )
        filenames: dict[str, str] = {}
        for track in tracks:
            filename = self.layout.track_filename(track)
            owner = filenames.setdefault(filename, track.track_id)
            if owner != track.track_id:
                raise ValueError(f"duplicate_track_filename:{filename}")
        # Binding is a reservation of the directory identity, not a media write.
        bind = getattr(self.layout, "bind", None)
        if callable(bind):
            bind(session, human_dir_name)
        else:
            self.layout.reserve(human_dir_name)
        plan = PreflightPlan(
            session=session,
            human_dir_name=human_dir_name,
            deployment=deployment,
            snapshot=snapshot,
            tracks=tracks,
        )
        key = self._key(session)
        with self._lock:
            old_state = self._states.get(key)
            if old_state is not None:
                self._release_reserved(old_state)
            self._plans[key] = plan
            self._states[key] = _RunState()
        return plan

    def get_plan(self, session: SessionRef) -> Optional[PreflightPlan]:
        with self._lock:
            return self._plans.get(self._key(session))

    def check(self, session: SessionRef) -> PreflightResult:
        key = self._key(session)
        with self._lock:
            plan = self._plans.get(key)
            state = self._states.setdefault(key, _RunState())
            if state.result is not None:
                return state.result
        if plan is None:
            return PreflightResult(status="failed", required_ok=False, checks=(PreflightCheck(
                module_id="preflight", status="failed", phase="prepare", reason="plan_not_found",
            ),), session=session)

        checks: list[PreflightCheck] = []
        self._release_reserved(state)
        for device in plan.snapshot.devices:
            if not device.enabled:
                checks.append(PreflightCheck(
                    module_id=f"device:{device.device_id}", status="disabled", phase="device",
                    device_id=device.device_id, track_id=device.track_id, required=False,
                ))
                continue
            try:
                raw = dict(self.broker.check(device) or {})
                ok = bool(raw.get("ok", False))
                if ok:
                    reserved = dict(self.broker.reserve(device) or {})
                    ok = bool(reserved.get("ok", False))
                    if ok:
                        state.reserved_device_ids.add(device.device_id)
                    raw.update({"reserve": reserved})
            except Exception as exc:
                raw = {"ok": False, "error": f"device_probe_error:{exc}"}
                ok = False
            checks.append(PreflightCheck(
                module_id=f"device:{device.device_id}",
                status="success" if ok else "failed",
                phase="device",
                reason=None if ok else str(raw.get("error") or raw.get("reason") or "device_check_failed"),
                repair_hint=raw.get("repairHint"),
                device_id=device.device_id,
                track_id=device.track_id,
                required=device.required,
                details=raw,
            ))

        for module_id in plan.deployment.required_modules + plan.deployment.optional_modules:
            probe = self.module_probes.get(module_id)
            required = module_id in plan.deployment.required_modules
            if probe is None:
                checks.append(PreflightCheck(
                    module_id=module_id,
                    status="failed" if required else "optional_unavailable",
                    phase="module",
                    reason="probe_not_registered",
                    required=required,
                ))
                continue
            try:
                raw = dict(probe(plan) or {})
                ok = bool(raw.get("ok", False))
                checks.append(PreflightCheck(
                    module_id=module_id,
                    status="success" if ok else "failed",
                    phase="module",
                    reason=None if ok else str(raw.get("error") or "module_check_failed"),
                    required=required,
                    details=raw,
                ))
            except Exception as exc:  # probe failures are data, not process failures
                checks.append(PreflightCheck(
                    module_id=module_id, status="failed", phase="module",
                    reason=f"probe_error:{exc}", required=required,
                ))

        required_ok = all(check.status == "success" for check in checks if check.required)
        result = PreflightResult(
            status="ready" if required_ok else "blocked",
            required_ok=required_ok,
            checks=tuple(checks),
            snapshot=plan.snapshot,
            session=session,
        )
        with self._lock:
            state.result = result
        if not required_ok:
            self._release_reserved(state)
        return result

    def start_barrier(self, session: SessionRef) -> Mapping[str, Any]:
        key = self._key(session)
        with self._lock:
            plan = self._plans.get(key)
            state = self._states.setdefault(key, _RunState())
            if state.stopped:
                return {"ok": False, "error": "session_already_stopped"}
            if state.started:
                return {"ok": True, "idempotent": True, "status": "started"}
            result = state.result
        if plan is None:
            return {"ok": False, "error": "plan_not_found"}
        if result is None:
            result = self.check(session)
        if not result.required_ok:
            return {"ok": False, "error": "preflight_blocked", "preflight": result}
        try:
            started = dict(self.capture.start(session, plan.tracks) or {})
            if not bool(started.get("ok", False)):
                raise RuntimeError(str(started.get("error") or "capture_start_failed"))
            required_ids = {track.track_id for track in plan.tracks if track.required}
            observed = started.get("tracks") or ()
            observed_ids = {
                str(item.get("trackId"))
                for item in observed
                if isinstance(item, Mapping)
                and bool(item.get("firstSample") or item.get("firstAudio") or item.get("firstChunk"))
            }
            missing = sorted(required_ids - observed_ids)
            if missing:
                raise RuntimeError(f"required_track_first_sample_missing:{','.join(missing)}")
        except Exception as exc:
            try:
                self.capture.stop(session)
            except Exception:
                pass
            self._release_reserved(state)
            with self._lock:
                state.result = None
            return {"ok": False, "error": str(exc), "rolledBack": True}
        with self._lock:
            state.started = True
            state.stopped = False
        return {"ok": True, "status": "started", "tracks": started.get("tracks", ())}

    def stop(self, session: SessionRef) -> Mapping[str, Any]:
        key = self._key(session)
        with self._lock:
            state = self._states.setdefault(key, _RunState())
            if state.stopped:
                return {"ok": True, "idempotent": True, "status": "stopped"}
            started = state.started
        result: Mapping[str, Any] = {"ok": True, "status": "stopped"}
        if started:
            try:
                raw = self.capture.stop(session)
                result = dict(raw or {})
            except Exception as exc:
                return {"ok": False, "error": str(exc), "status": "stop_failed"}
            if not result.get("ok"):
                return {**result, "ok": False, "status": "stop_failed"}
        self._release_reserved(state)
        with self._lock:
            state.stopped = True
        return result

    def _release_reserved(self, state: _RunState) -> None:
        for device_id in tuple(state.reserved_device_ids):
            try:
                self.broker.release(device_id)
            finally:
                state.reserved_device_ids.discard(device_id)


__all__ = ["PreflightOrchestrator", "PreflightPlan"]
