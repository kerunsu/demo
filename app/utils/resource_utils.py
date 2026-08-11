"""
资源文件处理工具
"""
import os
import random
from pathlib import Path
from typing import Optional, Tuple
from app.config import Config
from app.utils.logger import setup_logger

logger = setup_logger('resource_utils')


def get_random_file_from_folder(
    folder_path: str,
    extensions: Tuple[str, ...] = ('.png', '.jpg', '.jpeg', '.gif', '.bmp')
) -> Optional[str]:
    """
    从文件夹中随机选择一个文件
    
    Args:
        folder_path: 相对于 static 的文件夹路径，如 "resources/images/naming/001/"
        extensions: 允许的文件扩展名元组
    
    Returns:
        随机文件的完整相对路径，如 "resources/images/naming/001/003.jpg"
        如果文件夹不存在或为空，返回 None
    
    Example:
        >>> get_random_file_from_folder("resources/images/naming/001/")
        "resources/images/naming/001/005.jpg"
    """
    try:
        # 构建完整路径
        full_path = Config.STATIC_DIR / folder_path.lstrip('/')
        
        if not full_path.exists():
            logger.warning(f"文件夹不存在: {full_path}")
            return None
        
        if not full_path.is_dir():
            logger.warning(f"路径不是文件夹: {full_path}")
            return None
        
        # 获取所有符合扩展名的文件
        files = [
            f for f in full_path.iterdir()
            if f.is_file() and f.suffix.lower() in extensions
        ]
        
        if not files:
            logger.warning(f"文件夹为空或没有符合条件的文件: {full_path}")
            return None
        
        # 随机选择一个文件
        selected = random.choice(files)
        
        # 返回相对路径（相对于 static 目录）
        relative_path = f"{folder_path.rstrip('/')}/{selected.name}"
        
        logger.debug(f"从文件夹 {folder_path} 随机选择: {selected.name}")
        return relative_path
        
    except Exception as e:
        logger.error(f"获取随机文件失败: {folder_path}, 错误: {e}")
        return None


def get_first_file_from_folder(
    folder_path: str,
    extensions: Tuple[str, ...] = ('.png', '.jpg', '.jpeg', '.gif', '.bmp')
) -> Optional[str]:
    """
    从文件夹中获取第一个文件（按字母顺序排序）
    用于生成缩略图
    
    Args:
        folder_path: 相对于 static 的文件夹路径
        extensions: 允许的文件扩展名元组
    
    Returns:
        第一个文件的完整相对路径
        如果文件夹不存在或为空，返回 None
    
    Example:
        >>> get_first_file_from_folder("resources/images/naming/001/")
        "resources/images/naming/001/001.png"
    """
    try:
        # 构建完整路径
        full_path = Config.STATIC_DIR / folder_path.lstrip('/')
        
        if not full_path.exists() or not full_path.is_dir():
            logger.warning(f"文件夹不存在: {full_path}")
            return None
        
        # 获取所有符合扩展名的文件并排序
        files = sorted([
            f for f in full_path.iterdir()
            if f.is_file() and f.suffix.lower() in extensions
        ])
        
        if not files:
            logger.warning(f"文件夹为空: {full_path}")
            return None
        
        # 返回第一个文件的相对路径
        first_file = files[0]
        relative_path = f"{folder_path.rstrip('/')}/{first_file.name}"
        
        logger.debug(f"从文件夹 {folder_path} 获取第一个文件: {first_file.name}")
        return relative_path
        
    except Exception as e:
        logger.error(f"获取第一个文件失败: {folder_path}, 错误: {e}")
        return None


AUDIO_EXTENSIONS = ('.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac')


def is_folder_path(path: str) -> bool:
    """
    判断路径是否为文件夹路径（以 / 结尾）
    
    Args:
        path: 文件路径字符串
    
    Returns:
        True 如果路径以 / 结尾（表示文件夹）
        False 否则
    
    Example:
        >>> is_folder_path("resources/images/naming/001/")
        True
        >>> is_folder_path("resources/images/cat.png")
        False
    """
    return bool(path) and path.replace('\\', '/').endswith('/')


def resolve_playable_audio_path(path: str) -> Optional[str]:
    """
    将配置路径解析为可播放的单个音频文件（相对 static）。

    - 普通文件：原样返回（规范化斜杠）
    - 文件夹（以 / 结尾，或磁盘上是目录）：在目录内随机选一个音频文件
    """
    if not path:
        return None
    p = path.strip().replace('\\', '/')
    if p.startswith('/static/'):
        p = p[len('/static/'):]

    # 显式文件夹，或无扩展名且磁盘上是目录
    looks_folder = is_folder_path(p)
    if not looks_folder:
        abs_path = Config.STATIC_DIR / p.lstrip('/')
        if abs_path.exists() and abs_path.is_dir():
            looks_folder = True
            p = p.rstrip('/') + '/'

    if looks_folder:
        picked = get_random_file_from_folder(p, extensions=AUDIO_EXTENSIONS)
        if not picked:
            logger.warning(f"音频文件夹无法解析出可播文件: {p}")
        return picked

    abs_file = Config.STATIC_DIR / p.lstrip('/')
    if not abs_file.exists() or not abs_file.is_file():
        logger.warning(f"音频文件不存在: {abs_file}")
        return None
    return p


def folder_exists(folder_path: str) -> bool:
    """
    检查文件夹是否存在
    
    Args:
        folder_path: 相对于 static 的文件夹路径
    
    Returns:
        True 如果文件夹存在，False 否则
    """
    try:
        full_path = Config.STATIC_DIR / folder_path.lstrip('/')
        return full_path.exists() and full_path.is_dir()
    except Exception:
        return False


def count_files_in_folder(
    folder_path: str,
    extensions: Tuple[str, ...] = ('.png', '.jpg', '.jpeg', '.gif', '.bmp')
) -> int:
    """
    统计文件夹内符合条件的文件数量
    
    Args:
        folder_path: 相对于 static 的文件夹路径
        extensions: 允许的文件扩展名元组
    
    Returns:
        文件数量
    """
    try:
        full_path = Config.STATIC_DIR / folder_path.lstrip('/')
        
        if not full_path.exists() or not full_path.is_dir():
            return 0
        
        files = [
            f for f in full_path.iterdir()
            if f.is_file() and f.suffix.lower() in extensions
        ]
        
        return len(files)
        
    except Exception as e:
        logger.error(f"统计文件失败: {folder_path}, 错误: {e}")
        return 0
