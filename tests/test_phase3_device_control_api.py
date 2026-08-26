"""Contract tests for the versioned 0..N device control API."""

from __future__ import annotations

import uuid
import os
import runpy

import pytest


@pytest.fixture(scope="module")
def phase3_app(tmp_path_factory):
    old = {key: os.environ.get(key) for key in ("START_TEACHER_FRONTEND", "START_VOICE_SERVICE", "DIALOGUE_ENABLED", "CAPTURE_DEVICE_REGISTRY_PATH")}
    os.environ["START_TEACHER_FRONTEND"] = "0"
    os.environ["START_VOICE_SERVICE"] = "0"
    os.environ["DIALOGUE_ENABLED"] = "0"
    registry_path = tmp_path_factory.mktemp("phase3-device-api") / "devices.json"
    os.environ["CAPTURE_DEVICE_REGISTRY_PATH"] = str(registry_path)
    try:
        yield runpy.run_path("app.py", run_name="phase3_device_api")["app"], registry_path
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_phase3_device_control_api_registers_updates_freezes_and_deconfigures(phase3_app):
    from app.storage.repositories.device_profile_store import JsonDeviceProfileStore

    app, registry_path = phase3_app
    device_id = f"phase3-{uuid.uuid4().hex}"
    client = app.test_client()
    created = client.post("/api/v2/capture/devices", json={
        "deviceId": device_id,
        "kind": "video",
        "role": "environment_secondary",
        "required": False,
        "enabled": True,
    })
    assert created.status_code == 201
    body = created.get_json()
    assert body["success"] is True
    assert body["device"]["deviceId"] == device_id
    assert body["device"]["trackId"]

    listed = client.get("/api/v2/capture/devices")
    assert listed.status_code == 200
    assert any(item["deviceId"] == device_id for item in listed.get_json()["devices"])

    updated = client.patch(f"/api/v2/capture/devices/{device_id}", json={"required": True})
    assert updated.status_code == 200
    assert updated.get_json()["device"]["required"] is True
    assert JsonDeviceProfileStore(registry_path).load()[0].required is True

    snapshot = client.post("/api/v2/capture/snapshot", json={"strictPreflight": True})
    assert snapshot.status_code == 200
    snapshot_device = next(item for item in snapshot.get_json()["devices"] if item["deviceId"] == device_id)
    assert snapshot_device["required"] is True

    deleted = client.delete(f"/api/v2/capture/devices/{device_id}")
    assert deleted.status_code == 200
    assert deleted.get_json()["historyPreserved"] is True
    assert JsonDeviceProfileStore(registry_path).load() == ()


def test_phase3_device_control_api_rejects_invalid_boolean(phase3_app):
    app, _ = phase3_app
    response = app.test_client().post("/api/v2/capture/devices", json={
        "deviceId": "invalid-bool",
        "kind": "video",
        "role": "environment_secondary",
        "required": "yes",
    })
    assert response.status_code == 400
    assert response.get_json()["error"] == "required_must_be_boolean"


def test_local_camera_discovery_requires_explicit_add(monkeypatch, phase3_app):
    from app.routes import capture_devices

    app, _ = phase3_app
    discovery_calls = []

    def discover(*, skip_indexes=()):
        discovery_calls.append(tuple(skip_indexes))
        return [
            {"candidateId": "server-camera-3", "index": 3, "kind": "video", "name": "摄像头 3"}
        ]

    monkeypatch.setattr(capture_devices, "discover_local_cameras", discover)
    monkeypatch.setattr(capture_devices, "_candidate_cache_at", 0.0)
    capture_devices._candidate_cache.clear()
    client = app.test_client()

    discovered = client.get("/api/v2/capture/devices/candidates")
    assert discovered.status_code == 200
    assert discovered.get_json()["candidates"][0]["configuredDeviceId"] is None
    assert client.get("/api/v2/capture/devices").get_json()["devices"] == []

    added = client.post("/api/v2/capture/devices/candidates", json={"index": 3})
    assert added.status_code == 201
    device = added.get_json()["device"]
    assert device["deviceId"] == "server.camera.3"
    assert device["owner"] == "server"
    assert device["selector"] == {"index": 3}
    # POST consumes the recent candidate instead of immediately reopening the
    # same DirectShow camera for a second scan.
    assert discovery_calls == [()]

    client.delete("/api/v2/capture/devices/server.camera.3")


def test_discovery_does_not_reopen_an_already_configured_camera(monkeypatch, phase3_app):
    from app.routes import capture_devices

    app, _ = phase3_app
    client = app.test_client()
    created = client.post("/api/v2/capture/devices", json={
        "deviceId": "server.camera.4",
        "kind": "video",
        "role": "primary_environment",
        "owner": "server",
        "selector": {"index": 4},
        "required": False,
        "enabled": True,
        "capabilities": {"displayName": "环境摄像头"},
    })
    assert created.status_code == 201
    observed = []

    def discover(*, skip_indexes=()):
        observed.append(set(skip_indexes))
        return []

    monkeypatch.setattr(capture_devices, "discover_local_cameras", discover)
    discovered = client.get("/api/v2/capture/devices/candidates")
    assert discovered.status_code == 200
    assert observed == [{4}]
    candidate = discovered.get_json()["candidates"][0]
    assert candidate["configuredDeviceId"] == "server.camera.4"
    assert candidate["probeSkipped"] == "configured_camera_not_reopened"

    client.delete("/api/v2/capture/devices/server.camera.4")


def test_add_candidate_requires_a_recent_discovery(monkeypatch, phase3_app):
    from app.routes import capture_devices

    app, _ = phase3_app
    monkeypatch.setattr(capture_devices, "_candidate_cache_at", 0.0)
    capture_devices._candidate_cache.clear()
    response = app.test_client().post(
        "/api/v2/capture/devices/candidates", json={"index": 5}
    )
    assert response.status_code == 409
    assert response.get_json()["error"] == "camera_discovery_required"
