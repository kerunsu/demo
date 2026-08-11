"""
分析结果队列
管理分析结果的缓冲队列，用于异步处理和反馈
"""
import threading
from collections import deque
from typing import Optional, List, Any, Dict
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import time

from app.utils.logger import setup_logger

logger = setup_logger('result_queue')


class ResultType(Enum):
    """结果类型"""
    ANALYSIS = 'analysis'       # 分析结果
    MATCH = 'match'             # 匹配结果
    ATTENTION = 'attention'     # 注意力结果
    SESSION_SUMMARY = 'summary' # 会话总结
    TRIGGER_ACTION = 'trigger'  # 触发动作


@dataclass
class QueuedResult:
    """队列中的结果项"""
    result_type: ResultType
    session_id: str
    data: Any
    timestamp: float
    metadata: Optional[Dict] = None


class ResultQueue:
    """
    分析结果队列
    
    支持多会话的结果缓冲，用于：
    - 异步处理分析结果
    - 批量发送反馈
    - 结果持久化
    """
    
    def __init__(self, max_size: int = 1000):
        """
        初始化结果队列
        
        Args:
            max_size: 每个会话队列的最大大小
        """
        self.max_size = max_size
        # 按会话存储队列
        self._queues: Dict[str, deque] = {}
        # 全局队列（所有会话的结果）
        self._global_queue: deque = deque(maxlen=max_size * 10)
        self._lock = threading.RLock()
        
        logger.info(f"结果队列已初始化: max_size={max_size}")
    
    def put(
        self,
        result_type: ResultType,
        session_id: str,
        data: Any,
        timestamp: Optional[float] = None,
        metadata: Optional[Dict] = None
    ) -> bool:
        """
        将结果放入队列
        
        Args:
            result_type: 结果类型
            session_id: 会话ID
            data: 结果数据
            timestamp: 时间戳
            metadata: 元数据
        
        Returns:
            是否成功
        """
        if not session_id:
            logger.warning("session_id为空，无法放入队列")
            return False
        
        ts = timestamp or time.time()
        
        try:
            with self._lock:
                # 创建结果项
                result = QueuedResult(
                    result_type=result_type,
                    session_id=session_id,
                    data=data,
                    timestamp=ts,
                    metadata=metadata
                )
                
                # 放入会话队列
                if session_id not in self._queues:
                    self._queues[session_id] = deque(maxlen=self.max_size)
                
                self._queues[session_id].append(result)
                
                # 放入全局队列
                self._global_queue.append(result)
                
                return True
                
        except Exception as e:
            logger.error(f"放入结果队列失败: {e}")
            return False
    
    def put_analysis_result(
        self,
        session_id: str,
        analysis_result: Any
    ) -> bool:
        """放入分析结果"""
        return self.put(
            ResultType.ANALYSIS,
            session_id,
            analysis_result
        )
    
    def put_match_result(
        self,
        session_id: str,
        match_result: Any
    ) -> bool:
        """放入匹配结果"""
        return self.put(
            ResultType.MATCH,
            session_id,
            match_result
        )
    
    def put_attention_result(
        self,
        session_id: str,
        attention_data: Dict
    ) -> bool:
        """放入注意力结果"""
        return self.put(
            ResultType.ATTENTION,
            session_id,
            attention_data
        )
    
    def put_trigger_action(
        self,
        session_id: str,
        action_type: str,
        action_data: Dict
    ) -> bool:
        """放入触发动作"""
        return self.put(
            ResultType.TRIGGER_ACTION,
            session_id,
            {'action_type': action_type, 'data': action_data}
        )
    
    def get(self, session_id: str) -> Optional[QueuedResult]:
        """
        从会话队列获取一个结果
        
        Args:
            session_id: 会话ID
        
        Returns:
            结果项，队列为空时返回None
        """
        try:
            with self._lock:
                if session_id not in self._queues:
                    return None
                
                queue = self._queues[session_id]
                if not queue:
                    return None
                
                return queue.popleft()
                
        except Exception as e:
            logger.error(f"从结果队列获取失败: {e}")
            return None
    
    def get_all(self, session_id: str) -> List[QueuedResult]:
        """
        获取会话的所有结果
        
        Args:
            session_id: 会话ID
        
        Returns:
            结果列表
        """
        try:
            with self._lock:
                if session_id not in self._queues:
                    return []
                
                results = list(self._queues[session_id])
                self._queues[session_id].clear()
                return results
                
        except Exception as e:
            logger.error(f"获取所有结果失败: {e}")
            return []
    
    def get_by_type(
        self,
        session_id: str,
        result_type: ResultType
    ) -> List[QueuedResult]:
        """
        按类型获取结果
        
        Args:
            session_id: 会话ID
            result_type: 结果类型
        
        Returns:
            指定类型的结果列表
        """
        try:
            with self._lock:
                if session_id not in self._queues:
                    return []
                
                results = [
                    r for r in self._queues[session_id]
                    if r.result_type == result_type
                ]
                
                # 从队列中移除已获取的结果
                self._queues[session_id] = deque(
                    [r for r in self._queues[session_id] if r.result_type != result_type],
                    maxlen=self.max_size
                )
                
                return results
                
        except Exception as e:
            logger.error(f"按类型获取结果失败: {e}")
            return []
    
    def peek(self, session_id: str) -> Optional[QueuedResult]:
        """查看队列头部结果（不移除）"""
        try:
            with self._lock:
                if session_id not in self._queues or not self._queues[session_id]:
                    return None
                return self._queues[session_id][0]
        except Exception as e:
            logger.error(f"查看队列失败: {e}")
            return None
    
    def size(self, session_id: str) -> int:
        """获取会话队列大小"""
        with self._lock:
            if session_id not in self._queues:
                return 0
            return len(self._queues[session_id])
    
    def clear(self, session_id: str) -> None:
        """清空会话队列"""
        with self._lock:
            if session_id in self._queues:
                self._queues[session_id].clear()
                logger.debug(f"清空结果队列: {session_id}")
    
    def clear_all(self) -> None:
        """清空所有队列"""
        with self._lock:
            self._queues.clear()
            self._global_queue.clear()
            logger.info("清空所有结果队列")
    
    def list_sessions(self) -> List[str]:
        """获取有结果的会话列表"""
        with self._lock:
            return [
                session_id for session_id, queue in self._queues.items()
                if queue
            ]
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取队列统计"""
        with self._lock:
            return {
                'total_sessions': len(self._queues),
                'active_sessions': len([q for q in self._queues.values() if q]),
                'global_queue_size': len(self._global_queue),
                'session_sizes': {
                    sid: len(q) for sid, q in self._queues.items()
                }
            }


# 全局结果队列实例
_result_queue: Optional[ResultQueue] = None
_queue_lock = threading.Lock()


def get_result_queue() -> ResultQueue:
    """获取全局结果队列实例（单例模式）"""
    global _result_queue
    if _result_queue is None:
        with _queue_lock:
            if _result_queue is None:
                _result_queue = ResultQueue()
    return _result_queue

