"""Socket 注册兼容 adapter。

它不重新注册事件、不改变 handler 顺序，只为后续按领域拆分注册器提供稳定
入口；旧注册函数作为显式依赖传入，避免 facade 反向 import ``app.sockets``。
"""

from __future__ import annotations

from typing import Any, Callable


def register_legacy_socket_events(
    socketio: Any,
    legacy_register: Callable[[Any], Any],
) -> Any:
    return legacy_register(socketio)
