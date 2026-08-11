"""默认可注入的设备探针 broker；不拥有具体硬件。"""

from __future__ import annotations

import threading
from typing import Any, Callable, Dict, Optional

from app.contracts.models import DeviceProfile
from app.contracts.ports import DeviceBroker


class CallbackDeviceBroker(DeviceBroker):
    """用回调桥接旧 ambient/Runtime/浏览器检查，方便 fake 和逐步替换。"""

    def __init__(self, callbacks: Optional[Dict[str, Callable[..., Any]]] = None) -> None:
        self._callbacks = dict(callbacks or {})
        self._reserved: set[str] = set()
        self._checked: set[str] = set()
        self._lock = threading.RLock()

    def check(self, device: DeviceProfile) -> Dict[str, Any]:
        callback = self._callbacks.get("check")
        if not callback:
            return {
                "ok": False,
                "deviceId": device.device_id,
                "trackId": device.track_id,
                "error": "device_probe_not_configured",
            }
        result = dict(callback(device) or {})
        if result.get("ok"):
            with self._lock:
                self._checked.add(device.device_id)
        return result

    def reserve(self, device: DeviceProfile) -> Dict[str, Any]:
        with self._lock:
            if device.device_id in self._reserved:
                return {"ok": False, "error": "device_busy", "deviceId": device.device_id}
            reserve_callback = self._callbacks.get("reserve")
            if reserve_callback:
                result = dict(reserve_callback(device) or {})
            elif device.device_id in self._checked:
                result = {"ok": True, "deviceId": device.device_id}
            else:
                result = self.check(device)
            self._checked.discard(device.device_id)
            if result.get("ok"):
                self._reserved.add(device.device_id)
            return result

    def open(self, device: DeviceProfile) -> Any:
        callback = self._callbacks.get("open")
        if callback:
            return callback(device)
        raise RuntimeError("device_open_not_configured")

    def close(self, device_id: str) -> None:
        callback = self._callbacks.get("close")
        try:
            if callback:
                callback(device_id)
        finally:
            with self._lock:
                self._reserved.discard(device_id)
                self._checked.discard(device_id)

    def release(self, device_id: str) -> None:
        self.close(device_id)
