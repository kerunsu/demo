"""
数据缓冲区
用于 Type B（滑动窗口分析）场景中的数据缓存
"""
import threading
import time
from collections import deque
from typing import Optional, List, Tuple, Any
from dataclasses import dataclass, field
import numpy as np

from app.core.models import WindowData
from app.utils.logger import setup_logger

logger = setup_logger('data_buffer')


def normalize_media_timestamp(timestamp: Optional[float], *, now: Optional[float] = None) -> float:
    """
    统一媒体时间戳为 Unix 秒。

    robot_runtime / 部分浏览器上行使用毫秒（time.time()*1000）；
    若直接写入 buffer，按秒做的窗口清理永远剔不掉旧帧，live_window 也会失效。
    """
    current = time.time() if now is None else float(now)
    if timestamp is None:
        return current
    try:
        ts = float(timestamp)
    except (TypeError, ValueError):
        return current
    # 毫秒 epoch ~1e12；秒 epoch ~1e9
    if ts > 1e11:
        ts = ts / 1000.0
    # 时钟严重偏离时改用服务端接收时刻，保证滑动窗口可用
    if abs(ts - current) > 120.0:
        return current
    return ts


@dataclass
class BufferConfig:
    """缓冲区配置"""
    window_size: float = 10.0         # 窗口大小（秒）
    max_video_frames: int = 300       # 最大视频帧数（10秒 * 30fps）
    max_audio_chunks: int = 500       # 最大音频块数
    cleanup_interval: float = 1.0     # 清理间隔（秒）


class DataBuffer:
    """
    滑动窗口数据缓冲区
    
    用于缓存过去N秒的视频帧和音频块，支持：
    - 添加视频帧/音频块
    - 获取窗口内的数据
    - 自动清理过期数据
    
    典型使用场景：注意力检测（分析过去10秒的数据）
    """
    
    def __init__(
        self,
        session_id: str,
        window_size: float = 10.0,
        config: Optional[BufferConfig] = None
    ):
        """
        初始化数据缓冲区
        
        Args:
            session_id: 会话ID
            window_size: 窗口大小（秒）
            config: 缓冲区配置
        """
        self._session_id = session_id
        self._window_size = window_size
        self._config = config or BufferConfig(window_size=window_size)
        
        # 视频帧缓冲: (timestamp, frame)
        self._video_buffer: deque = deque(maxlen=self._config.max_video_frames)
        # 音频块缓冲: (timestamp, chunk)
        self._audio_buffer: deque = deque(maxlen=self._config.max_audio_chunks)
        
        # 线程锁
        self._video_lock = threading.Lock()
        self._audio_lock = threading.Lock()
        
        # 统计信息
        self._total_video_frames = 0
        self._total_audio_chunks = 0
        self._start_time = time.time()
        
        logger.info(
            f"创建数据缓冲区: session_id={session_id}, "
            f"window_size={window_size}s"
        )
    
    @property
    def session_id(self) -> str:
        """返回会话ID"""
        return self._session_id
    
    @property
    def window_size(self) -> float:
        """返回窗口大小"""
        return self._window_size
    
    @property
    def video_frame_count(self) -> int:
        """当前缓冲区中的视频帧数"""
        with self._video_lock:
            return len(self._video_buffer)
    
    @property
    def audio_chunk_count(self) -> int:
        """当前缓冲区中的音频块数"""
        with self._audio_lock:
            return len(self._audio_buffer)
    
    def add_video_frame(
        self,
        frame: np.ndarray,
        timestamp: Optional[float] = None
    ) -> None:
        """
        添加视频帧到缓冲区
        
        Args:
            frame: 视频帧（numpy数组）
            timestamp: 时间戳（默认使用当前时间）
        """
        if timestamp is None:
            timestamp = time.time()
        else:
            timestamp = normalize_media_timestamp(timestamp)
        
        with self._video_lock:
            self._video_buffer.append((timestamp, frame))
            self._total_video_frames += 1
        
        # 清理过期数据
        self._cleanup_expired_video()
    
    def add_audio_chunk(
        self,
        chunk: bytes,
        timestamp: Optional[float] = None
    ) -> None:
        """
        添加音频块到缓冲区
        
        Args:
            chunk: 音频块（bytes）
            timestamp: 时间戳（默认使用当前时间）
        """
        if timestamp is None:
            timestamp = time.time()
        else:
            timestamp = normalize_media_timestamp(timestamp)
        
        with self._audio_lock:
            self._audio_buffer.append((timestamp, chunk))
            self._total_audio_chunks += 1
        
        # 清理过期数据
        self._cleanup_expired_audio()
    
    def _cleanup_expired_video(self) -> None:
        """清理过期的视频帧"""
        current_time = time.time()
        cutoff_time = current_time - self._window_size
        
        with self._video_lock:
            while self._video_buffer and self._video_buffer[0][0] < cutoff_time:
                self._video_buffer.popleft()
    
    def _cleanup_expired_audio(self) -> None:
        """清理过期的音频块"""
        current_time = time.time()
        cutoff_time = current_time - self._window_size
        
        with self._audio_lock:
            while self._audio_buffer and self._audio_buffer[0][0] < cutoff_time:
                self._audio_buffer.popleft()
    
    def get_window_data(self) -> WindowData:
        """
        获取当前窗口数据
        
        Returns:
            WindowData对象，包含窗口内的所有视频帧和音频块
        """
        current_time = time.time()
        cutoff_time = current_time - self._window_size
        
        # 获取视频帧
        with self._video_lock:
            video_frames = [
                (ts, frame) for ts, frame in self._video_buffer
                if ts >= cutoff_time
            ]
        
        # 获取音频块
        with self._audio_lock:
            audio_chunks = [
                (ts, chunk) for ts, chunk in self._audio_buffer
                if ts >= cutoff_time
            ]
        
        # 计算窗口时间范围
        window_start = cutoff_time
        window_end = current_time
        
        return WindowData(
            session_id=self._session_id,
            window_start=window_start,
            window_end=window_end,
            window_size=self._window_size,
            video_frames=video_frames,
            audio_chunks=audio_chunks
        )
    
    def get_video_frames(self) -> List[Tuple[float, np.ndarray]]:
        """
        获取窗口内的视频帧
        
        Returns:
            视频帧列表 [(timestamp, frame), ...]
        """
        current_time = time.time()
        cutoff_time = current_time - self._window_size
        
        with self._video_lock:
            return [
                (ts, frame) for ts, frame in self._video_buffer
                if ts >= cutoff_time
            ]
    
    def get_audio_chunks(self) -> List[Tuple[float, bytes]]:
        """
        获取窗口内的音频块
        
        Returns:
            音频块列表 [(timestamp, chunk), ...]
        """
        current_time = time.time()
        cutoff_time = current_time - self._window_size
        
        with self._audio_lock:
            return [
                (ts, chunk) for ts, chunk in self._audio_buffer
                if ts >= cutoff_time
            ]
    
    def get_accumulated_audio(self) -> bytes:
        """
        获取窗口内累积的音频数据
        
        Returns:
            合并的音频数据
        """
        chunks = self.get_audio_chunks()
        if not chunks:
            return b''
        
        # 按时间戳排序
        chunks.sort(key=lambda x: x[0])
        
        # 合并音频块
        return b''.join(chunk for _, chunk in chunks)
    
    def clear(self) -> None:
        """清空缓冲区"""
        with self._video_lock:
            self._video_buffer.clear()
        
        with self._audio_lock:
            self._audio_buffer.clear()
        
        logger.info(f"缓冲区已清空: session_id={self._session_id}")
    
    def get_statistics(self) -> dict:
        """
        获取缓冲区统计信息
        
        Returns:
            统计信息字典
        """
        return {
            'session_id': self._session_id,
            'window_size': self._window_size,
            'current_video_frames': self.video_frame_count,
            'current_audio_chunks': self.audio_chunk_count,
            'total_video_frames': self._total_video_frames,
            'total_audio_chunks': self._total_audio_chunks,
            'buffer_duration': time.time() - self._start_time
        }


class MultiSessionBuffer:
    """
    多会话数据缓冲区管理器
    
    管理多个会话的数据缓冲区
    """
    
    def __init__(self, default_window_size: float = 10.0):
        """
        初始化多会话缓冲区管理器
        
        Args:
            default_window_size: 默认窗口大小（秒）
        """
        self._default_window_size = default_window_size
        self._buffers: dict = {}
        self._lock = threading.Lock()
        
        logger.info(
            f"创建多会话缓冲区管理器: default_window_size={default_window_size}s"
        )
    
    def get_buffer(
        self,
        session_id: str,
        window_size: Optional[float] = None
    ) -> DataBuffer:
        """
        获取或创建会话的数据缓冲区
        
        Args:
            session_id: 会话ID
            window_size: 窗口大小（可选）
        
        Returns:
            DataBuffer实例
        """
        with self._lock:
            if session_id not in self._buffers:
                self._buffers[session_id] = DataBuffer(
                    session_id=session_id,
                    window_size=window_size or self._default_window_size
                )
            return self._buffers[session_id]
    
    def remove_buffer(self, session_id: str) -> bool:
        """
        移除会话的数据缓冲区
        
        Args:
            session_id: 会话ID
        
        Returns:
            True如果成功移除
        """
        with self._lock:
            if session_id in self._buffers:
                self._buffers[session_id].clear()
                del self._buffers[session_id]
                logger.info(f"移除缓冲区: session_id={session_id}")
                return True
            return False
    
    def has_buffer(self, session_id: str) -> bool:
        """检查会话是否有缓冲区"""
        with self._lock:
            return session_id in self._buffers
    
    def list_sessions(self) -> List[str]:
        """列出所有有缓冲区的会话"""
        with self._lock:
            return list(self._buffers.keys())
    
    def clear_all(self) -> None:
        """清空所有缓冲区"""
        with self._lock:
            for buffer in self._buffers.values():
                buffer.clear()
            self._buffers.clear()
        logger.info("所有缓冲区已清空")


# 全局多会话缓冲区管理器实例
_buffer_manager: Optional[MultiSessionBuffer] = None
_buffer_manager_lock = threading.Lock()


def get_buffer_manager(default_window_size: float = 10.0) -> MultiSessionBuffer:
    """
    获取全局缓冲区管理器实例（单例模式）
    
    Args:
        default_window_size: 默认窗口大小
    
    Returns:
        MultiSessionBuffer实例
    """
    global _buffer_manager
    if _buffer_manager is None:
        with _buffer_manager_lock:
            if _buffer_manager is None:
                _buffer_manager = MultiSessionBuffer(default_window_size)
    return _buffer_manager

