"""六块之间的最小稳定端口。

Protocol 只描述协作边界，不包含实现、线程、文件名、数据库模型或 transport
细节。实现可以暂时由旧单例/旧 service adapter 提供。
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Protocol, Sequence

from .models import (
    AssetRef,
    BehaviorPlan,
    ModelDescriptor,
    Observation,
    AudioBatch,
    CapturePacket,
    CaptureSource,
    DeploymentProfile,
    DeviceProfile,
    DeviceProfileSnapshot,
    DeviceRef,
    DialogueRequest,
    DialogueResponse,
    EventEnvelope,
    FrameBatch,
    InteractionContext,
    ReadinessSnapshot,
    SessionRef,
    Score,
    SpeechCommand,
    TextObservation,
    TimePoint,
    TrackRef,
)


class Clock(Protocol):
    def monotonic_seconds(self) -> float: ...

    def wall_time_iso(self) -> str: ...


class SessionRepository(Protocol):
    def get(self, session: SessionRef) -> Optional[Mapping[str, Any]]: ...

    def save(self, session: SessionRef, record: Mapping[str, Any]) -> None: ...


class RecordingRepository(Protocol):
    def begin(self, session: SessionRef, tracks: Sequence[TrackRef]) -> Mapping[str, Any]: ...

    def append_timeline(self, session: SessionRef, entry: Mapping[str, Any]) -> None: ...

    def finalize(self, session: SessionRef, status: str = "finalized") -> Mapping[str, Any]: ...


class ContentCatalog(Protocol):
    def get_course(self, course_id: str) -> Optional[Mapping[str, Any]]: ...

    def get_item(self, course_id: str, item_id: str) -> Optional[Mapping[str, Any]]: ...


class DeviceRegistry(Protocol):
    def list_devices(self) -> Sequence[DeviceProfile]: ...

    def get(self, device_id: str) -> Optional[DeviceProfile]: ...

    def register(self, device: DeviceProfile) -> None: ...

    def unregister(self, device_id: str) -> None: ...

    def update(self, device_id: str, **changes: Any) -> DeviceProfile: ...

    def freeze(self, deployment: DeploymentProfile) -> DeviceProfileSnapshot: ...


class DeviceProfileStore(Protocol):
    """Persistence boundary for control-plane device configuration."""

    def load(self) -> Sequence[DeviceProfile]: ...

    def save(self, devices: Sequence[DeviceProfile]) -> None: ...


class DeviceDiscoveryPort(Protocol):
    def discover(self) -> Sequence[DeviceRef]: ...


class DeviceBroker(Protocol):
    def check(self, device: DeviceProfile) -> Mapping[str, Any]: ...

    def open(self, device: DeviceProfile) -> Any: ...

    def close(self, device_id: str) -> None: ...

    def reserve(self, device: DeviceProfile) -> Mapping[str, Any]: ...

    def release(self, device_id: str) -> None: ...


class CapturePort(Protocol):
    def prepare(self, session: SessionRef, tracks: Sequence[TrackRef]) -> Mapping[str, Any]: ...

    def start(self, session: SessionRef, tracks: Sequence[TrackRef]) -> Mapping[str, Any]: ...

    def stop(self, session: SessionRef) -> Mapping[str, Any]: ...

    def health(self, session: SessionRef) -> Mapping[str, Any]: ...


class CaptureSink(Protocol):
    def accept(self, packet: CapturePacket) -> Mapping[str, Any]: ...

    def accept_video(self, session: SessionRef, data: bytes, timestamp: TimePoint) -> Mapping[str, Any]: ...

    def accept_audio(self, session: SessionRef, data: bytes, timestamp: TimePoint) -> Mapping[str, Any]: ...


class AssetLibrary(Protocol):
    def get(self, asset: AssetRef) -> Optional[Mapping[str, Any]]: ...

    def list(self, kind: Optional[str] = None) -> Sequence[AssetRef]: ...


class AssetIndex(Protocol):
    def upsert(self, records: Sequence[Mapping[str, Any]]) -> Sequence[Mapping[str, Any]]: ...

    def get(self, asset_id: str, *, kind: Optional[str] = None, version: Optional[str] = None) -> Optional[Mapping[str, Any]]: ...

    def list(self, *, kind: Optional[str] = None) -> Sequence[Mapping[str, Any]]: ...


class BatchImportService(Protocol):
    def stage(self, items: Iterable[Mapping[str, Any]]) -> Mapping[str, Any]: ...

    def validate(self, staging_id: str) -> Mapping[str, Any]: ...

    def commit(self, staging_id: str) -> Mapping[str, Any]: ...

    def rollback(self, staging_id: str) -> Mapping[str, Any]: ...


class InteractionProfileRepository(Protocol):
    def get(self, course_id: str, version: Optional[str] = None) -> Optional[Mapping[str, Any]]: ...


class InteractionProfileStore(Protocol):
    """课程根交互方案的版本化读写边界。"""

    def get(self, course_id: str, version: Optional[str] = None) -> Optional[Mapping[str, Any]]: ...

    def list(self, course_id: Optional[str] = None) -> Sequence[Mapping[str, Any]]: ...

    def save_draft(self, profile: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def publish(self, course_id: str, version: str) -> Mapping[str, Any]: ...

    def rollback(self, course_id: str, version: str) -> Mapping[str, Any]: ...

    def deploy(self, course_id: str, version: str, stage: str, canary_percent: float = 0) -> Mapping[str, Any]: ...


class BehaviorResolver(Protocol):
    def resolve(self, context: InteractionContext) -> Mapping[str, Any]: ...


class ResourceResolver(Protocol):
    """将课程/事件/场景/台词上下文解析为原子多模态计划。"""

    def resolve(self, context: InteractionContext) -> BehaviorPlan: ...


class AnalysisEngine(Protocol):
    def analyze(self, session: SessionRef, input_data: Any) -> Mapping[str, Any]: ...

    def health(self) -> Mapping[str, Any]: ...


class ModelProvider(Protocol):
    def model_id(self) -> str: ...

    def analyze(self, input_data: Any, *, session: Optional[SessionRef] = None) -> Mapping[str, Any]: ...

    def close(self) -> None: ...


class AnalysisModel(Protocol):
    """第四阶段模型插件端口。"""

    @property
    def descriptor(self) -> ModelDescriptor: ...

    def prepare(self, config: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]: ...

    def health(self) -> Mapping[str, Any]: ...

    def analyze(self, batch: Any) -> Observation: ...

    def close(self) -> None: ...


class CourseProgression(Protocol):
    def advance(self, session: SessionRef, context: InteractionContext, result: Mapping[str, Any]) -> Mapping[str, Any]: ...


class DecisionEngine(Protocol):
    def decide(self, session: SessionRef, context: InteractionContext, observations: Sequence[Mapping[str, Any]]) -> Mapping[str, Any]: ...


class DialoguePort(Protocol):
    def respond(self, session: SessionRef, context: InteractionContext, text: Optional[str] = None, audio: Optional[bytes] = None) -> Sequence[SpeechCommand]: ...


class DialogueProvider(Protocol):
    """可替换的完整对话 provider；不依赖 Flask、Socket.IO 或机器人实现。"""

    def respond(self, request: DialogueRequest, cancel_event: Any = None) -> DialogueResponse: ...

    def health(self) -> Mapping[str, Any]: ...


class ASRProvider(Protocol):
    def transcribe(self, audio: bytes, *, mime_type: Optional[str] = None, request: Optional[DialogueRequest] = None) -> Mapping[str, Any]: ...


class TTSProvider(Protocol):
    def synthesize(self, text: str, *, request: DialogueRequest) -> Mapping[str, Any]: ...


class SpeechOutput(Protocol):
    def submit(self, command: SpeechCommand) -> Mapping[str, Any]: ...


class RobotCommandPort(Protocol):
    def submit(self, command: Mapping[str, Any]) -> Mapping[str, Any]: ...


class EventPublisher(Protocol):
    def publish(self, event: EventEnvelope) -> None: ...


class SessionLayoutPort(Protocol):
    def reserve(self, human_dir_name: str) -> Any: ...

    def track_filename(self, track: TrackRef) -> str: ...


class TimelineRepository(Protocol):
    def append(self, session: SessionRef, entry: Mapping[str, Any]) -> None: ...

    def finalize(self, session: SessionRef, end_relative_seconds: float) -> None: ...


class MetadataRepository(Protocol):
    def write(self, session: SessionRef, metadata: Mapping[str, Any]) -> None: ...

    def read(self, session: SessionRef) -> Optional[Mapping[str, Any]]: ...
