"""线程安全的 0..N 设备注册表和训练快照。

这是配置/身份层，不打开设备、不启动线程、不写 sessions。真实 Server/Runtime
发现通过 ``discover`` 注入，旧 AmbientCameraService 仍由兼容 adapter 拥有。
"""

from __future__ import annotations

import copy
import hashlib
import threading
import uuid
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Optional

from app.contracts.models import (
    DeploymentProfile,
    DeviceRef,
    DeviceProfile,
    DeviceProfileSnapshot,
    TimePoint,
)
from app.contracts.ports import Clock, DeviceDiscoveryPort, DeviceProfileStore, DeviceRegistry


def stable_track_id(device_id: str, kind: str, role: str) -> str:
    """由稳定身份生成 trackId，不使用设备数组下标。"""

    raw = f"{device_id}:{kind}:{role}".encode("utf-8")
    digest = hashlib.sha1(raw).hexdigest()[:12]
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in device_id)
    return f"{safe or 'device'}-{digest}"


class SystemClock:
    def monotonic_seconds(self) -> float:
        import time

        return time.monotonic()

    def wall_time_iso(self) -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()


class InMemoryDeviceRegistry(DeviceRegistry):
    def __init__(
        self,
        *,
        clock: Optional[Clock] = None,
        discoveries: Optional[Iterable[DeviceDiscoveryPort]] = None,
        profile_store: Optional[DeviceProfileStore] = None,
    ) -> None:
        self._clock = clock or SystemClock()
        self._discoveries = list(discoveries or ())
        self._profile_store = profile_store
        self._devices: Dict[str, DeviceProfile] = {}
        self._lock = threading.RLock()
        self._load_error: Optional[str] = None
        if profile_store is not None:
            try:
                for device in profile_store.load():
                    normalized = self._normalize(device)
                    if normalized.device_id in self._devices:
                        raise ValueError(f"duplicate_device_id:{normalized.device_id}")
                    self._assert_track_available(normalized.track_id, normalized.device_id)
                    self._devices[normalized.device_id] = copy.deepcopy(normalized)
            except Exception as exc:
                self._devices.clear()
                self._load_error = str(exc)

    @staticmethod
    def _normalize(device: DeviceProfile) -> DeviceProfile:
        device_id = str(device.device_id or "").strip()
        kind = str(device.kind or "").strip().lower()
        role = str(device.role or "").strip()
        if not device_id:
            raise ValueError("device_id_required")
        if len(device_id) > 200 or any(ch in device_id for ch in ("/", "\\", "\x00")):
            raise ValueError("invalid_device_id")
        if kind not in {"video", "audio"}:
            raise ValueError("invalid_device_kind")
        if not role:
            raise ValueError("device_role_required")
        if not isinstance(device.selector, dict) or not isinstance(device.format, dict) or not isinstance(device.capabilities, dict):
            raise ValueError("device_mapping_fields_must_be_objects")
        track_id = str(device.track_id or "").strip() or stable_track_id(device_id, kind, role)
        if len(track_id) > 200 or any(ch in track_id for ch in ("/", "\\", "\x00")):
            raise ValueError("invalid_track_id")
        return replace(
            device,
            device_id=device_id,
            track_id=track_id,
            kind=kind,
            role=role,
            owner=str(device.owner or "server").strip() or "server",
            selector=copy.deepcopy(device.selector),
            format=copy.deepcopy(device.format),
            capabilities=copy.deepcopy(device.capabilities),
            priority=int(device.priority),
        )

    def _assert_track_available(self, track_id: str, device_id: str) -> None:
        for current in self._devices.values():
            if current.track_id == track_id and current.device_id != device_id:
                raise ValueError(f"duplicate_track_id:{track_id}")

    def _persist_locked(self) -> None:
        if self._profile_store is not None:
            self._profile_store.save(self.list_devices())
            self._load_error = None

    def _ensure_available_locked(self) -> None:
        if self._load_error:
            raise RuntimeError(f"device_registry_load_failed:{self._load_error}")

    def get_load_error(self) -> Optional[str]:
        with self._lock:
            return self._load_error

    def list_devices(self) -> List[DeviceProfile]:
        with self._lock:
            return sorted(
                (copy.deepcopy(device) for device in self._devices.values()),
                key=lambda device: (device.priority, device.device_id),
            )

    def get(self, device_id: str) -> Optional[DeviceProfile]:
        with self._lock:
            device = self._devices.get(str(device_id))
            return copy.deepcopy(device) if device else None

    def register(self, device: DeviceProfile) -> None:
        device = self._normalize(device)
        with self._lock:
            self._ensure_available_locked()
            self._assert_track_available(device.track_id, device.device_id)
            previous = self._devices.get(device.device_id)
            self._devices[device.device_id] = copy.deepcopy(device)
            try:
                self._persist_locked()
            except Exception:
                if previous is None:
                    self._devices.pop(device.device_id, None)
                else:
                    self._devices[device.device_id] = previous
                raise

    def unregister(self, device_id: str) -> None:
        # 解绑配置，不访问历史 session，也不删除历史文件。
        with self._lock:
            self._ensure_available_locked()
            previous = self._devices.pop(str(device_id), None)
            try:
                self._persist_locked()
            except Exception:
                if previous is not None:
                    self._devices[str(device_id)] = previous
                raise

    def update(self, device_id: str, **changes: Any) -> DeviceProfile:
        with self._lock:
            self._ensure_available_locked()
            current = self._devices.get(str(device_id))
            if current is None:
                raise KeyError(str(device_id))
            allowed = {
                "track_id", "kind", "role", "location", "owner", "runtime_id",
                "selector", "enabled", "required", "priority", "format",
                "capabilities",
            }
            unknown = set(changes) - allowed
            if unknown:
                raise ValueError(f"unknown_device_fields:{','.join(sorted(unknown))}")
            updated = self._normalize(replace(current, **changes))
            self._assert_track_available(updated.track_id, updated.device_id)
            self._devices[str(device_id)] = copy.deepcopy(updated)
            try:
                self._persist_locked()
            except Exception:
                self._devices[str(device_id)] = current
                raise
            return copy.deepcopy(updated)

    def discover(self) -> List[DeviceProfile]:
        discovered: List[DeviceProfile] = []
        for provider in self._discoveries:
            for item in provider.discover():
                if isinstance(item, DeviceProfile):
                    profile = item
                elif isinstance(item, DeviceRef):
                    metadata = dict(item.metadata or {})
                    role = str(metadata.get("role") or "environment_secondary")
                    profile = DeviceProfile(
                        device_id=item.device_id,
                        track_id=str(metadata.get("trackId") or metadata.get("track_id") or ""),
                        kind=item.kind,
                        role=role,
                        location=metadata.get("location"),
                        owner=str(metadata.get("owner") or "server"),
                        runtime_id=item.runtime_id,
                        selector=dict(metadata.get("selector") or {"deviceType": item.device_type}),
                        enabled=item.enabled,
                        required=item.required,
                        format=dict(metadata.get("format") or {}),
                        capabilities=dict(metadata.get("capabilities") or {}),
                    )
                else:
                    raise TypeError("discovery_must_return_device_ref_or_profile")
                current = self.get(profile.device_id)
                if current is not None:
                    profile = replace(
                        profile,
                        track_id=current.track_id,
                        role=current.role,
                        enabled=current.enabled,
                        required=current.required,
                        priority=current.priority,
                    )
                discovered.append(self._normalize(profile))
        # Discovery is one configuration transaction. A bad/duplicate item or
        # a persistence failure must not leave a partially updated registry.
        with self._lock:
            self._ensure_available_locked()
            previous = copy.deepcopy(self._devices)
            staged = copy.deepcopy(self._devices)
            try:
                self._devices = staged
                for item in discovered:
                    self._assert_track_available(item.track_id, item.device_id)
                    self._devices[item.device_id] = copy.deepcopy(item)
                self._persist_locked()
            except Exception:
                self._devices = previous
                raise
        return [copy.deepcopy(item) for item in discovered]

    def freeze(self, deployment: DeploymentProfile) -> DeviceProfileSnapshot:
        if self.get_load_error():
            raise RuntimeError(f"device_registry_load_failed:{self.get_load_error()}")
        devices = tuple(
            device
            for device in self.list_devices()
            if device.enabled
        )
        return DeviceProfileSnapshot(
            snapshot_id=str(uuid.uuid4()),
            created_at=TimePoint(
                monotonic_seconds=self._clock.monotonic_seconds(),
                wall_time_iso=self._clock.wall_time_iso(),
            ),
            devices=devices,
            deployment_profile_id=f"{deployment.profile_id}@{deployment.version}",
        )


_registry: Optional[InMemoryDeviceRegistry] = None
_registry_lock = threading.Lock()


def get_device_registry() -> InMemoryDeviceRegistry:
    global _registry
    with _registry_lock:
        if _registry is None:
            _registry = InMemoryDeviceRegistry()
        return _registry


def configure_device_registry(registry: InMemoryDeviceRegistry) -> None:
    global _registry
    with _registry_lock:
        _registry = registry
