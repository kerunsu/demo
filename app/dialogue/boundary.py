"""语音对话的稳定边界与旧服务适配器。

这个模块只处理 DTO、provider 调用、超时和取消，不接触 Flask/Socket.IO、数据库、
录音器或机器人。现有 ``DialogueService`` 通过 ``LegacyDialogueAdapter`` 接入，
因此替换 provider 不需要改儿童端协议。
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import replace
from typing import Any, Callable, Mapping, Optional

from app.contracts.models import (
    AssetRef,
    DialogueRequest,
    DialogueResponse,
    InteractionContext,
    SessionRef,
    SpeechCommand,
)


WakeMatcher = Callable[[str], tuple[bool, str]]


def _session_id(request: DialogueRequest) -> str:
    session = request.session
    return str(session.session_id or session.training_session_id or session.media_session_id or "default")


def _cancelled(request: DialogueRequest, cancel_event: Optional[threading.Event]) -> Optional[DialogueResponse]:
    if cancel_event is not None and cancel_event.is_set():
        return DialogueResponse(
            request_id=request.request_id,
            session=request.session,
            context=request.context,
            status="cancelled",
            degraded=True,
            error="cancelled",
        )
    return None


def _asset_from_result(value: Any) -> Optional[AssetRef]:
    if isinstance(value, AssetRef):
        return value
    if not isinstance(value, Mapping):
        return None
    asset_id = value.get("assetId") or value.get("asset_id") or value.get("id")
    version = value.get("version") or "1"
    kind = value.get("kind") or "audio"
    if not asset_id:
        return None
    return AssetRef(
        asset_id=str(asset_id),
        version=str(version),
        kind=str(kind),
        filename=value.get("filename"),
        media_type=value.get("mediaType") or value.get("media_type"),
        checksum=value.get("checksum"),
        duration_seconds=value.get("durationSeconds") or value.get("duration_seconds"),
    )


def _speech_command(
    request: DialogueRequest,
    text: str,
    *,
    audio_asset: Optional[AssetRef] = None,
    pause_asr: bool = True,
    metadata: Optional[Mapping[str, Any]] = None,
) -> SpeechCommand:
    behavior_id = request.context.behavior_id
    return SpeechCommand(
        command_id=f"dialogue:{request.request_id}:{uuid.uuid4().hex[:8]}",
        text=text,
        audio_asset=audio_asset,
        line_id=request.context.line_id,
        behavior_id=behavior_id,
        session=request.session,
        context=request.context,
        pause_asr=bool(pause_asr),
        metadata=dict(metadata or {}),
    )


class LegacyDialogueAdapter:
    """把现有 ``DialogueService`` 映射为稳定 provider。

    唤醒状态仍由旧 Socket 适配层维护；这里不复制规则、历史窗口或安全策略，
    避免新边界和旧主链路出现两套行为。
    """

    def __init__(self, service: Any):
        self.service = service

    def respond(
        self,
        request: DialogueRequest,
        cancel_event: Optional[threading.Event] = None,
    ) -> DialogueResponse:
        stopped = _cancelled(request, cancel_event)
        if stopped is not None:
            return stopped
        text = (request.text or "").strip()
        if not text:
            return DialogueResponse(
                request_id=request.request_id,
                session=request.session,
                context=request.context,
                status="degraded",
                transcript="",
                degraded=True,
                error="empty_text",
                provider="legacy-dialogue",
            )
        generate = getattr(self.service, "generate_reply", None)
        if not callable(generate):
            return DialogueResponse(
                request_id=request.request_id,
                session=request.session,
                context=request.context,
                status="degraded",
                transcript=text,
                degraded=True,
                error="legacy_dialogue_provider_unavailable",
                provider="legacy-dialogue",
            )
        raw = generate(
            text,
            session_id=_session_id(request),
            page_context=dict(request.page_context),
        )
        raw = dict(raw) if isinstance(raw, Mapping) else {"reply": str(raw)}
        reply = str(raw.get("reply") or raw.get("text") or "").strip()
        if not reply:
            return DialogueResponse(
                request_id=request.request_id,
                session=request.session,
                context=request.context,
                status="degraded",
                transcript=text,
                degraded=True,
                error="empty_provider_reply",
                provider=str(raw.get("provider") or "legacy-dialogue"),
                metadata=raw,
            )
        command = _speech_command(
            request,
            reply,
            pause_asr=True,
            metadata={"source": "legacy-dialogue", "strategy": raw.get("strategy")},
        )
        return DialogueResponse(
            request_id=request.request_id,
            session=request.session,
            context=request.context,
            status="ok",
            transcript=text,
            text=reply,
            speech=(command,),
            provider=str(raw.get("provider") or "legacy-dialogue"),
            asr_paused=True,
            metadata=raw,
        )

    def health(self) -> Mapping[str, Any]:
        return {"ok": self.service is not None, "provider": "legacy-dialogue"}


class DialogueGateway:
    """带 ASR、唤醒、provider、TTS 端口的可关闭对话编排器。"""

    def __init__(
        self,
        provider: Any,
        *,
        asr: Any = None,
        tts: Any = None,
        wake_matcher: Optional[WakeMatcher] = None,
        timeout_ms: int = 30_000,
        max_workers: int = 2,
    ) -> None:
        if max_workers < 1:
            raise ValueError("dialogue_max_workers_must_be_positive")
        self.provider = provider
        self.asr = asr
        self.tts = tts
        self.wake_matcher = wake_matcher
        self.timeout_ms = max(1, int(timeout_ms))
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="dialogue-provider")
        self._closed = False
        self._lock = threading.RLock()

    def _call(self, fn: Callable[[], Any], *, cancel_event: Optional[threading.Event]) -> Any:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("cancelled")
        with self._lock:
            if self._closed:
                raise RuntimeError("gateway_closed")
        future: Future[Any] = self._executor.submit(fn)
        try:
            result = future.result(timeout=self.timeout_ms / 1000.0)
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("cancelled")
            return result
        except TimeoutError:
            future.cancel()
            raise RuntimeError("timeout")

    @staticmethod
    def _provider_response(request: DialogueRequest, raw: Any) -> DialogueResponse:
        if isinstance(raw, DialogueResponse):
            return raw
        if not isinstance(raw, Mapping):
            raw = {"text": str(raw)}
        text = raw.get("text") or raw.get("reply")
        return DialogueResponse(
            request_id=request.request_id,
            session=request.session,
            context=request.context,
            status=str(raw.get("status") or "ok"),
            transcript=raw.get("transcript") or request.text,
            text=str(text).strip() if text else None,
            provider=raw.get("provider"),
            degraded=bool(raw.get("degraded", False)),
            error=raw.get("error"),
            metadata=dict(raw),
        )

    def _transcribe(self, request: DialogueRequest, cancel_event: Optional[threading.Event]) -> str:
        if request.text is not None:
            return str(request.text).strip()
        if not request.audio or self.asr is None:
            return ""
        transcribe = getattr(self.asr, "transcribe", None)
        if callable(transcribe):
            raw = self._call(
                lambda: transcribe(request.audio or b"", mime_type=request.mime_type, request=request),
                cancel_event=cancel_event,
            )
        elif callable(self.asr):
            raw = self._call(lambda: self.asr(request.audio or b"", request), cancel_event=cancel_event)
        else:
            return ""
        if isinstance(raw, Mapping):
            return str(raw.get("transcript") or raw.get("text") or "").strip()
        return str(raw or "").strip()

    def _run_provider(self, request: DialogueRequest, cancel_event: Optional[threading.Event]) -> DialogueResponse:
        respond = getattr(self.provider, "respond", None)
        if not callable(respond):
            raise RuntimeError("dialogue_provider_invalid")
        raw = self._call(lambda: respond(request, cancel_event=cancel_event), cancel_event=cancel_event)
        return self._provider_response(request, raw)

    def _apply_tts(self, request: DialogueRequest, response: DialogueResponse, cancel_event: Optional[threading.Event]) -> DialogueResponse:
        if not response.text or response.speech or response.degraded:
            if response.speech:
                return replace(response, asr_paused=any(command.pause_asr for command in response.speech))
            return response
        if self.tts is None:
            command = _speech_command(request, response.text, pause_asr=True, metadata={"provider": response.provider, "tts": "browser-fallback"})
            return replace(response, speech=(command,), asr_paused=True)
        synthesize = getattr(self.tts, "synthesize", None)
        if callable(synthesize):
            raw = self._call(lambda: synthesize(response.text or "", request=request), cancel_event=cancel_event)
        elif callable(self.tts):
            raw = self._call(lambda: self.tts(response.text or "", request), cancel_event=cancel_event)
        else:
            raw = {}
        raw = dict(raw) if isinstance(raw, Mapping) else {}
        command = _speech_command(
            request,
            response.text,
            audio_asset=_asset_from_result(raw.get("audioAsset") or raw.get("audio_asset") or raw),
            pause_asr=bool(raw.get("pauseAsr", raw.get("pause_asr", True))),
            metadata={"provider": response.provider, "tts": raw},
        )
        return replace(response, speech=(command,), asr_paused=command.pause_asr)

    def respond(
        self,
        request: DialogueRequest,
        *,
        cancel_event: Optional[threading.Event] = None,
    ) -> DialogueResponse:
        stopped = _cancelled(request, cancel_event)
        if stopped is not None:
            return stopped
        try:
            transcript = self._transcribe(request, cancel_event)
            if not transcript:
                return replace(
                    DialogueResponse(
                        request_id=request.request_id,
                        session=request.session,
                        context=request.context,
                        status="degraded",
                        provider="asr" if request.audio else None,
                        degraded=True,
                        error="empty_transcript",
                    ),
                    transcript="",
                )
            original_transcript = transcript
            wake_matched = False
            if request.require_wake and not request.awake:
                if self.wake_matcher is None:
                    return DialogueResponse(
                        request_id=request.request_id,
                        session=request.session,
                        context=request.context,
                        status="degraded",
                        transcript=transcript,
                        degraded=True,
                        error="wake_matcher_unavailable",
                    )
                wake_matched, remainder = self.wake_matcher(transcript)
                if not wake_matched:
                    return DialogueResponse(
                        request_id=request.request_id,
                        session=request.session,
                        context=request.context,
                        status="not_awake",
                        transcript=transcript,
                        wake_matched=False,
                    )
                transcript = str(remainder or "").strip()
                if not transcript:
                    return DialogueResponse(
                        request_id=request.request_id,
                        session=request.session,
                        context=request.context,
                        status="awake",
                        transcript="",
                        wake_matched=True,
                    )
            provider_request = replace(request, text=transcript, awake=True if wake_matched else request.awake)
            response = self._run_provider(provider_request, cancel_event)
            response = replace(response, request_id=request.request_id, session=request.session, context=request.context, transcript=original_transcript, wake_matched=wake_matched)
            return self._apply_tts(provider_request, response, cancel_event)
        except Exception as exc:  # provider failures are explicit degraded results
            reason = str(exc) or exc.__class__.__name__
            return DialogueResponse(
                request_id=request.request_id,
                session=request.session,
                context=request.context,
                status="cancelled" if reason == "cancelled" else "degraded",
                degraded=True,
                error=reason,
            )

    def health(self) -> Mapping[str, Any]:
        try:
            health = getattr(self.provider, "health", None)
            return dict(health() if callable(health) else {"ok": True})
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)


__all__ = ["DialogueGateway", "LegacyDialogueAdapter"]
