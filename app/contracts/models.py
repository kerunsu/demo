"""纯数据契约。

字段使用内部 snake_case；HTTP/Socket 的旧 camelCase 字段由 facade presenter
负责转换。时间统一使用 session monotonic seconds，并可同时携带墙上时钟 ISO
字符串用于跨进程校准。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Tuple


@dataclass(frozen=True)
class TimePoint:
    """一个可追溯的时间点；``monotonic_seconds`` 是排序基准，单位为秒。"""

    monotonic_seconds: float
    wall_time_iso: Optional[str] = None
    clock_domain: str = "server.monotonic"
    sequence: Optional[int] = None


@dataclass(frozen=True)
class SessionRef:
    """训练、媒体和行为链路之间的稳定关联。"""

    session_id: Optional[str] = None
    training_session_id: Optional[str] = None
    media_session_id: Optional[str] = None


@dataclass(frozen=True)
class DeviceRef:
    """跨 Server/Runtime 稳定识别的设备引用。"""

    device_id: str
    kind: str
    device_type: str
    runtime_id: Optional[str] = None
    label: Optional[str] = None
    enabled: bool = True
    required: bool = False
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DeviceProfile:
    """一台可参与采集/预览的设备配置。

    ``device_id`` 是跨进程稳定身份；``selector`` 只是当前部署中用于打开
    设备的选择器，设备数组顺序变化不得改变历史引用。
    """

    device_id: str
    track_id: str
    kind: str
    role: str
    location: Optional[str] = None
    owner: str = "server"
    runtime_id: Optional[str] = None
    selector: Mapping[str, Any] = field(default_factory=dict)
    enabled: bool = True
    required: bool = False
    priority: int = 0
    format: Mapping[str, Any] = field(default_factory=dict)
    capabilities: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = 1


@dataclass(frozen=True)
class DeviceProfileSnapshot:
    """一次训练冻结的设备配置；之后 registry 变化不影响本快照。"""

    snapshot_id: str
    created_at: TimePoint
    devices: Tuple[DeviceProfile, ...] = ()
    deployment_profile_id: Optional[str] = None
    schema_version: int = 1


@dataclass(frozen=True)
class DeploymentProfile:
    """部署级 required/optional 策略。"""

    profile_id: str = "default"
    version: str = "1"
    child_media_mode: str = "agent"
    required_modules: Tuple[str, ...] = ()
    optional_modules: Tuple[str, ...] = ()
    strict_preflight: bool = False


@dataclass(frozen=True)
class CaptureSource:
    """采集样本来源，不包含落盘路径。"""

    source_type: str
    owner: str
    runtime_id: Optional[str] = None
    device_id: Optional[str] = None
    track_id: Optional[str] = None


@dataclass(frozen=True)
class CapturePacket:
    """视频帧/音频块统一的上行 DTO。

    ``monotonic_ns`` 优先用于排序；``relative_ms`` 是已映射到整场 t=0
    的兼容字段；payload 可以是内存数据或隔离临时 artifact 引用。
    """

    source: CaptureSource
    session: SessionRef
    sequence: Optional[int] = None
    monotonic_ns: Optional[int] = None
    relative_ms: Optional[float] = None
    wall_time_iso: Optional[str] = None
    format: Mapping[str, Any] = field(default_factory=dict)
    payload: Any = None
    temporary_artifact: Optional[str] = None
    quality: Mapping[str, Any] = field(default_factory=dict)
    status: str = "accepted"


@dataclass(frozen=True)
class PreflightCheck:
    module_id: str
    status: str
    phase: str
    reason: Optional[str] = None
    repair_hint: Optional[str] = None
    device_id: Optional[str] = None
    track_id: Optional[str] = None
    required: bool = True
    details: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreflightResult:
    status: str
    required_ok: bool
    checks: Tuple[PreflightCheck, ...] = ()
    snapshot: Optional[DeviceProfileSnapshot] = None
    session: SessionRef = field(default_factory=SessionRef)
    schema_version: int = 1


@dataclass(frozen=True)
class TrackRef:
    """媒体轨道逻辑身份与兼容物理文件名的分离。"""

    track_id: str
    kind: str
    role: str
    device_id: Optional[str] = None
    runtime_id: Optional[str] = None
    required: bool = False
    filename: Optional[str] = None
    format: Optional[str] = None
    clock_domain: str = "server.monotonic"


@dataclass(frozen=True)
class AssetRef:
    """素材逻辑身份；物理文件名不是稳定引用。"""

    asset_id: str
    version: str
    kind: str
    filename: Optional[str] = None
    media_type: Optional[str] = None
    checksum: Optional[str] = None
    duration_seconds: Optional[float] = None


@dataclass(frozen=True)
class InteractionContext:
    """课程内事件、情境和台词的明确上下文。"""

    course_id: Optional[str] = None
    course_type: Optional[str] = None
    item_id: Optional[str] = None
    question_id: Optional[str] = None
    event_key: Optional[str] = None
    scene_key: Optional[str] = None
    line_id: Optional[str] = None
    student_id: Optional[str] = None
    profile_version: Optional[str] = None
    behavior_id: Optional[str] = None
    request_id: Optional[str] = None
    current_state: Optional[str] = None
    capabilities: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SpeechCommand:
    """语音对话输出的稳定播报指令，不直接绑定播放器或机器人。"""

    command_id: str
    text: Optional[str] = None
    audio_asset: Optional[AssetRef] = None
    line_id: Optional[str] = None
    behavior_id: Optional[str] = None
    session: SessionRef = field(default_factory=SessionRef)
    context: Optional[InteractionContext] = None
    pause_asr: bool = True
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DialogueRequest:
    """语音对话边界的输入。

    ``page_context`` 是页面在本轮请求时的不可变快照；对话实现不得通过它反查
    数据库、录音文件或机器人对象。``audio`` 只在进程内传递，落盘仍属于采集/存储块。
    """

    request_id: str
    session: SessionRef = field(default_factory=SessionRef)
    context: InteractionContext = field(default_factory=InteractionContext)
    text: Optional[str] = None
    audio: Optional[bytes] = None
    mime_type: Optional[str] = None
    page_context: Mapping[str, Any] = field(default_factory=dict)
    require_wake: bool = True
    awake: bool = False
    schema_version: int = 1


@dataclass(frozen=True)
class DialogueResponse:
    """语音对话边界的输出。

    ``status`` 仅描述本轮处理结果（ok/not_awake/degraded/cancelled/error），
    不把 provider 的异常升级为 HTTP/Socket 异常。没有可靠结果时
    ``degraded=True`` 且不伪造高置信度回复。
    """

    request_id: str
    session: SessionRef = field(default_factory=SessionRef)
    context: InteractionContext = field(default_factory=InteractionContext)
    status: str = "ok"
    transcript: Optional[str] = None
    text: Optional[str] = None
    speech: Tuple[SpeechCommand, ...] = ()
    provider: Optional[str] = None
    wake_matched: bool = False
    asr_paused: bool = False
    degraded: bool = False
    error: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = 1


@dataclass(frozen=True)
class FrameBatch:
    """计算模型输入：已映射到 session 时间轴的视频帧批次。"""

    session: SessionRef
    frames: Tuple[Any, ...] = ()
    start_relative_ms: Optional[float] = None
    end_relative_ms: Optional[float] = None
    quality: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = 1


@dataclass(frozen=True)
class AudioBatch:
    """计算模型输入：已映射到 session 时间轴的音频块批次。"""

    session: SessionRef
    chunks: Tuple[Any, ...] = ()
    start_relative_ms: Optional[float] = None
    end_relative_ms: Optional[float] = None
    sample_rate_hz: Optional[int] = None
    quality: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = 1


@dataclass(frozen=True)
class TextObservation:
    """表达性语言/ASR 的标准文本输入，不携带对话历史实现。"""

    session: SessionRef
    text: str = ""
    relative_ms: Optional[float] = None
    language: Optional[str] = "zh-CN"
    quality: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = 1


@dataclass(frozen=True)
class ModelDescriptor:
    """可替换分析模型的声明，不依赖 Flask、Socket.IO 或具体 SDK。"""

    model_id: str
    version: str
    modalities: Tuple[str, ...] = ()
    capabilities: Tuple[str, ...] = ()
    config_schema: Mapping[str, Any] = field(default_factory=dict)
    resource_needs: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = 1


@dataclass(frozen=True)
class Observation:
    """模型输出的可审计观测；缺数据时必须显式给出 reason。"""

    observation_id: str
    model_id: str
    model_version: str
    session: SessionRef
    modality: str
    values: Mapping[str, Any] = field(default_factory=dict)
    confidence: Optional[float] = None
    relative_ms: Optional[float] = None
    missing_reason: Optional[str] = None
    latency_ms: Optional[float] = None
    schema_version: int = 1


@dataclass(frozen=True)
class Score:
    """标准评分输出，分数范围由 score_min/score_max 明确。"""

    score_id: str
    session: SessionRef
    key: str
    value: Optional[float]
    score_min: float = 0.0
    score_max: float = 1.0
    confidence: Optional[float] = None
    missing_reason: Optional[str] = None
    model_id: Optional[str] = None
    model_version: Optional[str] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = 1


@dataclass(frozen=True)
class DecisionCandidate:
    """计算块产出的候选决策；门面负责转换为旧 Socket 事件。"""

    decision_id: str
    session: SessionRef
    event_key: str
    confidence: Optional[float] = None
    priority: int = 0
    reason: Optional[str] = None
    context: Optional[InteractionContext] = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = 1


@dataclass(frozen=True)
class BehaviorPlan:
    """一次行为编排的不可变结果，动作/表情/语音/课程命令同一行为 ID。"""

    behavior_id: str
    request_id: Optional[str]
    context: InteractionContext
    profile_version: Optional[str] = None
    source: str = "legacy"
    speech: Tuple[SpeechCommand, ...] = ()
    motions: Tuple[Mapping[str, Any], ...] = ()
    expressions: Tuple[Mapping[str, Any], ...] = ()
    visual: Tuple[Mapping[str, Any], ...] = ()
    course_commands: Tuple[Mapping[str, Any], ...] = ()
    resolution_trace: Tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: int = 1


@dataclass(frozen=True)
class EventEnvelope:
    """跨块事件信封；transport 的 room/ack 细节仍由 facade 适配。"""

    event: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None
    behavior_id: Optional[str] = None
    session: SessionRef = field(default_factory=SessionRef)
    timestamp: Optional[TimePoint] = None
    schema_version: int = 1


@dataclass(frozen=True)
class ReadinessSnapshot:
    """模块/设备预检结果；``status`` 只允许由用例解释。"""

    status: str
    required_ok: bool
    modules: Tuple[Mapping[str, Any], ...] = ()
    devices: Tuple[Mapping[str, Any], ...] = ()
    failures: Tuple[Mapping[str, Any], ...] = ()
    session: SessionRef = field(default_factory=SessionRef)
    schema_version: int = 1


@dataclass(frozen=True)
class ServerStatusSnapshot:
    """server status 的内部 DTO；presenter 再转换为旧 camelCase JSON。"""

    statistics: Mapping[str, Any]
    sessions: Mapping[str, Any]
    model_status: Mapping[str, Any]
    global_mode: Optional[str]
    snapshot_count: int
    history_count: int
    online_presence: Mapping[str, Any]
    robot_control_mode: Any
    child_media_mode: Any
    media_session_meta: Mapping[str, Any]
    robot_runtime: Mapping[str, Any]
