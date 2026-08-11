"""第二阶段 composition root 的无副作用骨架。

真正的 Flask/SocketIO/数据库/线程装配暂时仍由 ``app.py`` 兼容入口拥有。本
模块只定义创建顺序和可替换注册点，导入它不会拉起服务或初始化设备。
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from time import monotonic

from app.acquisition.device_registry import InMemoryDeviceRegistry, configure_device_registry
from app.config import BASE_DIR
from app.contracts.ports import Clock
from app.storage.repositories.device_profile_store import JsonDeviceProfileStore

from .application import ApplicationContainer
from .use_cases.server_status import ServerStatusUseCase


class SystemClock(Clock):
    def monotonic_seconds(self) -> float:
        return monotonic()

    def wall_time_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()


def create_application_container() -> ApplicationContainer:
    """创建纯应用层容器；基础设施由现有 composition root 显式提供。"""

    container = ApplicationContainer()
    container.bind_instance("clock", SystemClock())
    registry_path = Path(
        os.environ.get("CAPTURE_DEVICE_REGISTRY_PATH")
        or (BASE_DIR / "config" / "capture_devices.json")
    )
    device_registry = InMemoryDeviceRegistry(
        clock=container.get("clock"),
        profile_store=JsonDeviceProfileStore(registry_path),
    )
    configure_device_registry(device_registry)
    container.bind_instance("device_registry", device_registry)
    container.bind_factory("server_status_use_case", ServerStatusUseCase)
    return container
