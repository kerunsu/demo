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
