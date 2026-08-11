"""
录制基类
定义所有录制器的统一接口
"""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from datetime import datetime
from app.utils.logger import setup_logger
from app.utils.exceptions import RecordingException

logger = setup_logger('recorder')


class BaseRecorder(ABC):
    """
    录制器基类
    
    所有录制器都应该继承此类并实现抽象方法
    """
    
    def __init__(self, output_path: Path, session_id: str):
        """
        初始化录制器
        
        Args:
            output_path: 输出文件路径
            session_id: 会话ID
        """
        self.output_path = Path(output_path)
        self.session_id = session_id
        self.is_recording = False
        self.start_time: Optional[datetime] = None
        self.frame_count = 0
        self._lock = None  # 子类可以设置锁
        
        # 确保输出目录存在
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"初始化录制器: {self.__class__.__name__}, 输出路径: {self.output_path}")
    
    @abstractmethod
    def start(self):
        """
        开始录制
        
        Raises:
            RecordingStartError: 如果启动失败
        """
        pass
    
    @abstractmethod
    def stop(self):
        """
        停止录制
        
        Raises:
            RecordingStopError: 如果停止失败
        """
        pass
    
    @abstractmethod
    def write(self, data):
        """
        写入数据
        
        Args:
            data: 要写入的数据（格式由子类定义）
            
        Raises:
            RecordingException: 如果写入失败
        """
        pass
    
    @abstractmethod
    def cleanup(self):
        """
        清理资源
        """
        pass
    
    def is_active(self) -> bool:
        """
        检查是否正在录制
        
        Returns:
            True如果正在录制，False否则
        """
        return self.is_recording
    
    def get_duration(self) -> Optional[float]:
        """
        获取录制时长（秒）
        
        Returns:
            录制时长，如果未开始则返回None
        """
        if not self.start_time:
            return None
        return (datetime.utcnow() - self.start_time).total_seconds()
    
    def get_frame_count(self) -> int:
        """
        获取已写入的帧数/块数
        
        Returns:
            帧数或块数
        """
        return self.frame_count
    
    def __enter__(self):
        """上下文管理器入口"""
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.stop()
        self.cleanup()
        return False

