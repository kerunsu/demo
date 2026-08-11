"""
自定义异常类
定义应用特定的异常类型
"""


class AppException(Exception):
    """应用基础异常类"""
    pass


class SessionException(AppException):
    """会话相关异常"""
    pass


class SessionNotFoundError(SessionException):
    """会话不存在异常"""
    pass


class SessionAlreadyExistsError(SessionException):
    """会话已存在异常"""
    pass


class SessionMaxLimitError(SessionException):
    """达到最大会话数限制异常"""
    pass


class RecordingException(AppException):
    """录制相关异常"""
    pass


class RecordingStartError(RecordingException):
    """录制启动失败异常"""
    pass


class RecordingStopError(RecordingException):
    """录制停止失败异常"""
    pass


class AnalysisException(AppException):
    """分析相关异常"""
    pass


class AnalysisInitializationError(AnalysisException):
    """分析器初始化失败异常"""
    pass


class AnalysisExecutionError(AnalysisException):
    """分析执行失败异常"""
    pass


class StorageException(AppException):
    """存储相关异常"""
    pass


class FileNotFoundError(StorageException):
    """文件不存在异常"""
    pass


class FileWriteError(StorageException):
    """文件写入失败异常"""
    pass

