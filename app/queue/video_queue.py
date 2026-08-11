"""
视频帧队列
管理视频帧的缓冲队列，支持多会话
"""
import threading
from collections import deque
from typing import Optional, Tuple, Any
from datetime import datetime
from app.config import Config
from app.utils.logger import setup_logger

logger = setup_logger('video_queue')


class VideoQueue:
    """
    视频帧队列
    
    每个会话有独立的队列，队列满时丢弃最旧的帧
    线程安全
    """
    
    def __init__(self, max_size: int = None):
        """
        初始化视频队列
        
        Args:
            max_size: 每个会话队列的最大大小（默认使用Config.VIDEO_QUEUE_SIZE）
        """
        self.max_size = max_size or Config.VIDEO_QUEUE_SIZE
        # 存储每个会话的队列：{session_id: deque}
        self._queues: dict[str, deque] = {}
        # 锁，保证线程安全
        self._lock = threading.RLock()
        
        logger.debug(f"初始化视频队列: max_size={self.max_size}")
    
    def put(
        self,
        session_id: str,
        frame: Any,
        timestamp: Optional[float] = None
    ) -> bool:
        """
        将视频帧放入队列
        
        Args:
            session_id: 会话ID
            frame: 视频帧数据（base64字符串或numpy数组）
            timestamp: 时间戳（可选，默认使用当前时间）
        
        Returns:
            True如果成功放入，False如果失败
        """
        if not session_id:
            logger.warning("session_id为空，无法放入队列")
            return False
        
        if timestamp is None:
            timestamp = datetime.utcnow().timestamp()
        
        try:
            with self._lock:
                # 获取或创建会话队列
                if session_id not in self._queues:
                    self._queues[session_id] = deque(maxlen=self.max_size)
                    logger.debug(f"为会话创建视频队列: session_id={session_id}")
                
                queue = self._queues[session_id]
                
                # 如果队列已满，最旧的帧会被自动丢弃（deque的maxlen特性）
                queue.append((frame, timestamp, session_id))
                
                # 如果队列满了，记录警告（但继续工作）
                if len(queue) >= self.max_size:
                    logger.debug(
                        f"视频队列已满，将丢弃最旧的帧: "
                        f"session_id={session_id}, size={len(queue)}"
                    )
                
                return True
                
        except Exception as e:
            logger.error(f"放入视频帧到队列失败: {e}", exc_info=True)
            return False
    
    def peek_latest(self, session_id: str) -> Optional[Tuple[Any, float, str]]:
        """
        查看队列中最新一帧（不取出）。

        Returns:
            (frame, timestamp, session_id) 或 None
        """
        if not session_id:
            return None
        try:
            with self._lock:
                queue = self._queues.get(session_id)
                if not queue or len(queue) == 0:
                    return None
                return queue[-1]
        except Exception as e:
            logger.error(f"peek 视频队列失败: {e}", exc_info=True)
            return None

    def get(self, session_id: str) -> Optional[Tuple[Any, float, str]]:
        """
        从队列中获取一个视频帧
        
        Args:
            session_id: 会话ID
        
        Returns:
            (frame, timestamp, session_id) 元组，如果队列为空则返回None
        """
        if not session_id:
            logger.warning("session_id为空，无法从队列获取")
            return None
        
        try:
            with self._lock:
                if session_id not in self._queues:
                    return None
                
                queue = self._queues[session_id]
                
                if len(queue) == 0:
                    return None
                
                # 从左侧（最旧）取出
                return queue.popleft()
                
        except Exception as e:
            logger.error(f"从视频队列获取帧失败: {e}", exc_info=True)
            return None
    
    def clear(self, session_id: str) -> bool:
        """
        清空指定会话的队列
        
        Args:
            session_id: 会话ID
        
        Returns:
            True如果成功，False如果失败
        """
        if not session_id:
            logger.warning("session_id为空，无法清空队列")
            return False
        
        try:
            with self._lock:
                if session_id in self._queues:
                    self._queues[session_id].clear()
                    logger.debug(f"清空视频队列: session_id={session_id}")
                    return True
                return False
                
        except Exception as e:
            logger.error(f"清空视频队列失败: {e}", exc_info=True)
            return False
    
    def remove(self, session_id: str) -> bool:
        """
        移除指定会话的队列（完全删除）
        
        Args:
            session_id: 会话ID
        
        Returns:
            True如果成功，False如果失败
        """
        if not session_id:
            return False
        
        try:
            with self._lock:
                if session_id in self._queues:
                    del self._queues[session_id]
                    logger.debug(f"移除视频队列: session_id={session_id}")
                    return True
                return False
                
        except Exception as e:
            logger.error(f"移除视频队列失败: {e}", exc_info=True)
            return False
    
    def size(self, session_id: Optional[str] = None) -> int:
        """
        获取队列大小
        
        Args:
            session_id: 会话ID，如果为None则返回所有队列的总大小
        
        Returns:
            队列大小
        """
        try:
            with self._lock:
                if session_id is None:
                    # 返回所有队列的总大小
                    return sum(len(q) for q in self._queues.values())
                else:
                    # 返回指定会话的队列大小
                    if session_id in self._queues:
                        return len(self._queues[session_id])
                    return 0
                    
        except Exception as e:
            logger.error(f"获取视频队列大小失败: {e}", exc_info=True)
            return 0
    
    def has_data(self, session_id: str) -> bool:
        """
        检查指定会话的队列是否有数据
        
        Args:
            session_id: 会话ID
        
        Returns:
            True如果有数据，False否则
        """
        return self.size(session_id) > 0
    
    def list_sessions(self) -> list[str]:
        """
        获取所有有队列的会话ID列表
        
        Returns:
            会话ID列表
        """
        try:
            with self._lock:
                return list(self._queues.keys())
        except Exception as e:
            logger.error(f"获取会话列表失败: {e}", exc_info=True)
            return []
    
    def get_statistics(self) -> dict:
        """
        获取队列统计信息
        
        Returns:
            统计信息字典
        """
        try:
            with self._lock:
                stats = {
                    'total_sessions': len(self._queues),
                    'total_frames': sum(len(q) for q in self._queues.values()),
                    'max_size': self.max_size,
                    'sessions': {}
                }
                
                for session_id, queue in self._queues.items():
                    stats['sessions'][session_id] = {
                        'size': len(queue),
                        'max_size': self.max_size
                    }
                
                return stats
        except Exception as e:
            logger.error(f"获取队列统计信息失败: {e}", exc_info=True)
            return {}

