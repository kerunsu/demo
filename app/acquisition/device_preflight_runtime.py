"""Concrete Server/Robot Runtime first-sample preflight for configured devices."""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any

from app.acquisition.local_device_probe import probe_local_device
from app.monitor.configured_cameras import get_configured_camera_manager
ROBOT_RUNTIME_KEY = os.environ.get(
    "ROBOT_RUNTIME_KEY",
    os.environ.get("CHILD_MEDIA_AGENT_KEY", os.environ.get("ROBOT_AGENT_KEY", "")),
)
ROBOT_RUNTIME_HTTP_TIMEOUT = float(os.environ.get("ROBOT_RUNTIME_HTTP_TIMEOUT", "5"))


def perform_device_preflight(registry, runtime_status: dict[str, Any]) -> dict[str, Any]:
    checks = []
    runtime_profiles = []
    configured = [device for device in registry.list_devices() if device.enabled]
    for device in configured:
        if device.owner == "runtime":
            runtime_profiles.append({
                "deviceId": device.device_id,
                "trackId": device.track_id,
                "kind": device.kind,
                "selector": dict(device.selector),
                "required": device.required,
            })
        elif device.owner == "server":
            if device.kind == "video":
                observed = get_configured_camera_manager().wait_for_frame(device)
            else:
                observed = probe_local_device(device.kind, device.selector)
                observed["captureReady"] = False
                observed["error"] = observed.get("error") or "server_multitrack_capture_not_available"
            checks.append({
                "deviceId": device.device_id,
                "trackId": device.track_id,
                "kind": device.kind,
                "required": device.required,
                **observed,
                "captureReady": bool(observed.get("captureReady", observed.get("connected"))),
                "error": observed.get("error"),
            })

    runtime = runtime_status.get("primary")
    if runtime and runtime.get("online"):
        if runtime.get("compatible") is not True:
            defaults = [
                ("default.child.camera", "child_video", "video"),
                ("default.child.microphone", "child_audio", "audio"),
            ]
            checks.extend({
                "deviceId": device_id,
                "trackId": track_id,
                "kind": kind,
                "required": True,
                "connected": False,
                "captureReady": False,
                "error": "robot_runtime_upgrade_required",
                "detail": runtime.get("compatibilityReason") or "runtime_protocol_incompatible",
            } for device_id, track_id, kind in defaults)
            checks.extend({
                **profile,
                "connected": False,
                "captureReady": False,
                "error": "robot_runtime_upgrade_required",
                "detail": runtime.get("compatibilityReason") or "runtime_protocol_incompatible",
            } for profile in runtime_profiles)
            return {
                "ok": False,
                "checks": checks,
                "error": "robot_runtime_upgrade_required",
                "checkedAt": datetime.now(timezone.utc).isoformat(),
            }
        import requests

        headers = {"Content-Type": "application/json"}
        if ROBOT_RUNTIME_KEY:
            headers["X-Robot-Runtime-Key"] = ROBOT_RUNTIME_KEY
            headers["X-Child-Media-Agent-Key"] = ROBOT_RUNTIME_KEY
        response = requests.post(
            f"{str(runtime.get('advertisedUrl')).rstrip('/')}/devices/check",
            json={"devices": runtime_profiles},
            headers=headers,
            timeout=max(ROBOT_RUNTIME_HTTP_TIMEOUT, 10),
        )
        body = response.json() if response.content else {}
        if response.status_code != 200 or not body.get("ok"):
            raise RuntimeError(body.get("error") or "runtime_device_check_failed")
        capability = "multi-track-media-v1" in set(runtime.get("capabilities") or [])
        profile_by_id = {item["deviceId"]: item for item in runtime_profiles}
        for observed in body.get("checks") or []:
            profile = profile_by_id.get(str(observed.get("deviceId")))
            is_default = str(observed.get("deviceId", "")).startswith("default.child.")
            checks.append({
                **observed,
                "trackId": profile.get("trackId") if profile else (
                    "child_video" if observed.get("kind") == "video" else "child_audio"
                ),
                "required": profile.get("required", True) if profile else True,
                "captureReady": bool(observed.get("connected")) and (is_default or capability),
                "error": observed.get("error") or (
                    None if is_default or capability else "runtime_multitrack_capability_missing"
                ),
            })
    else:
        defaults = [
            ("default.child.camera", "child_video", "video"),
            ("default.child.microphone", "child_audio", "audio"),
        ]
        checks.extend({
            "deviceId": device_id, "trackId": track_id, "kind": kind,
            "required": True, "connected": False, "captureReady": False,
            "error": "robot_runtime_offline",
        } for device_id, track_id, kind in defaults)
        checks.extend({
            **profile, "connected": False, "captureReady": False,
            "error": "robot_runtime_offline",
        } for profile in runtime_profiles)

    required_ok = all(
        bool(item.get("connected")) and bool(item.get("captureReady"))
        for item in checks if item.get("required")
    )
    return {
        "ok": required_ok,
        "checks": checks,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }


__all__ = ["perform_device_preflight"]
