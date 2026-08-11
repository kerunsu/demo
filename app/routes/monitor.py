"""监控台 Snapshot / 预览 / 环境摄像头 API"""
from __future__ import annotations

import base64

from flask import Blueprint, Response, jsonify, request

from app.monitor import get_monitor_snapshot
from app.monitor.ambient_camera import get_ambient_camera
from app.utils.logger import setup_logger

logger = setup_logger("monitor_routes")

monitor_bp = Blueprint("monitor", __name__, url_prefix="/api/monitor")


@monitor_bp.route("/snapshot", methods=["GET"])
def monitor_snapshot():
    """
    GET /api/monitor/snapshot
    GET /api/monitor/snapshot?trainingSessionId=<id>
    """
    try:
        ts_id = request.args.get("trainingSessionId") or request.args.get("training_session_id")
        data = get_monitor_snapshot(ts_id)
        # 活跃训练时强制开启环境摄像头
        ambient = get_ambient_camera()
        if data.get("active"):
            ambient.set_forced(True)
        else:
            ambient.set_forced(False)
        data["ambient"] = ambient.status()
        return jsonify({"success": True, "data": data})
    except Exception as e:
        logger.error("MonitorSnapshot 失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@monitor_bp.route("/remote-preview.jpg", methods=["GET"])
def remote_preview_jpg():
    """远端 agent 预览快通道：直接返回最近一帧 JPEG。"""
    from app.config import Config
    from app.routes.media_upload import get_last_probe_frame

    if not bool(getattr(Config, "MONITOR_PREVIEW_ENABLED", True)):
        return Response(status=204)

    media_session_id = (
        request.args.get("mediaSessionId")
        or request.args.get("media_session_id")
        or request.args.get("sessionId")
    )
    if not media_session_id:
        # 尝试从 snapshot 会话解析
        try:
            snap = get_monitor_snapshot(None)
            media_session_id = (snap.get("session") or {}).get("mediaSessionId")
        except Exception:
            media_session_id = None
    if not media_session_id:
        return Response(status=204)

    frame_b64 = get_last_probe_frame(media_session_id)
    if not frame_b64:
        return Response(status=204)
    try:
        raw = base64.b64decode(frame_b64)
    except Exception:
        return Response(status=204)
    return Response(
        raw,
        mimetype="image/jpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@monitor_bp.route("/ambient/devices", methods=["GET"])
def ambient_devices():
    try:
        devices = get_ambient_camera().list_devices()
        return jsonify({"success": True, "devices": devices, "status": get_ambient_camera().status()})
    except Exception as e:
        logger.error("枚举环境摄像头失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e), "devices": []}), 500


@monitor_bp.route("/ambient/control", methods=["POST"])
def ambient_control():
    try:
        body = request.get_json(silent=True) or {}
        enabled = bool(body.get("enabled"))
        device_id = body.get("deviceId", body.get("device_id"))
        status = get_ambient_camera().control(enabled=enabled, device_id=device_id)
        return jsonify({"success": True, "status": status})
    except Exception as e:
        logger.error("环境摄像头控制失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@monitor_bp.route("/ambient/preview.jpg", methods=["GET"])
def ambient_preview_jpg():
    cam = get_ambient_camera()
    jpeg = cam.get_jpeg()
    if not jpeg:
        return Response(status=204)
    return Response(
        jpeg,
        mimetype="image/jpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@monitor_bp.route("/teacher-connections/disconnect", methods=["POST"])
def teacher_connection_disconnect():
    """终止一条教师端连接（按 socket sid）。

    仅接受当前仍在线的 teacher 角色连接；被踢连接的前端会收到 disconnect
    并提示刷新/重连，其持有的控制权在 TTL 后自动释放。
    """
    try:
        body = request.get_json(silent=True) or {}
        sid = str(body.get("sid") or "").strip()
        if not sid:
            return jsonify({"success": False, "error": "sid_missing"}), 400

        from app.sockets.events import get_online_presence_snapshot

        snapshot = get_online_presence_snapshot()
        teacher_sids = {
            str(item.get("sid"))
            for item in (snapshot.get("connections") or {}).get("teacher") or []
        }
        if sid not in teacher_sids:
            return jsonify({"success": False, "error": "teacher_connection_not_found"}), 404

        # app.py 在模块级自行创建 SocketIO（不经过 app.create_app），
        # 因此从 app.extensions 取实例，避免 app/__init__.py 的 None 占位。
        from flask import current_app

        socketio_instance = current_app.extensions.get("socketio")
        if socketio_instance is None:
            return jsonify({"success": False, "error": "socketio_not_ready"}), 500
        # 新版 flask_socketio 不再暴露 disconnect 代理，改走底层 Server。
        server = getattr(socketio_instance, "server", None) or socketio_instance
        server.disconnect(sid, namespace="/")
        logger.info("已终止教师连接 sid=%s", sid)
        return jsonify({"success": True, "disconnected": sid})
    except Exception as e:
        logger.error("终止教师连接失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
