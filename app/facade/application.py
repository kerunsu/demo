"""轻量应用容器，不引入 DI 框架，也不负责创建业务基础设施。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Dict


class ApplicationContainer:
    """显式、可替换、可关闭的服务注册表。

    ``bind_factory`` 默认按 key 缓存实例，便于保留现有单例身份；测试可以用
    ``bind_instance`` 注入 fake。容器本身不启动线程、不打开设备、不访问文件。
    """

    def __init__(self) -> None:
        self._factories: Dict[str, Callable[[], Any]] = {}
        self._instances: Dict[str, Any] = {}

    def bind_instance(self, key: str, instance: Any) -> None:
        self._instances[key] = instance

    def bind_factory(self, key: str, factory: Callable[[], Any]) -> None:
        self._factories[key] = factory

    def get(self, key: str) -> Any:
        if key in self._instances:
            return self._instances[key]
        if key not in self._factories:
            raise KeyError(key)
        self._instances[key] = self._factories[key]()
        return self._instances[key]

    def close(self) -> None:
        for instance in tuple(self._instances.values()):
            close = getattr(instance, "close", None)
            if callable(close):
                close()
        self._instances.clear()
