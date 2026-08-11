"""server status 的旧 JSON 呈现，不改变字段命名和 envelope。"""

from __future__ import annotations

from typing import Any

from app.contracts.models import ServerStatusSnapshot


def present_server_status(snapshot: ServerStatusSnapshot) -> dict[str, Any]:
    return {
        "success": True,
        "statistics": snapshot.statistics,
        "sessions": snapshot.sessions,
        "modelStatus": snapshot.model_status,
        "globalMode": snapshot.global_mode,
        "snapshotCount": snapshot.snapshot_count,
        "historyCount": snapshot.history_count,
        "onlinePresence": snapshot.online_presence,
        "robotControlMode": snapshot.robot_control_mode,
        "childMediaMode": snapshot.child_media_mode,
        "mediaSessionMeta": snapshot.media_session_meta,
        "robotRuntime": snapshot.robot_runtime,
    }
