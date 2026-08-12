import time

from app.contracts.models import DeviceProfile
from app.monitor.configured_cameras import ConfiguredCameraPreviewManager


class _FakeStream:
    def __init__(self):
        self.enabled = False
        self.index = None

    def control(self, *, enabled, device_id=None):
        self.enabled = enabled
        if device_id is not None:
            self.index = device_id
        return self.status()

    def status(self):
        return {
            "enabled": self.enabled,
            "hasFrame": self.enabled,
            "updatedAt": time.time(),
            "error": None,
        }

    def get_jpeg(self):
        return b"jpeg" if self.enabled else None


def test_preview_manager_tracks_only_synced_configured_cameras(monkeypatch):
    from app.monitor import configured_cameras

    monkeypatch.setattr(configured_cameras, "AmbientCameraService", _FakeStream)
    manager = ConfiguredCameraPreviewManager()
    first = DeviceProfile(
        device_id="server.camera.0", track_id="a", kind="video",
        role="primary_environment", owner="server", selector={"index": 0},
    )
    second = DeviceProfile(
        device_id="server.camera.2", track_id="b", kind="video",
        role="environment_secondary", owner="server", selector={"index": 2},
    )

    assert [item["deviceId"] for item in manager.sync([first, second])] == [
        "server.camera.0", "server.camera.2"
    ]
    assert manager.get_jpeg("server.camera.2") == b"jpeg"
    manager.sync([second])
    assert manager.status("server.camera.0") is None
