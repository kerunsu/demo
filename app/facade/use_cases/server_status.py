"""首个 facade vertical slice：server status。

该用例只聚合现有状态端口，旧 route 负责 Flask 错误日志和 response status，
presenter 负责旧 camelCase 字段。因此迁移不改变异常形态或对外 JSON。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from app.contracts.models import ServerStatusSnapshot


@dataclass(frozen=True)
class ServerStatusInputs:
    config_manager: Any
    analysis_service: Any
    model_status: Callable[[Mapping[str, Any]], Mapping[str, Any]]
    online_presence: Callable[[], Mapping[str, Any]]
    robot_control_mode: Callable[[], Any]
    child_media_mode: Callable[[], Any]
    media_session_meta: Callable[[], Mapping[str, Any]]
    runtime_status: Callable[[], Mapping[str, Any]]


class ServerStatusUseCase:
    def execute(self, inputs: ServerStatusInputs) -> ServerStatusSnapshot:
        current_config = inputs.config_manager.get_all_config()
        return ServerStatusSnapshot(
            statistics=inputs.analysis_service.get_statistics(),
            sessions=inputs.analysis_service.get_all_session_states(),
            model_status=inputs.model_status(current_config),
            global_mode=current_config.get("global", {}).get("mode"),
            snapshot_count=inputs.config_manager.get_snapshot_count(),
            history_count=len(inputs.config_manager.get_audit_logs(limit=1000)),
            online_presence=inputs.online_presence(),
            robot_control_mode=inputs.robot_control_mode(),
            child_media_mode=inputs.child_media_mode(),
            media_session_meta=inputs.media_session_meta(),
            robot_runtime=inputs.runtime_status(),
        )
