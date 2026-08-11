"""服务端本机环境摄像头采集（供 /server 监控，不参与评分）。"""
from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional

from app.utils.logger import setup_logger

logger = setup_logger("ambient_camera")

_JPEG_QUALITY = 82
_TARGET_WIDTH = 640
_TARGET_HEIGHT = 480
_CAPTURE_INTERVAL = 0.1  # ~10 fps，本机预览可更高清更流畅


class AmbientCameraService:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._enabled = False
        self._device_id = 0
        self._forced = False
        self._error: Optional[str] = None
        self._jpeg: Optional[bytes] = None
        self._updated_at: float = 0.0
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._cap = None
        self._cv2 = None

    def _ensure_cv2(self):
        if self._cv2 is not None:
            return self._cv2
        try:
            import cv2  # type: ignore
            self._cv2 = cv2
            return cv2
        except Exception as e:
            self._error = f"opencv_unavailable: {e}"
            logger.warning("OpenCV 不可用，环境摄像头降级: %s", e)
            return None

    def list_devices(self, max_index: int = 6) -> List[Dict[str, Any]]:
        cv2 = self._ensure_cv2()
        devices: List[Dict[str, Any]] = []
        if cv2 is None:
            return devices
        for idx in range(max_index):
            cap = None
            try:
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW) if hasattr(cv2, "CAP_DSHOW") else cv2.VideoCapture(idx)
                if cap is not None and cap.isOpened():
                    devices.append({"id": idx, "name": f"摄像头 {idx}"})
            except Exception:
                pass
            finally:
                if cap is not None:
                    try:
                        cap.release()
                    except Exception:
                        pass
        return devices

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "deviceId": self._device_id,
                "forcedByTraining": self._forced,
                "error": self._error,
                "hasFrame": self._jpeg is not None,
                "updatedAt": self._updated_at or None,
            }

    def set_forced(self, forced: bool) -> None:
        with self._lock:
            self._forced = bool(forced)
            if self._forced and not self._enabled:
                self._enabled = True
                self._start_locked()

    def control(self, *, enabled: bool, device_id: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            if device_id is not None:
                try:
                    self._device_id = int(device_id)
                except (TypeError, ValueError):
                    pass
            if self._forced and not enabled:
                self._error = "training_force_on"
                return self.status()
            want = bool(enabled)
            if want == self._enabled and self._thread and self._thread.is_alive():
                if want:
                    # 切换设备：重启采集
                    self._stop_locked()
                    self._enabled = True
                    self._start_locked()
                return self.status()
            if want:
                self._enabled = True
                self._start_locked()
            else:
                self._enabled = False
                self._stop_locked()
            return self.status()

    def get_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._jpeg

    def _start_locked(self) -> None:
        self._error = None
        if self._ensure_cv2() is None:
            self._enabled = False
            return
        self._stop_event.clear()
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._loop, name="ambient-camera", daemon=True)
        self._thread.start()
        logger.info("环境摄像头采集已启动 device=%s", self._device_id)

    def _stop_locked(self) -> None:
        self._stop_event.set()
        cap = self._cap
        self._cap = None
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        self._jpeg = None
        logger.info("环境摄像头采集已停止")

    def _open_capture(self):
        cv2 = self._cv2
        if cv2 is None:
            return None
        idx = self._device_id
        try:
            if hasattr(cv2, "CAP_DSHOW"):
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
            else:
                cap = cv2.VideoCapture(idx)
            if not cap.isOpened():
                cap.release()
                return None
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, _TARGET_WIDTH)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, _TARGET_HEIGHT)
            return cap
        except Exception as e:
            self._error = f"open_failed: {e}"
            return None

    def _loop(self) -> None:
        cv2 = self._cv2
        while not self._stop_event.is_set():
            with self._lock:
                enabled = self._enabled
                device_id = self._device_id
            if not enabled:
                break
            if self._cap is None:
                with self._lock:
                    self._cap = self._open_capture()
                    if self._cap is None and not self._error:
                        self._error = f"device_unavailable:{device_id}"
                if self._cap is None:
                    time.sleep(1.0)
                    continue
            ok, frame = False, None
            try:
                ok, frame = self._cap.read()
            except Exception as e:
                with self._lock:
                    self._error = f"read_failed: {e}"
                ok = False
            if not ok or frame is None:
                with self._lock:
                    if self._cap is not None:
                        try:
                            self._cap.release()
                        except Exception:
                            pass
                        self._cap = None
                time.sleep(0.5)
                continue
            try:
                h, w = frame.shape[:2]
                if w > _TARGET_WIDTH:
                    scale = _TARGET_WIDTH / float(w)
                    frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
                ok_enc, buf = cv2.imencode(
                    ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), _JPEG_QUALITY]
                )
                if ok_enc:
                    with self._lock:
                        self._jpeg = buf.tobytes()
                        self._updated_at = time.time()
                        self._error = None
            except Exception as e:
                with self._lock:
                    self._error = f"encode_failed: {e}"
            time.sleep(_CAPTURE_INTERVAL)
        with self._lock:
            if self._cap is not None:
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None


_ambient: Optional[AmbientCameraService] = None
_ambient_lock = threading.Lock()


def get_ambient_camera() -> AmbientCameraService:
    global _ambient
    with _ambient_lock:
        if _ambient is None:
            _ambient = AmbientCameraService()
        return _ambient
