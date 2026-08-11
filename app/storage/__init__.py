"""
存储模块
管理分析结果的持久化存储
"""

from app.storage.result_storage import (
    ResultStorage,
    get_result_storage,
    StoredResult
)
from app.storage.session_layout import SessionLayout, atomic_write_json, default_session_layout
from app.storage.session_validator import validate_session_directory

__all__ = [
    'ResultStorage',
    'get_result_storage',
    'StoredResult',
    'SessionLayout',
    'atomic_write_json',
    'default_session_layout',
    'validate_session_directory'
]
