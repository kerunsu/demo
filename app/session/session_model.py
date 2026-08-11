"""
会话数据模型
定义会话的数据结构
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
import uuid


class SessionStatus(Enum):
    """会话状态枚举"""
    CREATED = "created"          # 已创建，未开始
    RECORDING = "recording"      # 正在录制
    ANALYZING = "analyzing"     # 正在分析
    COMPLETED = "completed"     # 已完成
    FAILED = "failed"            # 失败
    CANCELLED = "cancelled"      # 已取消


@dataclass
class Session:
    """
    训练会话数据模型
    
    一个会话代表一次完整的训练过程，包含：
    - 学生信息
    - 课程信息
    - 录制文件路径
    - 分析结果
    - 状态信息
    """
    # 会话基本信息
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    student_id: Optional[int] = None
    course_id: Optional[int] = None
    course_item_id: Optional[int] = None  # 课程项ID（可选）

    # 训练会话 / 题目窗口（整次上课贯穿）
    training_session_id: Optional[str] = None
    question_id: Optional[str] = None
    question_index: int = 0
    
    # 时间信息
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    
    # 状态信息
    status: SessionStatus = SessionStatus.CREATED
    
    # 文件路径
    video_file_path: Optional[str] = None
    audio_file_path: Optional[str] = None
    result_file_path: Optional[str] = None
    resolved_file_path: Optional[str] = None  # 实际播放的文件路径（随机选择后的）
    
    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 统计信息
    total_frames: int = 0
    total_audio_chunks: int = 0
    analysis_count: int = 0
    
    def start(self):
        """开始会话"""
        if self.status != SessionStatus.CREATED:
            raise ValueError(f"只能从CREATED状态开始会话，当前状态: {self.status}")
        self.status = SessionStatus.RECORDING
        self.started_at = datetime.utcnow()
    
    def stop(self):
        """停止会话"""
        if self.status not in [SessionStatus.RECORDING, SessionStatus.ANALYZING]:
            raise ValueError(f"只能从RECORDING或ANALYZING状态停止会话，当前状态: {self.status}")
        self.status = SessionStatus.COMPLETED
        self.ended_at = datetime.utcnow()
    
    def fail(self, error_message: str = None):
        """标记会话为失败"""
        self.status = SessionStatus.FAILED
        self.ended_at = datetime.utcnow()
        if error_message:
            self.metadata['error'] = error_message
    
    def cancel(self):
        """取消会话"""
        self.status = SessionStatus.CANCELLED
        self.ended_at = datetime.utcnow()
    
    def set_analyzing(self):
        """设置为分析状态"""
        if self.status != SessionStatus.RECORDING:
            raise ValueError(f"只能从RECORDING状态切换到ANALYZING，当前状态: {self.status}")
        self.status = SessionStatus.ANALYZING
    
    def is_active(self) -> bool:
        """检查会话是否处于活动状态"""
        return self.status in [SessionStatus.RECORDING, SessionStatus.ANALYZING]
    
    def get_duration(self) -> Optional[float]:
        """获取会话持续时间（秒）"""
        if not self.started_at:
            return None
        end_time = self.ended_at or datetime.utcnow()
        return (end_time - self.started_at).total_seconds()
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式（用于JSON序列化）"""
        return {
            'session_id': self.session_id,
            'student_id': self.student_id,
            'course_id': self.course_id,
            'course_item_id': self.course_item_id,
            'training_session_id': self.training_session_id,
            'question_id': self.question_id,
            'question_index': self.question_index,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
            'status': self.status.value,
            'video_file_path': self.video_file_path,
            'audio_file_path': self.audio_file_path,
            'result_file_path': self.result_file_path,
            'metadata': self.metadata,
            'total_frames': self.total_frames,
            'total_audio_chunks': self.total_audio_chunks,
            'analysis_count': self.analysis_count,
            'duration': self.get_duration()
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Session':
        """从字典创建Session对象"""
        session = cls(
            session_id=data.get('session_id', str(uuid.uuid4())),
            student_id=data.get('student_id'),
            course_id=data.get('course_id'),
            course_item_id=data.get('course_item_id'),
            training_session_id=data.get('training_session_id'),
            question_id=data.get('question_id'),
            question_index=int(data.get('question_index') or 0),
            status=SessionStatus(data.get('status', SessionStatus.CREATED.value)),
            video_file_path=data.get('video_file_path'),
            audio_file_path=data.get('audio_file_path'),
            result_file_path=data.get('result_file_path'),
            metadata=data.get('metadata', {}),
            total_frames=data.get('total_frames', 0),
            total_audio_chunks=data.get('total_audio_chunks', 0),
            analysis_count=data.get('analysis_count', 0)
        )
        
        # 解析时间字段
        if data.get('created_at'):
            session.created_at = datetime.fromisoformat(data['created_at'])
        if data.get('started_at'):
            session.started_at = datetime.fromisoformat(data['started_at'])
        if data.get('ended_at'):
            session.ended_at = datetime.fromisoformat(data['ended_at'])
        
        return session

