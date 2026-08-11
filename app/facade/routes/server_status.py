"""server status route adapter 的无框架部分。"""

from __future__ import annotations

from typing import Any

from app.facade.presenters.server_status import present_server_status
from app.facade.use_cases.server_status import ServerStatusInputs, ServerStatusUseCase


def execute_server_status(
    use_case: ServerStatusUseCase,
    inputs: ServerStatusInputs,
) -> dict[str, Any]:
    """执行 status 用例并生成旧 JSON payload。

    Flask request、异常日志和 HTTP 状态码仍留在兼容 route 中；这样该 adapter
    可以在 Flask test client 和纯单元测试中复用。
    """

    return present_server_status(use_case.execute(inputs))
