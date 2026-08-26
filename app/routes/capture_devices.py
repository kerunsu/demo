"""Versioned control-plane API for the 0..N capture device registry.

Hardware discovery returns candidates only. A device is persisted only after
the operator explicitly adds it, and a frozen session snapshot remains
unchanged when the registry is edited.
"""

from __future__ import annotations

from dataclasses import asdict
import threading
import time

from flask import Blueprint, jsonify, request

from app.acquisition.device_registry import get_device_registry, stable_track_id
from app.contracts.models import DeploymentProfile, DeviceProfile
from app.monitor.configured_cameras import discover_local_cameras


capture_devices_bp = Blueprint("capture_devices", __name__, url_prefix="/api/v2/capture")
_CANDIDATE_CACHE_TTL_SEC = 120.0
_candidate_cache_lock = threading.RLock()
_candidate_cache: dict[int, dict] = {}
_candidate_cache_at = 0.0


def _replace_candidate_cache(candidates: list[dict]) -> None:
    global _candidate_cache_at
    with _candidate_cache_lock:
        _candidate_cache.clear()
        _candidate_cache.update({int(item["index"]): dict(item) for item in candidates})
        _candidate_cache_at = time.monotonic()


def _recent_candidate(index: int) -> dict | None:
    with _candidate_cache_lock:
        if time.monotonic() - _candidate_cache_at > _CANDIDATE_CACHE_TTL_SEC:
            return None
        candidate = _candidate_cache.get(int(index))
        return dict(candidate) if candidate is not None else None


def _bool_value(value, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"true", "false"}:
        return value.strip().lower() == "true"
    raise ValueError(f"{field}_must_be_boolean")


def _json_device(device: DeviceProfile) -> dict:
    value = asdict(device)
    value["deviceId"] = value.pop("device_id")
    value["trackId"] = value.pop("track_id")
    value["runtimeId"] = value.pop("runtime_id")
    value["schemaVersion"] = value.pop("schema_version")
    return value


def _device_from_json(payload: dict) -> DeviceProfile:
    device_id = str(payload.get("deviceId") or payload.get("device_id") or "").strip()
    kind = str(payload.get("kind") or "").strip().lower()
    role = str(payload.get("role") or "").strip()
    if not device_id or kind not in {"video", "audio"} or not role:
        raise ValueError("deviceId, kind(video/audio), and role are required")
    track_id = str(payload.get("trackId") or payload.get("track_id") or "").strip()
    return DeviceProfile(
        device_id=device_id,
        track_id=track_id or stable_track_id(device_id, kind, role),
        kind=kind,
        role=role,
        location=payload.get("location"),
        owner=str(payload.get("owner") or "server"),
        runtime_id=payload.get("runtimeId", payload.get("runtime_id")),
        selector=dict(payload.get("selector") or {}),
        enabled=_bool_value(payload.get("enabled", True), field="enabled"),
        required=_bool_value(payload.get("required", False), field="required"),
        priority=int(payload.get("priority", 0)),
        format=dict(payload.get("format") or {}),
        capabilities=dict(payload.get("capabilities") or {}),
    )


@capture_devices_bp.route("/devices", methods=["GET"])
def list_capture_devices():
    registry = get_device_registry()
    load_error = registry.get_load_error()
    if load_error:
        return jsonify({
            "success": False,
            "schemaVersion": 1,
            "devices": [],
            "error": "device_registry_load_failed",
            "detail": load_error,
        }), 503
    return jsonify({
        "success": True,
        "schemaVersion": 1,
        "devices": [_json_device(device) for device in registry.list_devices()],
    })


@capture_devices_bp.route("/devices", methods=["POST"])
def register_capture_device():
    try:
        device = _device_from_json(request.get_json(silent=True) or {})
        get_device_registry().register(device)
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"success": False, "error": "device_registry_unavailable", "detail": str(exc)}), 503
    except OSError as exc:
        return jsonify({"success": False, "error": "device_registry_save_failed", "detail": str(exc)}), 503
    return jsonify({"success": True, "device": _json_device(get_device_registry().get(device.device_id))}), 201


@capture_devices_bp.route("/devices/<device_id>", methods=["PATCH"])
def update_capture_device(device_id: str):
    payload = request.get_json(silent=True) or {}
    allowed = {
        "trackId": "track_id", "kind": "kind", "role": "role", "location": "location",
        "owner": "owner", "runtimeId": "runtime_id", "selector": "selector",
        "enabled": "enabled", "required": "required", "priority": "priority",
        "format": "format", "capabilities": "capabilities",
    }
    changes = {allowed[key]: payload[key] for key in allowed if key in payload}
    try:
        for field in ("enabled", "required"):
            if field in changes:
                changes[field] = _bool_value(changes[field], field=field)
        for field in ("selector", "format", "capabilities"):
            if field in changes and not isinstance(changes[field], dict):
                raise ValueError(f"{field}_must_be_object")
        if "priority" in changes:
            changes["priority"] = int(changes["priority"])
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    if not changes:
        return jsonify({"success": False, "error": "no_supported_fields"}), 400
    try:
        updated = get_device_registry().update(device_id, **changes)
    except KeyError:
        return jsonify({"success": False, "error": "device_not_found"}), 404
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"success": False, "error": "device_registry_unavailable", "detail": str(exc)}), 503
    except OSError as exc:
        return jsonify({"success": False, "error": "device_registry_save_failed", "detail": str(exc)}), 503
    return jsonify({"success": True, "device": _json_device(updated)})


@capture_devices_bp.route("/devices/<device_id>", methods=["DELETE"])
def unregister_capture_device(device_id: str):
    registry = get_device_registry()
    if registry.get(device_id) is None:
        return jsonify({"success": False, "error": "device_not_found"}), 404
    try:
        registry.unregister(device_id)
    except RuntimeError as exc:
        return jsonify({"success": False, "error": "device_registry_unavailable", "detail": str(exc)}), 503
    except OSError as exc:
        return jsonify({"success": False, "error": "device_registry_save_failed", "detail": str(exc)}), 503
    return jsonify({"success": True, "deviceId": device_id, "historyPreserved": True})


@capture_devices_bp.route("/devices/discover", methods=["POST"])
def discover_capture_devices():
    try:
        devices = get_device_registry().discover()
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"success": False, "error": "device_registry_unavailable", "detail": str(exc)}), 503
    except OSError as exc:
        return jsonify({"success": False, "error": "device_registry_save_failed", "detail": str(exc)}), 503
    return jsonify({"success": True, "devices": [_json_device(device) for device in devices]})


@capture_devices_bp.route("/devices/candidates", methods=["GET"])
def capture_device_candidates():
    """Probe local cameras without silently registering any of them."""
    try:
        configured_devices = [
            device for device in get_device_registry().list_devices()
            if device.kind == "video" and device.owner == "server" and "index" in device.selector
        ]
        configured = {
            int(device.selector.get("index")): device.device_id
            for device in configured_devices
        }
        # A configured camera may already be held open by the monitor preview.
        # Never ask DirectShow to open it a second time merely to render this
        # list; that native re-open caused python.exe heap corruption on Windows.
        candidates = discover_local_cameras(skip_indexes=configured)
        _replace_candidate_cache(candidates)
    except Exception as exc:
        return jsonify({"success": False, "error": "camera_discovery_failed", "detail": str(exc)}), 500
    for candidate in candidates:
        candidate["configuredDeviceId"] = configured.get(candidate["index"])
    discovered_indexes = {candidate["index"] for candidate in candidates}
    for device in configured_devices:
        index = int(device.selector["index"])
        if index not in discovered_indexes:
            candidates.append({
                "candidateId": f"server-camera-{index}",
                "index": index,
                "kind": "video",
                "name": str(device.capabilities.get("displayName") or f"摄像头 {index}"),
                "configuredDeviceId": device.device_id,
                "available": None,
                "probeSkipped": "configured_camera_not_reopened",
            })
    return jsonify({"success": True, "candidates": candidates})


@capture_devices_bp.route("/devices/candidates", methods=["POST"])
def add_capture_device_candidate():
    """Explicitly add one discovered Server camera to the persistent registry."""
    payload = request.get_json(silent=True) or {}
    try:
        index = int(payload.get("index"))
        if index < 0:
            raise ValueError("camera_index_must_be_non_negative")
        registry = get_device_registry()
        existing = next((
            item for item in registry.list_devices()
            if item.kind == "video" and item.owner == "server" and item.selector.get("index") == index
        ), None)
        if existing:
            return jsonify({"success": True, "created": False, "device": _json_device(existing)})
        candidate = _recent_candidate(index)
        if candidate is None:
            return jsonify({
                "success": False,
                "error": "camera_discovery_required",
                "detail": "请先重新扫描可用摄像头，再点击添加",
            }), 409
        server_videos = [
            item for item in registry.list_devices()
            if item.kind == "video" and item.owner == "server"
        ]
        role = "primary_environment" if not server_videos else "environment_secondary"
        device_id = f"server.camera.{index}"
        device = DeviceProfile(
            device_id=device_id,
            track_id=stable_track_id(device_id, "video", role),
            kind="video",
            role=role,
            location="server",
            owner="server",
            selector={"index": index},
            enabled=True,
            required=_bool_value(payload.get("required", False), field="required"),
            capabilities={"displayName": candidate["name"]},
        )
        registry.register(device)
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except (RuntimeError, OSError) as exc:
        return jsonify({"success": False, "error": "device_registry_save_failed", "detail": str(exc)}), 503
    return jsonify({"success": True, "created": True, "device": _json_device(device)}), 201


@capture_devices_bp.route("/snapshot", methods=["POST"])
def freeze_capture_snapshot():
    payload = request.get_json(silent=True) or {}
    try:
        required_modules = payload.get("requiredModules") or ()
        optional_modules = payload.get("optionalModules") or ()
        if not isinstance(required_modules, (list, tuple)) or not isinstance(optional_modules, (list, tuple)):
            raise ValueError("module_lists_must_be_arrays")
        deployment = DeploymentProfile(
            profile_id=str(payload.get("profileId") or "default"),
            version=str(payload.get("version") or "1"),
            child_media_mode=str(payload.get("childMediaMode") or "agent"),
            required_modules=tuple(str(item) for item in required_modules),
            optional_modules=tuple(str(item) for item in optional_modules),
            strict_preflight=_bool_value(payload.get("strictPreflight", False), field="strictPreflight"),
        )
        snapshot = get_device_registry().freeze(deployment)
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"success": False, "error": "device_registry_unavailable", "detail": str(exc)}), 503
    return jsonify({
        "success": True,
        "snapshotId": snapshot.snapshot_id,
        "deploymentProfileId": snapshot.deployment_profile_id,
        "createdAt": snapshot.created_at.wall_time_iso,
        "devices": [_json_device(device) for device in snapshot.devices],
    })


__all__ = ["capture_devices_bp"]
