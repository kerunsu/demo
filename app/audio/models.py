"""
语音系统数据模型
定义语音条目、状态等核心数据结构
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from enum import Enum


class SelectionStrategy(Enum):
    """语音选择策略"""
    RANDOM = "random"           # 随机选择
    SEQUENTIAL = "sequential"    # 顺序播放
    WEIGHTED = "weighted"        # 加权选择
    CONTEXT_AWARE = "context"    # 上下文感知


class AudioStatus(Enum):
    """播放状态"""
    IDLE = "idle"
    PLAYING = "playing"
    STOPPED = "stopped"
    ENDED = "ended"
    ERROR = "error"


@dataclass
class AudioFile:
    """单个音频文件"""
    path: str                           # 相对路径，如 "016/1.mp3"
    weight: float = 1.0                 # 权重（用于加权选择）
    description: Optional[str] = None   # 描述
    
    def get_full_path(self, base_path: str) -> str:
        """获取完整路径"""
        return f"{base_path}/{self.path}".replace("//", "/")


@dataclass
class AudioEntry:
    """语音条目 - 对应 YAML 中的一个 entry"""
    entry_id: str                       # 条目ID，如 "greeting_hello"
    category: str                       # 分类，如 "system.greeting"
    intent: str                         # 语义意图，如 "hello"
    description: str                    # 描述
    files: List[AudioFile]              # 音频文件列表
    selection: SelectionStrategy = SelectionStrategy.RANDOM  # 选择策略
    cooldown: int = 0                   # 冷却次数（避免重复）
    tags: List[str] = field(default_factory=list)  # 标签
    
    # 拟声课程专用字段
    question_files: List[AudioFile] = field(default_factory=list)  # 提问语音
    answer_files: List[AudioFile] = field(default_factory=list)    # 回答语音
    
    def __post_init__(self):
        """后初始化处理"""
        # 确保 selection 是枚举类型
        if isinstance(self.selection, str):
            self.selection = SelectionStrategy(self.selection)
        
        # 确保 files 是 AudioFile 列表
        if self.files and isinstance(self.files[0], dict):
            self.files = [AudioFile(**f) if isinstance(f, dict) else f for f in self.files]
        
        if self.question_files and isinstance(self.question_files[0], dict):
            self.question_files = [AudioFile(**f) if isinstance(f, dict) else f 
                                  for f in self.question_files]
        
        if self.answer_files and isinstance(self.answer_files[0], dict):
            self.answer_files = [AudioFile(**f) if isinstance(f, dict) else f 
                                for f in self.answer_files]
    
    def get_file_count(self) -> int:
        """获取总文件数"""
        return len(self.files) + len(self.question_files) + len(self.answer_files)


@dataclass
class AudioContext:
    """播放上下文 - 用于上下文感知选择"""
    session_id: Optional[str] = None    # 会话ID
    student_id: Optional[int] = None    # 学生ID
    course_type: Optional[str] = None   # 课程类型
    course_id: Optional[int] = None     # 课程ID
    item_id: Optional[int] = None       # 课程项ID
    metadata: Dict[str, Any] = field(default_factory=dict)  # 额外元数据
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'session_id': self.session_id,
            'student_id': self.student_id,
            'course_type': self.course_type,
            'course_id': self.course_id,
            'item_id': self.item_id,
            'metadata': self.metadata
        }


@dataclass
class PlaybackStatus:
    """播放状态"""
    session_id: str                     # 会话ID
    status: AudioStatus                 # 当前状态
    current_audio_id: Optional[str] = None   # 当前播放的语音ID
    current_file: Optional[str] = None       # 当前播放的文件路径
    updated_at: Optional[float] = None       # 更新时间戳
    
    def __post_init__(self):
        """后初始化处理"""
        if isinstance(self.status, str):
            self.status = AudioStatus(self.status)
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'session_id': self.session_id,
            'status': self.status.value,
            'current_audio_id': self.current_audio_id,
            'current_file': self.current_file,
            'updated_at': self.updated_at
        }


@dataclass
class AudioManifest:
    """语音清单 - 对应整个 YAML 文件"""
    version: str                        # 版本号
    base_path: str                      # 基础路径
    entries: Dict[str, AudioEntry]      # 语音条目字典
    aliases: Dict[str, str]             # 别名映射
    course_defaults: Dict[str, Dict[str, str]]  # 课程默认语音映射
    
    def get_entry(self, entry_id: str) -> Optional[AudioEntry]:
        """获取语音条目（支持别名）"""
        # 先检查是否是别名
        if entry_id in self.aliases:
            entry_id = self.aliases[entry_id]
        
        return self.entries.get(entry_id)
    
    def get_course_default(self, course_type: str, audio_type: str) -> Optional[str]:
        """获取课程默认语音ID"""
        if course_type in self.course_defaults:
            return self.course_defaults[course_type].get(audio_type)
        return None
