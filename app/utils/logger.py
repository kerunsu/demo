"""
日志工具模块
提供统一的日志记录功能
"""
import logging
import sys
from pathlib import Path
from app.config import Config


def _make_console_stream_safe() -> None:
    """Windows GBK/重定向控制台遇到 emoji 时只转义字符，不让日志写入抛异常。"""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, 'reconfigure', None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(errors='backslashreplace')
        except (OSError, ValueError):
            # IDE 关闭或替换控制台句柄时保持原流，文件日志仍可继续工作。
            pass


_make_console_stream_safe()

# 共享文件处理器：所有 logger 复用同一个实例写 Config.LOG_FILE。
# 之前业务模块（socket_events / socket_handlers / recording_timeline 等）
# 调用 setup_logger 时未传 log_file，只有 console handler，业务日志从不落盘，
# 导致“点击无响应”等故障只能靠控制台现场，app.log 里一片空白。
_default_file_handler = None


def _default_log_file_handler(formatter: logging.Formatter) -> logging.Handler:
    """返回共享的 app.log 文件处理器（进程内单例）。"""
    global _default_file_handler
    if _default_file_handler is None:
        log_file = Config.LOG_FILE
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_file, encoding='utf-8')
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(formatter)
        _default_file_handler = handler
    return _default_file_handler


def setup_logger(name: str = 'app', log_file: Path = None, level: str = None) -> logging.Logger:
    """
    设置并返回日志记录器

    Args:
        name: 日志记录器名称
        log_file: 日志文件路径（可选，默认写入 Config.LOG_FILE）
        level: 日志级别（可选，默认使用Config.LOG_LEVEL）

    Returns:
        配置好的日志记录器
    """
    logger = logging.getLogger(name)

    # 如果已经配置过，直接返回
    if logger.handlers:
        return logger

    # 设置日志级别
    log_level = level or Config.LOG_LEVEL
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # 创建格式化器
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # 文件处理器：默认写入 Config.LOG_FILE（共享实例避免重复打开同一文件）；
    # 显式传入其他路径时单独创建该文件的处理器。
    target = Config.LOG_FILE if log_file is None else Path(log_file)
    if target == Config.LOG_FILE:
        logger.addHandler(_default_log_file_handler(formatter))
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(target, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


# 创建默认日志记录器
default_logger = setup_logger('app', Config.LOG_FILE)

