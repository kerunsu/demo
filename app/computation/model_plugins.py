"""可替换分析模型插件边界。

这里不导入 Flask、Socket.IO、数据库、硬件 SDK 或对话服务。旧的
``AnalyzerRegistry`` 可以通过一个很薄的 adapter 注册进来，新模型只需实现
descriptor/prepare/health/analyze/close 五个端口。
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional

from app.contracts.models import (
    AudioBatch,
    FrameBatch,
    ModelDescriptor,
    Observation,
    SessionRef,
    TextObservation,
)


ModelFactory = Callable[[Optional[Mapping[str, Any]]], Any]
ModelInput = FrameBatch | AudioBatch | TextObservation | Any


@dataclass(frozen=True)
class ModelRegistration:
    descriptor: ModelDescriptor
    mode: str
    factory: ModelFactory


class ModelRegistry:
    """进程内模型注册表；注册本身不加载模型、不启动线程。"""

    def __init__(self) -> None:
        self._entries: Dict[str, Dict[str, ModelRegistration]] = {}
        self._lock = threading.RLock()

    def register(
        self,
        descriptor: ModelDescriptor,
        factory: ModelFactory,
        *,
        mode: str = "real",
    ) -> None:
        mode = str(mode or "real").strip().lower()
        if mode not in {"mock", "real"}:
            raise ValueError("model_mode_must_be_mock_or_real")
        if not descriptor.model_id or not descriptor.version:
            raise ValueError("model_descriptor_identity_required")
        with self._lock:
            self._entries.setdefault(descriptor.model_id, {})[mode] = ModelRegistration(
                descriptor=descriptor,
                mode=mode,
                factory=factory,
            )

    def describe(self, model_id: str, *, mode: str = "real") -> Optional[ModelDescriptor]:
        entry = self._resolve(model_id, mode)
        return entry.descriptor if entry else None

    def _resolve(self, model_id: str, mode: str) -> Optional[ModelRegistration]:
        with self._lock:
            modes = dict(self._entries.get(str(model_id), {}))
        requested = str(mode or "real").strip().lower()
        return modes.get(requested) or modes.get("mock")

    def create(
        self,
        model_id: str,
        *,
        mode: str = "real",
        config: Optional[Mapping[str, Any]] = None,
    ) -> Any:
        entry = self._resolve(model_id, mode)
        if entry is None:
            raise KeyError(f"model_not_registered:{model_id}")
        model = entry.factory(config)
        prepare = getattr(model, "prepare", None)
        if callable(prepare):
            prepare(config)
        return model

    def list_descriptors(self) -> tuple[ModelDescriptor, ...]:
        with self._lock:
            entries = [entry for modes in self._entries.values() for entry in modes.values()]
        unique: Dict[tuple[str, str, str], ModelDescriptor] = {}
        for entry in entries:
            unique[(entry.descriptor.model_id, entry.descriptor.version, entry.mode)] = entry.descriptor
        return tuple(unique.values())

    def health(self, model_id: str, *, mode: str = "real") -> Mapping[str, Any]:
        model = None
        try:
            model = self.create(model_id, mode=mode)
            health = getattr(model, "health", None)
            raw = dict(health() if callable(health) else {"ok": True})
            raw.setdefault("ok", True)
            raw.update({"modelId": model_id, "mode": mode})
            return raw
        except Exception as exc:  # health is data, not a process failure
            return {"ok": False, "modelId": model_id, "mode": mode, "error": str(exc)}
        finally:
            if model is not None:
                close = getattr(model, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass


def _session_for(batch: Any) -> SessionRef:
    session = getattr(batch, "session", None)
    return session if isinstance(session, SessionRef) else SessionRef()


def _degraded(
    *,
    model_id: str,
    model_version: str,
    batch: Any,
    reason: str,
    latency_ms: Optional[float] = None,
) -> Observation:
    return Observation(
        observation_id=f"obs-{uuid.uuid4().hex}",
        model_id=model_id,
        model_version=model_version,
        session=_session_for(batch),
        modality="unknown",
        values={},
        confidence=None,
        missing_reason=reason,
        latency_ms=latency_ms,
    )


class ModelPipeline:
    """带背压、超时和可关闭 executor 的最小模型流水线。"""

    def __init__(self, registry: ModelRegistry, *, max_workers: int = 2, max_pending: int = 16) -> None:
        if max_workers < 1 or max_pending < 1:
            raise ValueError("model_pipeline_limits_must_be_positive")
        self.registry = registry
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="analysis-model")
        self._slots = threading.BoundedSemaphore(max_pending)
        self._closed = False
        self._lock = threading.RLock()

    def analyze(
        self,
        model_id: str,
        batch: ModelInput,
        *,
        mode: str = "real",
        config: Optional[Mapping[str, Any]] = None,
        timeout_ms: int = 1000,
        cancel_event: Optional[threading.Event] = None,
    ) -> Observation:
        with self._lock:
            if self._closed:
                return _degraded(model_id=model_id, model_version="unknown", batch=batch, reason="pipeline_closed")
        descriptor = self.registry.describe(model_id, mode=mode)
        if descriptor is None:
            return _degraded(model_id=model_id, model_version="unknown", batch=batch, reason="model_not_registered")
        if cancel_event is not None and cancel_event.is_set():
            return _degraded(model_id=model_id, model_version=descriptor.version, batch=batch, reason="cancelled")
        if not self._slots.acquire(blocking=False):
            return _degraded(model_id=model_id, model_version=descriptor.version, batch=batch, reason="backpressure")

        started = time.perf_counter()

        def _run() -> Observation:
            model = None
            try:
                if cancel_event is not None and cancel_event.is_set():
                    return _degraded(model_id=model_id, model_version=descriptor.version, batch=batch, reason="cancelled")
                model = self.registry.create(model_id, mode=mode, config=config)
                result = model.analyze(batch)
                if not isinstance(result, Observation):
                    raise TypeError("analysis_model_must_return_observation")
                return result
            except Exception as exc:  # model failure is a degraded observation
                return _degraded(
                    model_id=model_id,
                    model_version=descriptor.version,
                    batch=batch,
                    reason=f"model_error:{exc}",
                    latency_ms=(time.perf_counter() - started) * 1000,
                )
            finally:
                if model is not None:
                    close = getattr(model, "close", None)
                    if callable(close):
                        try:
                            close()
                        except Exception:
                            pass

        future: Future[Observation] = self._executor.submit(_run)
        try:
            result = future.result(timeout=max(1, int(timeout_ms)) / 1000.0)
            if result.latency_ms is None:
                return Observation(
                    observation_id=result.observation_id,
                    model_id=result.model_id,
                    model_version=result.model_version,
                    session=result.session,
                    modality=result.modality,
                    values=result.values,
                    confidence=result.confidence,
                    relative_ms=result.relative_ms,
                    missing_reason=result.missing_reason,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    schema_version=result.schema_version,
                )
            return result
        except FuturesTimeoutError:
            future.cancel()
            return _degraded(
                model_id=model_id,
                model_version=descriptor.version,
                batch=batch,
                reason="timeout",
                latency_ms=(time.perf_counter() - started) * 1000,
            )
        finally:
            self._slots.release()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["ModelRegistry", "ModelPipeline", "ModelRegistration"]
