"""
分析结果存储
持久化存储分析结果，支持查询和导出
"""
import threading
import json
import os
import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
from datetime import datetime

from app.config import Config
from app.utils.logger import setup_logger

logger = setup_logger('result_storage')


@dataclass
class StoredResult:
    """存储的结果记录"""
    id: str                         # 唯一ID
    session_id: str                 # 会话ID
    result_type: str                # 结果类型
    analyzer_type: str              # 分析器类型
    timestamp: float                # 时间戳
    data: Dict[str, Any]            # 结果数据
    score: Optional[float] = None   # 评分（如果有）
    passed: Optional[bool] = None   # 是否通过（如果有）
    metadata: Optional[Dict] = None # 元数据
    
    def to_dict(self) -> Dict:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'StoredResult':
        """从字典创建"""
        return cls(**data)


class ResultStorage:
    """
    分析结果存储
    
    支持：
    - 内存存储（快速访问）
    - 文件存储（持久化）
    - 按会话/类型查询
    - 会话总结导出
    """
    
    def __init__(self, storage_dir: Optional[str] = None):
        """
        初始化结果存储
        
        Args:
            storage_dir: 存储目录
        """
        self._storage_dir = storage_dir or os.path.join(
            str(Config.RECORDINGS_DIR), 'analysis_results'
        )
        
        # 确保目录存在
        os.makedirs(self._storage_dir, exist_ok=True)
        
        # 内存存储：{session_id: [StoredResult, ...]}
        self._memory_store: Dict[str, List[StoredResult]] = {}
        self._lock = threading.RLock()
        
        # 计数器
        self._result_counter = 0
        
        logger.info(f"结果存储已初始化: {self._storage_dir}")
    
    def _generate_id(self) -> str:
        """生成唯一ID"""
        self._result_counter += 1
        return f"r_{int(time.time() * 1000)}_{self._result_counter}"
    
    def store(
        self,
        session_id: str,
        result_type: str,
        analyzer_type: str,
        data: Dict[str, Any],
        score: Optional[float] = None,
        passed: Optional[bool] = None,
        metadata: Optional[Dict] = None
    ) -> Optional[str]:
        """
        存储结果
        
        Args:
            session_id: 会话ID
            result_type: 结果类型
            analyzer_type: 分析器类型
            data: 结果数据
            score: 评分
            passed: 是否通过
            metadata: 元数据
        
        Returns:
            结果ID，失败返回None
        """
        try:
            with self._lock:
                result_id = self._generate_id()
                
                result = StoredResult(
                    id=result_id,
                    session_id=session_id,
                    result_type=result_type,
                    analyzer_type=analyzer_type,
                    timestamp=time.time(),
                    data=data,
                    score=score,
                    passed=passed,
                    metadata=metadata
                )
                
                # 存入内存
                if session_id not in self._memory_store:
                    self._memory_store[session_id] = []
                self._memory_store[session_id].append(result)
                
                return result_id
                
        except Exception as e:
            logger.error(f"存储结果失败: {e}")
            return None
    
    def store_analysis_result(
        self,
        session_id: str,
        analysis_result: Any
    ) -> Optional[str]:
        """存储分析结果"""
        return self.store(
            session_id=session_id,
            result_type='analysis',
            analyzer_type=getattr(analysis_result, 'analyzer_type', 'unknown'),
            data=getattr(analysis_result, 'data', {}),
            score=getattr(analysis_result, 'confidence', None),
            metadata={'mode': str(getattr(analysis_result, 'mode', ''))}
        )
    
    def store_match_result(
        self,
        session_id: str,
        match_result: Any
    ) -> Optional[str]:
        """存储匹配结果"""
        return self.store(
            session_id=session_id,
            result_type='match',
            analyzer_type=getattr(match_result, 'matcher_type', 'unknown'),
            data=getattr(match_result, 'details', {}),
            score=getattr(match_result, 'score', None),
            passed=getattr(match_result, 'passed', None)
        )
    
    def get_by_session(
        self,
        session_id: str,
        result_type: Optional[str] = None
    ) -> List[StoredResult]:
        """
        按会话获取结果
        
        Args:
            session_id: 会话ID
            result_type: 结果类型过滤（可选）
        
        Returns:
            结果列表
        """
        with self._lock:
            results = self._memory_store.get(session_id, [])
            
            if result_type:
                results = [r for r in results if r.result_type == result_type]
            
            return results
    
    def get_latest(
        self,
        session_id: str,
        result_type: Optional[str] = None,
        limit: int = 10
    ) -> List[StoredResult]:
        """
        获取最新结果
        
        Args:
            session_id: 会话ID
            result_type: 结果类型过滤
            limit: 返回数量限制
        
        Returns:
            最新的结果列表
        """
        results = self.get_by_session(session_id, result_type)
        return sorted(results, key=lambda r: r.timestamp, reverse=True)[:limit]
    
    def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """
        获取会话总结
        
        Args:
            session_id: 会话ID
        
        Returns:
            会话总结数据
        """
        with self._lock:
            results = self._memory_store.get(session_id, [])
            
            if not results:
                return {'session_id': session_id, 'total_results': 0}
            
            # 统计各类型结果
            type_counts = {}
            scores = []
            pass_count = 0
            total_match = 0
            
            for r in results:
                type_counts[r.result_type] = type_counts.get(r.result_type, 0) + 1
                
                if r.score is not None:
                    scores.append(r.score)
                
                if r.result_type == 'match':
                    total_match += 1
                    if r.passed:
                        pass_count += 1
            
            # 计算时间范围
            timestamps = [r.timestamp for r in results]
            duration = max(timestamps) - min(timestamps) if len(timestamps) > 1 else 0
            
            return {
                'session_id': session_id,
                'total_results': len(results),
                'type_counts': type_counts,
                'duration': round(duration, 2),
                'average_score': round(sum(scores) / len(scores), 3) if scores else None,
                'match_success_rate': round(pass_count / total_match, 3) if total_match > 0 else None,
                'first_timestamp': min(timestamps),
                'last_timestamp': max(timestamps)
            }
    
    def export_session(
        self,
        session_id: str,
        format: str = 'json'
    ) -> Optional[str]:
        """
        导出会话结果到文件
        
        Args:
            session_id: 会话ID
            format: 导出格式（json）
        
        Returns:
            导出文件路径
        """
        try:
            results = self.get_by_session(session_id)
            if not results:
                logger.warning(f"会话无结果可导出: {session_id}")
                return None
            
            # 创建会话目录
            session_dir = os.path.join(self._storage_dir, session_id)
            os.makedirs(session_dir, exist_ok=True)
            
            # 导出数据
            export_data = {
                'session_id': session_id,
                'export_time': datetime.now().isoformat(),
                'summary': self.get_session_summary(session_id),
                'results': [r.to_dict() for r in results]
            }
            
            # 写入文件
            filename = f"analysis_results_{int(time.time())}.json"
            filepath = os.path.join(session_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"导出会话结果: {filepath}")
            return filepath
            
        except Exception as e:
            logger.error(f"导出会话结果失败: {e}")
            return None
    
    def clear_session(self, session_id: str) -> None:
        """清除会话内存数据"""
        with self._lock:
            if session_id in self._memory_store:
                del self._memory_store[session_id]
                logger.debug(f"清除会话存储: {session_id}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取存储统计"""
        with self._lock:
            total_results = sum(len(r) for r in self._memory_store.values())
            
            return {
                'total_sessions': len(self._memory_store),
                'total_results': total_results,
                'storage_dir': self._storage_dir,
                'sessions': list(self._memory_store.keys())
            }


# 全局存储实例
_result_storage: Optional[ResultStorage] = None
_storage_lock = threading.Lock()


def get_result_storage() -> ResultStorage:
    """获取全局结果存储实例（单例模式）"""
    global _result_storage
    if _result_storage is None:
        with _storage_lock:
            if _result_storage is None:
                _result_storage = ResultStorage()
    return _result_storage

