"""Operator-facing device and recording overview (additive v2 API)."""

from __future__ import annotations

import os
import threading
from dataclasses import asdict
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from app.acquisition.device_registry import get_device_registry
from app.storage.session_catalog import build_session_catalog, resolve_session_folder
from app.utils.logger import setup_logger

logger = setup_logger("control_overview")

control_overview_bp = Blueprint("control_overview", __name__, url_prefix="/api/v2/control")
_check_lock = threading.RLock()
_last_device_checks: dict[str, dict] = {}


def _disabled_runtime_status() -> dict:
    return {"onlineCount": 0, "runtimes": [], "primary": None, "enabled": False}


def _reveal_local_folder(folder) -> None:
    if os.name != "nt" or not hasattr(os, "startfile"):
        raise NotImplementedError("folder_reveal_not_supported")
    os.startfile(str(folder))  # type: ignore[attr-defined]


def _configured_devices(runtime_status: dict) -> list[dict]:
    online_ids = {
        str(item.get("id"))
        for item in runtime_status.get("runtimes", [])
        if item.get("online")
    }
    devices = []
    for profile in get_device_registry().list_devices():
        item = asdict(profile)
        if item.get("owner") == "runtime":
            continue
        runtime_id = item.pop("runtime_id")
        item["deviceId"] = item.pop("device_id")
        item["trackId"] = item.pop("track_id")
        item["runtimeId"] = runtime_id
        item["schemaVersion"] = item.pop("schema_version")
        with _check_lock:
            observed = dict(_last_device_checks.get(item["deviceId"], {}))
        if not item.get("enabled"):
            item["connectionStatus"] = "disabled"
            item["captureReady"] = False
        elif runtime_id and str(runtime_id) in online_ids:
            item["connectionStatus"] = "runtime_online_unprobed"
            item["captureReady"] = False
        else:
            item["connectionStatus"] = "unprobed"
            item["captureReady"] = False
        if observed:
            item["connected"] = bool(observed.get("connected"))
            item["captureReady"] = bool(observed.get("captureReady"))
            item["connectionStatus"] = (
                "connected" if item["captureReady"]
                else "connected_not_capture_enabled" if observed.get("connected")
                else "check_failed"
            )
            item["lastCheck"] = observed
        item["operatorHint"] = (
            "已通过首样本检查，将在下一场以同一 session 时间基准录制"
            if item.get("captureReady")
            else "已连接不等于已接入多轨录制；采集适配器未就绪时不会参与正式录制"
        )
        devices.append(item)
    return devices


def _default_devices(runtime_status: dict) -> list[dict]:
    status = "browser_unprobed"
    with _check_lock:
        camera_check = dict(_last_device_checks.get("default.child.camera", {}))
        microphone_check = dict(_last_device_checks.get("default.child.microphone", {}))
    return [
        {
            "deviceId": "default.child.camera",
            "trackId": "child_video",
            "kind": "video",
            "role": "primary_child",
            "required": True,
            "enabled": True,
            "managedByDefault": True,
            "connectionStatus": "connected" if camera_check.get("connected") else ("check_failed" if camera_check else status),
            "captureReady": bool(camera_check.get("connected")),
            "lastCheck": camera_check or None,
            "filename": "video.avi",
        },
        {
            "deviceId": "default.child.microphone",
            "trackId": "child_audio",
            "kind": "audio",
            "role": "primary_child",
            "required": True,
            "enabled": True,
            "managedByDefault": True,
            "connectionStatus": "connected" if microphone_check.get("connected") else ("check_failed" if microphone_check else status),
            "captureReady": bool(microphone_check.get("connected")),
            "lastCheck": microphone_check or None,
            "filename": "audio.wav",
        },
    ]


@control_overview_bp.route("/overview", methods=["GET"])
def get_control_overview():
    try:
        limit = int(request.args.get("limit", 200))
    except ValueError:
        return jsonify({"success": False, "error": "limit_must_be_integer"}), 400
    runtime_status = _disabled_runtime_status()
    try:
        configured = _configured_devices(runtime_status)
    except RuntimeError as exc:
        return jsonify({"success": False, "error": "device_registry_unavailable", "detail": str(exc)}), 503
    catalog = build_session_catalog(limit=limit)
    return jsonify({
        "success": True,
        "schemaVersion": 1,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "devices": {
            "defaults": _default_devices(runtime_status),
            "configured": configured,
            "runtime": runtime_status,
            "allRequiredReady": all(
                item.get("captureReady")
                for item in _default_devices(runtime_status) + configured
                if item.get("enabled") and item.get("required")
            ),
        },
        "recordings": catalog,
    })


@control_overview_bp.route("/devices/check", methods=["POST"])
def check_control_devices():
    try:
        # Demo 的主摄像头和麦克风由儿童端浏览器持有，服务端不能替浏览器
        # 申请权限或伪造首样本检查。明确返回待儿童端授权，避免误报
        # Robot Runtime 离线（Demo 根本不依赖 Runtime）。
        checks = [
            {
                "deviceId": "default.child.camera",
                "trackId": "child_video",
                "kind": "video",
                "required": True,
                "connected": False,
                "captureReady": False,
                "error": "browser_permission_required",
            },
            {
                "deviceId": "default.child.microphone",
                "trackId": "child_audio",
                "kind": "audio",
                "required": True,
                "connected": False,
                "captureReady": False,
                "error": "browser_permission_required",
            },
        ]
        with _check_lock:
            for check in checks:
                if check.get("deviceId"):
                    _last_device_checks[str(check["deviceId"])] = dict(check)
        return jsonify({
            "success": True,
            "checks": checks,
            "checkedAt": datetime.now(timezone.utc).isoformat(),
            "allConnected": False,
            "error": "browser_permission_required",
        })
    except Exception as exc:
        return jsonify({"success": False, "error": "runtime_device_check_failed", "detail": str(exc)}), 502


@control_overview_bp.route("/actions/stop-robot", methods=["POST"])
def stop_robot_output():
    """Compatibility path: the Demo has no robot output to stop."""
    return jsonify({
        "success": False,
        "action": "stop_robot",
        "error": "demo_capability_disabled",
    }), 410


@control_overview_bp.route("/actions/stop-audio", methods=["POST"])
def stop_session_audio():
    """Stop audio in one exact runtime session; never broadcast a false success."""
    body = request.get_json(silent=True) or {}
    session_id = body.get("sessionId") or body.get("session_id")
    if not session_id:
        return jsonify({
            "success": False,
            "action": "stop_audio",
            "error": "session_id_required",
            "detail": "当前没有可定位的录制/运行会话",
        }), 400
    try:
        from app.audio import get_audio_controller

        controller = get_audio_controller()
        if controller is None:
            return jsonify({
                "success": False,
                "action": "stop_audio",
                "error": "audio_controller_unavailable",
            }), 503
        sent = bool(controller.stop_audio(str(session_id), immediate=True))
        return jsonify({
            "success": sent,
            "action": "stop_audio",
            "sessionId": str(session_id),
            "message": "声音停止命令已下发" if sent else "声音停止命令下发失败",
            "verification": "socket_dispatch",
        }), 200 if sent else 502
    except Exception as exc:
        return jsonify({
            "success": False,
            "action": "stop_audio",
            "error": "audio_stop_failed",
            "detail": str(exc),
        }), 500


def _local_console_only() -> bool:
    """reveal/删除/上锁等本机文件操作只允许服务器本机访问。"""
    return request.remote_addr in {None, "127.0.0.1", "::1"}


def _emit_to_rooms(socketio, event: str, payload: dict, session_id: str) -> None:
    """向该会话的教师房间和儿童房间广播事件（房间不存在时静默）。"""
    if socketio is None:
        return
    try:
        socketio.emit(
            event, payload, room=f"session_{session_id}_teacher"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("广播 %s 到教师房间失败: %s", event, exc)
    try:
        socketio.emit(
            event, payload, room=f"session_{session_id}_child"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("广播 %s 到儿童房间失败: %s", event, exc)


@control_overview_bp.route("/recordings/active", methods=["GET"])
def list_active_recordings_route():
    """控制台查看当前进行中的录制会话（避免忘记结束课程一直占用内存）。"""
    try:
        from app.services.recording_admin import list_active_recordings

        return jsonify({
            "success": True,
            "recordings": list_active_recordings(),
        })
    except Exception as exc:
        logger.error("列举活跃录制失败: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


@control_overview_bp.route("/recordings/<session_id>/force-stop", methods=["POST"])
def force_stop_recording_route(session_id: str):
    """强制关闭一场进行中的录制；教师端收到提示后需重新选择角色课程。"""
    try:
        from app.services.recording_admin import force_stop_recording

        result = force_stop_recording(session_id)
        if not result.get("ok"):
            status_code = 404 if result.get("error") == "active_recording_not_found" else 502
            return jsonify({"success": False, **result}), status_code
        # 通知教师端：录制被强制关闭，需要重新选择角色和课程
        try:
            from flask import current_app

            socketio_instance = current_app.extensions.get("socketio")
        except Exception:  # noqa: BLE001
            socketio_instance = None
        _emit_to_rooms(socketio_instance, "recording_forced_stop", result, session_id)
        return jsonify({"success": True, **result})
    except Exception as exc:
        logger.error("强制关闭录制失败: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


@control_overview_bp.route("/recordings/<folder_name>/lock", methods=["POST"])
def lock_recording_route(folder_name: str):
    """上锁/解锁历史会话（删除前必须先解锁）。body: {locked: bool}"""
    if not _local_console_only():
        return jsonify({"success": False, "error": "local_console_only"}), 403
    body = request.get_json(silent=True) or {}
    locked = bool(body.get("locked", body.get("lock", True)))
    try:
        from app.services.recording_admin import set_folder_locked

        entry = set_folder_locked(folder_name, locked)
        return jsonify({"success": True, "folderName": folder_name, **entry})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("设置录制锁失败: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


@control_overview_bp.route("/recordings/<folder_name>", methods=["DELETE"])
def delete_recording_route(folder_name: str):
    """删除一个历史会话文件夹；已上锁的会被拒绝。"""
    if not _local_console_only():
        return jsonify({"success": False, "error": "local_console_only"}), 403
    try:
        from app.services.recording_admin import delete_session_folder

        result = delete_session_folder(folder_name)
        if not result.get("ok"):
            status_code = 403 if result.get("error") == "recording_locked" else (
                404 if result.get("error") == "session_folder_not_found" else 400
            )
            return jsonify({"success": False, **result}), status_code
        return jsonify({"success": True, **result})
    except Exception as exc:
        logger.error("删除录制会话失败: %s", exc, exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500


@control_overview_bp.route("/sessions/<folder_name>/reveal", methods=["POST"])
def reveal_session_folder(folder_name: str):
    if not _local_console_only():
        return jsonify({"success": False, "error": "local_console_only"}), 403
    try:
        folder = resolve_session_folder(folder_name)
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except FileNotFoundError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    try:
        _reveal_local_folder(folder)
    except NotImplementedError as exc:
        return jsonify({"success": False, "error": str(exc)}), 501
    except OSError as exc:
        return jsonify({"success": False, "error": "folder_reveal_failed", "detail": str(exc)}), 500
    return jsonify({"success": True, "folderName": folder.name})


__all__ = ["control_overview_bp"]
