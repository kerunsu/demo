"""
核心数据模型
定义分析框架中使用的所有数据结构
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime
import time


class AnalysisMode(Enum):
    """
    分析模式枚举
    
    - REALTIME: 实时分析+控制（Type A）
        用于姿态模仿、语音命名等需要实时比对的场景
    - WINDOW: 滑动窗口分析（Type B）
        用于注意力检测等需要分析过去一段时间数据的场景
    - SESSION: 会话汇总分析（Type C）
        用于课程结束后的统计汇总
    """
    REALTIME = "realtime"
    WINDOW = "window"
    SESSION = "session"


class AnalyzerStatus(Enum):
    """分析器状态"""
    UNINITIALIZED = "uninitialized"  # 未初始化
    READY = "ready"                   # 就绪
    RUNNING = "running"               # 运行中
    ERROR = "error"                   # 错误
    STOPPED = "stopped"               # 已停止


class AnalyzerType(Enum):
    """分析器类型"""
    # 视觉分析器
    POSE = "pose"                     # 姿态分析
    FACE = "face"                     # 表情/头部分析
    EYE = "eye"                       # 眼动分析
    ATTENTION = "attention"           # 注意力分析
    
    # 音频分析器
    SPEECH = "speech"                 # 语音分析
    ASR = "asr"                       # 语音识别
    AUDIO_EMOTION = "audio_emotion"   # 语音情感
    
    # 比对器
    POSE_MATCHER = "pose_matcher"     # 姿态比对
    SPEECH_MATCHER = "speech_matcher" # 语音比对


@dataclass
class AnalysisContext:
    """
    分析上下文
    包含分析过程中需要的上下文信息
    """
    session_id: str                           # 会话ID
    course_id: Optional[int] = None           # 课程ID
    course_item_id: Optional[int] = None      # 课程项ID
    student_id: Optional[int] = None          # 学生ID
    course_type: Optional[str] = None         # 课程类型
    start_time: float = field(default_factory=time.time)  # 开始时间
    frame_index: int = 0                      # 当前帧索引
    audio_chunk_index: int = 0                # 当前音频块索引
    metadata: Dict[str, Any] = field(default_factory=dict)  # 额外元数据
    aux_data: Dict[str, Any] = field(default_factory=dict)  # 辅助数据（如目标文本等）
    
    def update_frame_index(self, index: int) -> None:
        """更新帧索引"""
        self.frame_index = index
    
    def update_audio_chunk_index(self, index: int) -> None:
        """更新音频块索引"""
        self.audio_chunk_index = index
    
    def get_elapsed_time(self) -> float:
        """获取已过时间（秒）"""
        return time.time() - self.start_time


@dataclass
class AnalysisResult:
    """
    分析结果
    所有分析器返回的统一结果格式
    """
    session_id: str                           # 会话ID
    analyzer_type: str                        # 分析器类型
    mode: AnalysisMode                        # 分析模式
    timestamp: float                          # 时间戳
    data: Dict[str, Any]                      # 分析数据
    confidence: float = 1.0                   # 置信度 (0-1)
    frame_index: Optional[int] = None         # 帧索引（视觉分析）
    audio_chunk_index: Optional[int] = None   # 音频块索引（音频分析）
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'session_id': self.session_id,
            'analyzer_type': self.analyzer_type,
            'mode': self.mode.value,
            'timestamp': self.timestamp,
            'data': self.data,
            'confidence': self.confidence,
            'frame_index': self.frame_index,
            'audio_chunk_index': self.audio_chunk_index,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AnalysisResult':
        """从字典创建"""
        return cls(
            session_id=data['session_id'],
            analyzer_type=data['analyzer_type'],
            mode=AnalysisMode(data['mode']),
            timestamp=data['timestamp'],
            data=data['data'],
            confidence=data.get('confidence', 1.0),
            frame_index=data.get('frame_index'),
            audio_chunk_index=data.get('audio_chunk_index'),
            metadata=data.get('metadata', {})
        )


@dataclass
class MatchResult:
    """
    匹配结果（Type A：实时分析+控制）
    用于姿态比对、语音比对等场景
    """
    session_id: str                           # 会话ID
    matcher_type: str                         # 比对器类型
    timestamp: float                          # 时间戳
    score: float                              # 匹配度 (0-1)
    passed: bool                              # 是否达到阈值
    threshold: float                          # 使用的阈值
    details: Dict[str, Any] = field(default_factory=dict)  # 详细信息
    frame_index: Optional[int] = None         # 帧索引
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'session_id': self.session_id,
            'matcher_type': self.matcher_type,
            'timestamp': self.timestamp,
            'score': self.score,
            'passed': self.passed,
            'threshold': self.threshold,
            'details': self.details,
            'frame_index': self.frame_index,
            'metadata': self.metadata
        }


@dataclass
class WindowData:
    """
    窗口数据（Type B：滑动窗口分析）
    包含过去N秒的视频帧和音频块
    """
    session_id: str                           # 会话ID
    window_start: float                       # 窗口开始时间
    window_end: float                         # 窗口结束时间
    window_size: float                        # 窗口大小（秒）
    video_frames: List[tuple] = field(default_factory=list)   # [(timestamp, frame), ...]
    audio_chunks: List[tuple] = field(default_factory=list)   # [(timestamp, chunk), ...]
    
    @property
    def frame_count(self) -> int:
        """视频帧数量"""
        return len(self.video_frames)
    
    @property
    def audio_chunk_count(self) -> int:
        """音频块数量"""
        return len(self.audio_chunks)
    
    @property
    def duration(self) -> float:
        """窗口时长"""
        return self.window_end - self.window_start


@dataclass
class SessionSummary:
    """
    会话汇总（Type C：会话汇总分析）
    课程结束后的统计数据
    """
    session_id: str                           # 会话ID
    student_id: Optional[int] = None          # 学生ID
    course_id: Optional[int] = None           # 课程ID
    course_item_id: Optional[int] = None      # 课程项ID
    
    # 时间信息
    start_time: Optional[float] = None        # 开始时间
    end_time: Optional[float] = None          # 结束时间
    duration: float = 0.0                     # 总时长（秒）
    
    # 视频统计
    total_frames: int = 0                     # 总帧数
    analyzed_frames: int = 0                  # 分析的帧数
    
    # 音频统计
    total_audio_chunks: int = 0               # 总音频块数
    total_audio_duration: float = 0.0         # 总音频时长
    total_word_count: int = 0                 # 总字数
    average_speech_rate: float = 0.0          # 平均语速（字/分钟）
    
    # 注意力统计
    attention_scores: List[float] = field(default_factory=list)  # 注意力评分列表
    average_attention: float = 0.0            # 平均注意力
    min_attention: float = 0.0                # 最低注意力
    max_attention: float = 0.0                # 最高注意力
    
    # 匹配统计（Type A）
    total_matches: int = 0                    # 匹配尝试次数
    successful_matches: int = 0               # 成功匹配次数
    match_success_rate: float = 0.0           # 匹配成功率
    
    # 关键事件
    key_events: List[Dict[str, Any]] = field(default_factory=list)
    
    # 触发动作统计
    triggered_actions: List[Dict[str, Any]] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'session_id': self.session_id,
            'student_id': self.student_id,
            'course_id': self.course_id,
            'course_item_id': self.course_item_id,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'duration': self.duration,
            'total_frames': self.total_frames,
            'analyzed_frames': self.analyzed_frames,
            'total_audio_chunks': self.total_audio_chunks,
            'total_audio_duration': self.total_audio_duration,
            'total_word_count': self.total_word_count,
            'average_speech_rate': self.average_speech_rate,
            'average_attention': self.average_attention,
            'min_attention': self.min_attention,
            'max_attention': self.max_attention,
            'total_matches': self.total_matches,
            'successful_matches': self.successful_matches,
            'match_success_rate': self.match_success_rate,
            'key_events': self.key_events,
            'triggered_actions': self.triggered_actions
        }


@dataclass
class AnalyzerConfig:
    """分析器配置"""
    analyzer_type: AnalyzerType               # 分析器类型
    enabled: bool = True                      # 是否启用
    mode: AnalysisMode = AnalysisMode.REALTIME  # 分析模式
    interval: float = 1.0                     # 分析间隔（帧数或秒数）
    threshold: Optional[float] = None         # 阈值（用于触发）
    params: Dict[str, Any] = field(default_factory=dict)  # 额外参数


@dataclass
class Action:
    """
    动作定义
    触发系统执行的动作
    """
    action_type: str                          # 动作类型
    target: str                               # 目标: "child", "therapist", "both"
    payload: Dict[str, Any] = field(default_factory=dict)  # 动作参数
    
    # 预定义动作类型
    PLAY_AUDIO = "play_audio"                 # 播放音频
    PLAY_VIDEO = "play_video"                 # 播放视频
    EMIT_EVENT = "emit_event"                 # 发送WebSocket事件
    LOG = "log"                               # 记录日志
    CUSTOM = "custom"                         # 自定义动作
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'action_type': self.action_type,
            'target': self.target,
            'payload': self.payload
        }


@dataclass
class Trigger:
    """
    触发器定义
    当条件满足时执行动作
    """
    name: str                                 # 触发器名称
    trigger_type: str                         # 触发器类型
    condition: Dict[str, Any]                 # 触发条件配置
    action: Action                            # 触发动作
    cooldown: float = 3.0                     # 冷却时间（秒）
    enabled: bool = True                      # 是否启用
    last_triggered: Optional[float] = None    # 上次触发时间
    
    # 预定义触发器类型
    THRESHOLD_ABOVE = "threshold_above"       # 高于阈值触发
    THRESHOLD_BELOW = "threshold_below"       # 低于阈值触发
    MATCH_SUCCESS = "match_success"           # 匹配成功触发
    DURATION = "duration"                     # 持续时间触发
    
    def can_trigger(self) -> bool:
        """检查是否可以触发（考虑冷却时间）"""
        if not self.enabled:
            return False
        if self.last_triggered is None:
            return True
        return (time.time() - self.last_triggered) >= self.cooldown
    
    def mark_triggered(self) -> None:
        """标记已触发"""
        self.last_triggered = time.time()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'name': self.name,
            'trigger_type': self.trigger_type,
            'condition': self.condition,
            'action': self.action.to_dict(),
            'cooldown': self.cooldown,
            'enabled': self.enabled
        }


# 类型别名
FrameData = tuple  # (timestamp: float, frame: np.ndarray)
AudioChunkData = tuple  # (timestamp: float, chunk: bytes)

