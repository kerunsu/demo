"""
累积器
用于 Type C（会话汇总分析）场景中的数据累积和统计
"""
import threading
import time
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from app.core.models import (
    AnalysisResult,
    MatchResult,
    SessionSummary,
    AnalysisMode,
    Action
)
from app.utils.logger import setup_logger

logger = setup_logger('accumulator')


@dataclass
class AccumulatorConfig:
    """累积器配置"""
    # 注意力统计配置
    attention_score_history_limit: int = 1000  # 注意力分数历史记录上限
    
    # 事件记录配置
    max_key_events: int = 100                  # 最大关键事件数
    max_triggered_actions: int = 100           # 最大触发动作记录数


class Accumulator:
    """
    会话累积器
    
    用于累积整个会话期间的统计数据，包括：
    - 视频帧/音频块计数
    - 字数统计
    - 注意力评分
    - 匹配统计
    - 关键事件记录
    - 触发动作记录
    
    会话结束时生成 SessionSummary
    """
    
    def __init__(
        self,
        session_id: str,
        student_id: Optional[int] = None,
        course_id: Optional[int] = None,
        course_item_id: Optional[int] = None,
        config: Optional[AccumulatorConfig] = None
    ):
        """
        初始化累积器
        
        Args:
            session_id: 会话ID
            student_id: 学生ID
            course_id: 课程ID
            course_item_id: 课程项ID
            config: 累积器配置
        """
        self._session_id = session_id
        self._student_id = student_id
        self._course_id = course_id
        self._course_item_id = course_item_id
        self._config = config or AccumulatorConfig()
        
        # 时间信息
        self._start_time = time.time()
        self._end_time: Optional[float] = None
        
        # 视频统计
        self._total_frames = 0
        self._analyzed_frames = 0
        
        # 音频统计
        self._total_audio_chunks = 0
        self._total_audio_duration = 0.0
        self._total_word_count = 0
        self._speech_durations: List[float] = []  # 每段说话的时长
        
        # 注意力统计
        self._attention_scores: List[float] = []
        self._attention_timestamps: List[float] = []
        
        # 匹配统计
        self._total_matches = 0
        self._successful_matches = 0
        self._match_scores: List[float] = []
        
        # 关键事件
        self._key_events: List[Dict[str, Any]] = []
        
        # 触发动作记录
        self._triggered_actions: List[Dict[str, Any]] = []
        
        # 线程锁
        self._lock = threading.Lock()
        
        logger.info(
            f"创建累积器: session_id={session_id}, "
            f"student_id={student_id}, course_id={course_id}"
        )
    
    @property
    def session_id(self) -> str:
        """返回会话ID"""
        return self._session_id
    
    @property
    def duration(self) -> float:
        """返回会话时长（秒）"""
        end = self._end_time or time.time()
        return end - self._start_time
    
    def update_from_result(self, result: AnalysisResult) -> None:
        """
        从分析结果更新累积数据
        
        Args:
            result: 分析结果
        """
        with self._lock:
            # 根据分析器类型更新不同的统计
            analyzer_type = result.analyzer_type
            data = result.data
            
            # 更新帧计数
            if result.frame_index is not None:
                self._analyzed_frames += 1
            
            # 语音分析结果
            if analyzer_type == 'speech':
                if 'word_count' in data:
                    self._total_word_count += data['word_count']
                if 'speech_duration' in data:
                    self._speech_durations.append(data['speech_duration'])
            
            # 注意力分析结果
            if analyzer_type == 'attention':
                if 'score' in data:
                    score = data['score']
                    self._attention_scores.append(score)
                    self._attention_timestamps.append(result.timestamp)
                    
                    # 限制历史记录数量
                    if len(self._attention_scores) > self._config.attention_score_history_limit:
                        self._attention_scores.pop(0)
                        self._attention_timestamps.pop(0)
    
    def update_from_match(self, match_result: MatchResult) -> None:
        """
        从匹配结果更新累积数据
        
        Args:
            match_result: 匹配结果
        """
        with self._lock:
            self._total_matches += 1
            self._match_scores.append(match_result.score)
            
            if match_result.passed:
                self._successful_matches += 1
                
                # 记录成功匹配事件
                self._add_key_event(
                    event_type='match_success',
                    timestamp=match_result.timestamp,
                    data={
                        'matcher_type': match_result.matcher_type,
                        'score': match_result.score,
                        'threshold': match_result.threshold
                    }
                )
    
    def add_frame_count(self, count: int = 1) -> None:
        """增加视频帧计数"""
        with self._lock:
            self._total_frames += count
    
    def add_audio_chunk_count(self, count: int = 1, duration: float = 0.0) -> None:
        """
        增加音频块计数
        
        Args:
            count: 音频块数量
            duration: 音频时长（秒）
        """
        with self._lock:
            self._total_audio_chunks += count
            self._total_audio_duration += duration
    
    def add_word_count(self, count: int) -> None:
        """增加字数统计"""
        with self._lock:
            self._total_word_count += count
    
    def add_attention_score(self, score: float, timestamp: Optional[float] = None) -> None:
        """
        添加注意力评分
        
        Args:
            score: 注意力评分 (0-1)
            timestamp: 时间戳
        """
        with self._lock:
            self._attention_scores.append(score)
            self._attention_timestamps.append(timestamp or time.time())
            
            # 限制历史记录数量
            if len(self._attention_scores) > self._config.attention_score_history_limit:
                self._attention_scores.pop(0)
                self._attention_timestamps.pop(0)
    
    def _add_key_event(
        self,
        event_type: str,
        timestamp: float,
        data: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        添加关键事件（内部方法，不加锁）
        
        Args:
            event_type: 事件类型
            timestamp: 时间戳
            data: 事件数据
        """
        if len(self._key_events) < self._config.max_key_events:
            self._key_events.append({
                'event_type': event_type,
                'timestamp': timestamp,
                'elapsed_time': timestamp - self._start_time,
                'data': data or {}
            })
    
    def add_key_event(
        self,
        event_type: str,
        data: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None
    ) -> None:
        """
        添加关键事件
        
        Args:
            event_type: 事件类型
            data: 事件数据
            timestamp: 时间戳
        """
        with self._lock:
            self._add_key_event(
                event_type=event_type,
                timestamp=timestamp or time.time(),
                data=data
            )
    
    def add_triggered_action(
        self,
        action: Action,
        trigger_name: str,
        timestamp: Optional[float] = None
    ) -> None:
        """
        记录触发的动作
        
        Args:
            action: 触发的动作
            trigger_name: 触发器名称
            timestamp: 时间戳
        """
        with self._lock:
            if len(self._triggered_actions) < self._config.max_triggered_actions:
                ts = timestamp or time.time()
                self._triggered_actions.append({
                    'trigger_name': trigger_name,
                    'action': action.to_dict(),
                    'timestamp': ts,
                    'elapsed_time': ts - self._start_time
                })
    
    def get_summary(self) -> SessionSummary:
        """
        获取会话汇总
        
        Returns:
            SessionSummary对象
        """
        with self._lock:
            # 计算注意力统计
            avg_attention = 0.0
            min_attention = 0.0
            max_attention = 0.0
            
            if self._attention_scores:
                avg_attention = sum(self._attention_scores) / len(self._attention_scores)
                min_attention = min(self._attention_scores)
                max_attention = max(self._attention_scores)
            
            # 计算语速
            avg_speech_rate = 0.0
            total_speech_duration = sum(self._speech_durations) if self._speech_durations else 0
            if total_speech_duration > 0:
                avg_speech_rate = (self._total_word_count / total_speech_duration) * 60
            
            # 计算匹配成功率
            match_success_rate = 0.0
            if self._total_matches > 0:
                match_success_rate = self._successful_matches / self._total_matches
            
            return SessionSummary(
                session_id=self._session_id,
                student_id=self._student_id,
                course_id=self._course_id,
                course_item_id=self._course_item_id,
                start_time=self._start_time,
                end_time=self._end_time or time.time(),
                duration=self.duration,
                total_frames=self._total_frames,
                analyzed_frames=self._analyzed_frames,
                total_audio_chunks=self._total_audio_chunks,
                total_audio_duration=self._total_audio_duration,
                total_word_count=self._total_word_count,
                average_speech_rate=avg_speech_rate,
                attention_scores=self._attention_scores.copy(),
                average_attention=avg_attention,
                min_attention=min_attention,
                max_attention=max_attention,
                total_matches=self._total_matches,
                successful_matches=self._successful_matches,
                match_success_rate=match_success_rate,
                key_events=self._key_events.copy(),
                triggered_actions=self._triggered_actions.copy()
            )
    
    def finish(self) -> SessionSummary:
        """
        结束累积并返回汇总
        
        Returns:
            SessionSummary对象
        """
        with self._lock:
            self._end_time = time.time()
        
        summary = self.get_summary()
        
        logger.info(
            f"累积器结束: session_id={self._session_id}, "
            f"duration={summary.duration:.2f}s, "
            f"total_frames={summary.total_frames}, "
            f"total_word_count={summary.total_word_count}"
        )
        
        return summary
    
    def reset(self) -> None:
        """重置累积器"""
        with self._lock:
            self._start_time = time.time()
            self._end_time = None
            self._total_frames = 0
            self._analyzed_frames = 0
            self._total_audio_chunks = 0
            self._total_audio_duration = 0.0
            self._total_word_count = 0
            self._speech_durations.clear()
            self._attention_scores.clear()
            self._attention_timestamps.clear()
            self._total_matches = 0
            self._successful_matches = 0
            self._match_scores.clear()
            self._key_events.clear()
            self._triggered_actions.clear()
        
        logger.info(f"累积器已重置: session_id={self._session_id}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        获取当前统计信息
        
        Returns:
            统计信息字典
        """
        with self._lock:
            return {
                'session_id': self._session_id,
                'duration': self.duration,
                'total_frames': self._total_frames,
                'analyzed_frames': self._analyzed_frames,
                'total_audio_chunks': self._total_audio_chunks,
                'total_word_count': self._total_word_count,
                'attention_score_count': len(self._attention_scores),
                'total_matches': self._total_matches,
                'successful_matches': self._successful_matches,
                'key_event_count': len(self._key_events),
                'triggered_action_count': len(self._triggered_actions)
            }


class MultiSessionAccumulator:
    """
    多会话累积器管理器
    
    管理多个会话的累积器
    """
    
    def __init__(self):
        """初始化多会话累积器管理器"""
        self._accumulators: Dict[str, Accumulator] = {}
        self._lock = threading.Lock()
        
        logger.info("创建多会话累积器管理器")
    
    def get_accumulator(
        self,
        session_id: str,
        student_id: Optional[int] = None,
        course_id: Optional[int] = None,
        course_item_id: Optional[int] = None
    ) -> Accumulator:
        """
        获取或创建会话的累积器
        
        Args:
            session_id: 会话ID
            student_id: 学生ID
            course_id: 课程ID
            course_item_id: 课程项ID
        
        Returns:
            Accumulator实例
        """
        with self._lock:
            if session_id not in self._accumulators:
                self._accumulators[session_id] = Accumulator(
                    session_id=session_id,
                    student_id=student_id,
                    course_id=course_id,
                    course_item_id=course_item_id
                )
            return self._accumulators[session_id]
    
    def finish_session(self, session_id: str) -> Optional[SessionSummary]:
        """
        结束会话并返回汇总
        
        Args:
            session_id: 会话ID
        
        Returns:
            SessionSummary对象，如果会话不存在返回None
        """
        with self._lock:
            if session_id in self._accumulators:
                summary = self._accumulators[session_id].finish()
                return summary
            return None
    
    def remove_accumulator(self, session_id: str) -> bool:
        """
        移除会话的累积器
        
        Args:
            session_id: 会话ID
        
        Returns:
            True如果成功移除
        """
        with self._lock:
            if session_id in self._accumulators:
                del self._accumulators[session_id]
                logger.info(f"移除累积器: session_id={session_id}")
                return True
            return False
    
    def has_accumulator(self, session_id: str) -> bool:
        """检查会话是否有累积器"""
        with self._lock:
            return session_id in self._accumulators
    
    def list_sessions(self) -> List[str]:
        """列出所有有累积器的会话"""
        with self._lock:
            return list(self._accumulators.keys())
    
    def clear_all(self) -> None:
        """清空所有累积器"""
        with self._lock:
            self._accumulators.clear()
        logger.info("所有累积器已清空")


# 全局多会话累积器管理器实例
_accumulator_manager: Optional[MultiSessionAccumulator] = None
_accumulator_manager_lock = threading.Lock()


def get_accumulator_manager() -> MultiSessionAccumulator:
    """
    获取全局累积器管理器实例（单例模式）
    
    Returns:
        MultiSessionAccumulator实例
    """
    global _accumulator_manager
    if _accumulator_manager is None:
        with _accumulator_manager_lock:
            if _accumulator_manager is None:
                _accumulator_manager = MultiSessionAccumulator()
    return _accumulator_manager

