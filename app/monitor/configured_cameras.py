"""Configured Server camera discovery and multi-camera preview management."""
from __future__ import annotations

import threading
import time
from typing import Any, Iterable

from app.monitor.ambient_camera import AmbientCameraService


def discover_local_cameras(max_index: int = 8) -> list[dict[str, Any]]:
    """Return local camera candidates without changing the device registry."""

    probe = AmbientCameraService()
    return [
        {
            "candidateId": f"server-camera-{int(item['id'])}",
            "index": int(item["id"]),
            "kind": "video",
            "name": f"摄像头 {int(item['id'])}",
        }
        for item in probe.list_devices(max_index=max_index)
    ]


def _profile_value(profile: Any, name: str, default: Any = None) -> Any:
    if isinstance(profile, dict):
        return profile.get(name, default)
    return getattr(profile, name, default)


class ConfiguredCameraPreviewManager:
    """Own one preview worker per configured local camera."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._streams: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _describe(profile: Any) -> dict[str, Any] | None:
        device_id = str(_profile_value(profile, "device_id", _profile_value(profile, "deviceId", ""))).strip()
        selector = dict(_profile_value(profile, "selector", {}) or {})
        try:
            index = int(selector.get("index"))
        except (TypeError, ValueError):
            return None
        capabilities = dict(_profile_value(profile, "capabilities", {}) or {})
        return {
            "deviceId": device_id,
            "index": index,
            "name": str(capabilities.get("displayName") or f"环境摄像头 {index}"),
            "role": str(_profile_value(profile, "role", "environment_secondary")),
            "required": bool(_profile_value(profile, "required", False)),
        } if device_id else None

    def ensure(self, profile: Any) -> dict[str, Any] | None:
        desired = self._describe(profile)
        if desired is None:
            return None
        device_id = desired["deviceId"]
        with self._lock:
            current = self._streams.get(device_id)
            if current and current["index"] != desired["index"]:
                current["service"].control(enabled=False)
                self._streams.pop(device_id, None)
                current = None
            if current is None:
                service = AmbientCameraService()
                service.control(enabled=True, device_id=desired["index"])
                current = {**desired, "service": service}
                self._streams[device_id] = current
            else:
                current.update(desired)
            return self._status_locked(current)

    def sync(self, profiles: Iterable[Any]) -> list[dict[str, Any]]:
        source_profiles = list(profiles)
        desired_profiles = [item for item in (self._describe(profile) for profile in source_profiles) if item]
        wanted = {item["deviceId"] for item in desired_profiles}
        with self._lock:
            for device_id in tuple(self._streams):
                if device_id not in wanted:
                    self._streams.pop(device_id)["service"].control(enabled=False)
        for profile in source_profiles:
            self.ensure(profile)
        return self.statuses()

    def wait_for_frame(self, profile: Any, timeout: float = 2.0) -> dict[str, Any]:
        status = self.ensure(profile) or {"connected": False, "captureReady": False, "error": "invalid_selector"}
        deadline = time.monotonic() + max(0.0, timeout)
        while not status.get("hasFrame") and time.monotonic() < deadline:
            time.sleep(0.05)
            device_id = status.get("deviceId")
            status = self.status(device_id) or status
        return {
            "connected": bool(status.get("hasFrame")),
            "captureReady": bool(status.get("hasFrame")),
            "firstFrameReady": bool(status.get("hasFrame")),
            "error": None if status.get("hasFrame") else (status.get("error") or "first_frame_timeout"),
        }

    def _status_locked(self, entry: dict[str, Any]) -> dict[str, Any]:
        raw = entry["service"].status()
        updated_at = raw.get("updatedAt")
        has_fresh_frame = bool(
            raw.get("hasFrame")
            and updated_at
            and time.time() - float(updated_at) <= 2.5
        )
        return {
            "deviceId": entry["deviceId"],
            "selectorIndex": entry["index"],
            "name": entry["name"],
            "role": entry["role"],
            "required": entry["required"],
            "enabled": bool(raw.get("enabled")),
            "hasFrame": has_fresh_frame,
            "updatedAt": updated_at,
            "error": raw.get("error"),
        }

    def statuses(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._status_locked(self._streams[key]) for key in sorted(self._streams)]

    def status(self, device_id: str | None) -> dict[str, Any] | None:
        with self._lock:
            entry = self._streams.get(str(device_id or ""))
            return self._status_locked(entry) if entry else None

    def get_jpeg(self, device_id: str | None) -> bytes | None:
        with self._lock:
            entry = self._streams.get(str(device_id or ""))
            return entry["service"].get_jpeg() if entry else None


_manager: ConfiguredCameraPreviewManager | None = None
_manager_lock = threading.Lock()


def get_configured_camera_manager() -> ConfiguredCameraPreviewManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = ConfiguredCameraPreviewManager()
        return _manager


__all__ = ["ConfiguredCameraPreviewManager", "discover_local_cameras", "get_configured_camera_manager"]
