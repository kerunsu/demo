"""后端门面：只负责 transport 适配、校验、用例接线和旧契约呈现。"""

from .bootstrap import ApplicationContainer, create_application_container

__all__ = ["ApplicationContainer", "create_application_container"]
