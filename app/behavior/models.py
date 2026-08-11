"""
行为观测领域模型（训练会话 / 题目窗口 / 观测）
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


@dataclass
class AttentionObservation:
    observation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    training_session_id: str = ""
    question_id: str = ""
    runtime_session_id: Optional[str] = None
    timestamp: str = field(default_factory=_now_iso)
    score: float = 0.0
    state: str = "unknown"
    trend: str = "stable"
    data_quality: str = "VALID"  # VALID | DEGRADED | MISSING | complete | low_confidence | missing_device
    face_present: Optional[bool] = None
    orientation: Optional[str] = None
    confidence: Optional[float] = None
    algorithm_version: Optional[str] = None
    provider: str = "server"  # browser | server
    features: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EmotionObservation:
    observation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    training_session_id: str = ""
    question_id: str = ""
    runtime_session_id: Optional[str] = None
    timestamp: str = field(default_factory=_now_iso)
    positive: float = 0.0
    focused: float = 0.0
    frustrated: float = 0.0
    confidence: float = 0.0
    data_quality: str = "VALID"  # complete | low_confidence | insufficient | missing_device
    degraded: bool = False
    algorithm_version: Optional[str] = None
    provider: str = "browser"
    features: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LanguageObservation:
    observation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    training_session_id: str = ""
    question_id: str = ""
    runtime_session_id: Optional[str] = None
    timestamp: str = field(default_factory=_now_iso)
    kind: str = "speech_activity"  # speech_activity | transcript | acoustic
    value: Any = None
    speech_ratio: Optional[float] = None
    word_count: Optional[int] = None
    speech_duration: Optional[float] = None
    clarity_proxy: Optional[float] = None
    is_speech: Optional[bool] = None
    transcript: Optional[str] = None
    confidence: Optional[float] = None
    data_quality: str = "VALID"
    features: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InteractionEvent:
    """One server-ordered classroom interaction or modality transition."""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: str = ""
    training_session_id: str = ""
    runtime_session_id: Optional[str] = None
    question_id: Optional[str] = None
    request_id: Optional[str] = None
    behavior_id: Optional[str] = None
    actor: str = "server"
    timestamp: str = field(default_factory=_now_iso)
    server_epoch_ms: float = 0.0
    client_timestamp: Optional[str] = None
    state_before: str = "idle"
    state_after: str = "idle"
    degraded: bool = False
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QuestionWindow:
    question_id: str = ""
    training_session_id: str = ""
    runtime_session_id: Optional[str] = None
    course_id: Optional[int] = None
    course_item_id: Optional[int] = None
    question_index: int = 0
    course_type: str = "default"
    opened_at: str = field(default_factory=_now_iso)
    closed_at: Optional[str] = None
    status: str = "open"  # open | closed
    task_metrics: Dict[str, Any] = field(default_factory=dict)
    attention_summary: Dict[str, Any] = field(default_factory=dict)
    language_summary: Dict[str, Any] = field(default_factory=dict)
    emotion_summary: Dict[str, Any] = field(default_factory=dict)
    analysis_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TrainingSessionRecord:
    training_session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    student_id: Optional[int] = None
    status: str = "active"  # active | finalized
    created_at: str = field(default_factory=_now_iso)
    finalized_at: Optional[str] = None
    current_question_id: Optional[str] = None
    window_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SessionBehaviorSummary:
    training_session_id: str = ""
    student_id: Optional[int] = None
    finalized_at: str = field(default_factory=_now_iso)
    window_count: int = 0
    attention: Dict[str, Any] = field(default_factory=dict)
    language: Dict[str, Any] = field(default_factory=dict)
    emotion: Dict[str, Any] = field(default_factory=dict)
    task: Dict[str, Any] = field(default_factory=dict)
    windows: List[Dict[str, Any]] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
