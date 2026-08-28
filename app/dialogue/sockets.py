"""对话相关 Socket 事件：语音轮次 / 文本轮次。"""



from __future__ import annotations



from typing import Any, Dict, Optional
import re
import threading
import time

import uuid



from flask import request, session as flask_session
from flask_socketio import emit, join_room, leave_room

from app.config import Config



from app.dialogue.page_context_store import merge_page_context

from app.dialogue.phrases import pick_phrase

from app.dialogue.service import (

    WAKE_ACK_REPLY,

    get_dialogue_service,

    parse_wake_utterance,

)
from app.dialogue.voice_config import (
    FIXED_BROWSER_TTS_VOICE_NAME,
    is_fixed_browser_tts_voice_name,
    project_fixed_browser_tts_runtime_state,
)


from app.utils.logger import setup_logger



logger = setup_logger("dialogue.sockets")

_dialogue_ui_lock = threading.RLock()
_dialogue_ui_visible: Dict[str, bool] = {}
_pending_dialogue_speak_lock = threading.RLock()
_pending_dialogue_speak: Dict[str, Dict[str, Any]] = {}
_pending_dialogue_speak_timers: Dict[str, threading.Timer] = {}
_PENDING_DIALOGUE_RETRY_SEC = 0.2
_PENDING_DIALOGUE_TTL_SEC = 12.0
_dialogue_socketio = None
_dialogue_runtime_state: Dict[str, Dict[str, Any]] = {}
_dialogue_visible_messages: Dict[str, list[Dict[str, Any]]] = {}
_dialogue_turn_dedupe_lock = threading.RLock()
_dialogue_turn_requests: Dict[tuple[str, str], float] = {}
_dialogue_recent_transcripts: Dict[tuple[str, str, str], float] = {}
_dialogue_reply_control_lock = threading.RLock()
_dialogue_reply_generations: Dict[str, int] = {}
_active_dialogue_reply_behaviors: Dict[str, str] = {}


def _current_dialogue_reply_generation(session_id: Any) -> int:
    sid = str(session_id or "").strip()
    with _dialogue_reply_control_lock:
        return int(_dialogue_reply_generations.get(sid, 0))


def _dialogue_reply_generation_is_current(
    session_id: Any,
    generation: Optional[int],
) -> bool:
    if generation is None:
        return True
    sid = str(session_id or "").strip()
    with _dialogue_reply_control_lock:
        return int(_dialogue_reply_generations.get(sid, 0)) == int(generation)


def _cancel_dialogue_replies(session_id: Any, *, reason: str) -> Dict[str, Any]:
    """Invalidate generation/queue/playback without stopping continuous ASR."""
    sid = str(session_id or "").strip()
    if not sid:
        return {
            "generation": 0,
            "pendingCancelled": False,
            "activeCancelled": False,
        }
    with _dialogue_reply_control_lock:
        generation = int(_dialogue_reply_generations.get(sid, 0)) + 1
        _dialogue_reply_generations[sid] = generation
        behavior_id = _active_dialogue_reply_behaviors.pop(sid, None)

    pending_cancelled = cancel_pending_dialogue_speak(sid, reason=reason)
    active_cancelled = False
    if behavior_id:
        try:
            from app.robot import get_robot_service

            active_cancelled = bool(get_robot_service().abort_behavior(behavior_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "停止智能体回复失败 session=%s behavior=%s: %s",
                sid,
                behavior_id,
                exc,
            )
    return {
        "generation": generation,
        "pendingCancelled": bool(pending_cancelled),
        "activeCancelled": bool(active_cancelled),
    }


def _activate_dialogue_wake(
    session_id: Any,
    page_context: Optional[Dict[str, Any]] = None,
    *,
    defer_context_binding: bool = False,
    expected_generation: Optional[int] = None,
    service: Any = None,
) -> bool:
    """Shared awake-state transition for wake word and teacher control."""
    dialogue_service = service or get_dialogue_service()
    with _dialogue_reply_control_lock:
        if not _dialogue_reply_generation_is_current(
            session_id,
            expected_generation,
        ):
            return False
        if defer_context_binding:
            dialogue_service.set_awake(
                str(session_id),
                defer_context_binding=True,
            )
        else:
            dialogue_service.set_awake(str(session_id), page_context or {})
    return True


def _claim_dialogue_turn(
    session_id: str,
    request_id: str,
    transcript: str,
    page_context: Dict[str, Any],
    *,
    recognition_provider: Optional[str] = None,
) -> Optional[str]:
    """Atomically reject request replays and near-simultaneous browser finals."""
    now = time.monotonic()
    request_key = (str(session_id), str(request_id))
    normalized = re.sub(r"[\W_]+", "", str(transcript or "").lower(), flags=re.UNICODE)
    context_key = "|".join(
        str(page_context.get(key) or "")
        for key in ("courseType", "courseId", "questionId", "itemId", "questionIndex")
    )
    transcript_key = (str(session_id), context_key, normalized)
    is_browser = str(recognition_provider or "").lower().startswith("browser")
    with _dialogue_turn_dedupe_lock:
        for key, seen_at in list(_dialogue_turn_requests.items()):
            if now - seen_at > 120:
                _dialogue_turn_requests.pop(key, None)
        for key, seen_at in list(_dialogue_recent_transcripts.items()):
            if now - seen_at > 8:
                _dialogue_recent_transcripts.pop(key, None)
        if request_key in _dialogue_turn_requests:
            return "duplicate_request"
        if (
            is_browser
            and normalized
            and now - _dialogue_recent_transcripts.get(transcript_key, -999) < 3
        ):
            _dialogue_turn_requests[request_key] = now
            return "duplicate_transcript"
        _dialogue_turn_requests[request_key] = now
        if is_browser and normalized:
            _dialogue_recent_transcripts[transcript_key] = now
    return None


def _training_id_for_runtime(session_id: Any) -> Optional[str]:
    try:
        from app.session import get_session_manager
        runtime = get_session_manager().get_session(str(session_id or ""))
        value = getattr(runtime, "training_session_id", None) if runtime else None
        return str(value) if value else None
    except Exception:
        return None


def _authorize_teacher_control(data: Dict[str, Any]) -> Dict[str, Any]:
    try:
        teacher_id = int(flask_session.get("teacher_id"))
    except (TypeError, ValueError):
        return {"ok": False, "error": "teacher_auth_required"}
    training_id = (
        data.get("trainingSessionId") or data.get("training_session_id")
        or _training_id_for_runtime(data.get("sessionId") or data.get("session_id"))
    )
    if not training_id:
        return {"ok": False, "error": "training_session_id_missing"}
    from app.services.teacher_control import get_teacher_control_registry
    result = get_teacher_control_registry().authorize(
        str(training_id), teacher_id=teacher_id, sid=request.sid
    )
    if not result.get("ok") or not result.get("writable"):
        return {"ok": False, "error": result.get("error") or "observer_read_only"}
    return {"ok": True, "trainingSessionId": str(training_id), "teacherId": teacher_id}


def _resolve_manual_wake_target(data: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve an active course and its exact child without a teacher lease gate."""
    session_id = str(data.get("sessionId") or data.get("session_id") or "").strip()
    if not session_id:
        return {"ok": False, "error": "session_id_missing"}
    try:
        from app.session import get_session_manager

        runtime = get_session_manager().get_session(session_id)
    except Exception:
        runtime = None
    if runtime is None:
        return {"ok": False, "error": "session_not_found"}
    if not runtime.is_active():
        return {"ok": False, "error": "active_course_missing"}
    training_id = str(getattr(runtime, "training_session_id", None) or "").strip()
    course_id = getattr(runtime, "course_id", None)
    course_type = str((getattr(runtime, "metadata", None) or {}).get("course_type") or "").strip()
    if not training_id or (course_id is None and not course_type):
        return {"ok": False, "error": "active_course_missing"}
    requested_training = str(
        data.get("trainingSessionId") or data.get("training_session_id") or ""
    ).strip()
    if requested_training and requested_training != training_id:
        return {"ok": False, "error": "session_mismatch"}
    try:
        from app.sockets.events import get_connected_child_sid

        child_sid = get_connected_child_sid(session_id)
    except Exception:
        child_sid = None
    if not child_sid:
        return {"ok": False, "error": "child_not_connected"}
    return {
        "ok": True,
        "sessionId": session_id,
        "trainingSessionId": training_id,
        "childSid": child_sid,
        "childRoom": _child_room(session_id),
        "standby": False,
    }


def _resolve_dialogue_target(
    data: Dict[str, Any],
    *,
    allow_standby: bool = False,
) -> Dict[str, Any]:
    """Resolve an active course or a unique child's private standby scope."""
    session_id = str(data.get("sessionId") or data.get("session_id") or "").strip()
    if session_id.startswith("dialogue-standby-"):
        try:
            from app.sockets.events import get_connected_child_sid

            child_sid = get_connected_child_sid(session_id)
        except Exception:
            child_sid = None
        if not child_sid:
            return {"ok": False, "error": "child_not_connected"}
        return {
            "ok": True,
            "sessionId": session_id,
            "trainingSessionId": None,
            "childSid": child_sid,
            "childRoom": _child_room(session_id),
            "standby": True,
        }
    if session_id:
        return _resolve_manual_wake_target(data)
    if not allow_standby:
        return {"ok": False, "error": "session_id_missing"}
    try:
        from app.sockets.events import bind_unique_child_to_dialogue_standby

        target = bind_unique_child_to_dialogue_standby(_dialogue_socketio)
    except Exception as exc:
        logger.warning("建立儿童端待机对话会话失败: %s", exc, exc_info=True)
        return {"ok": False, "error": "standby_session_unavailable"}
    if not target.get("ok"):
        return target
    return {
        **target,
        "childRoom": _child_room(target.get("sessionId")),
    }


def _audit_dialogue(event: str, data: Dict[str, Any], **extra: Any) -> None:
    try:
        from app.behavior.audit_timeline import record_audit_event
        record_audit_event(
            event,
            training_session_id=data.get("trainingSessionId") or data.get("training_session_id"),
            runtime_session_id=data.get("sessionId") or data.get("session_id"),
            question_id=data.get("questionId") or data.get("question_id"),
            request_id=data.get("requestId") or data.get("request_id"),
            actor=extra.pop("actor", "dialogue_service"),
            source=extra.pop("source", "dialogue"),
            category="dialogue",
            **extra,
        )
    except Exception:
        pass


def _record_visible_dialogue_message(
    *,
    session_id: str,
    role: str,
    text: str,
    request_id: Optional[str],
) -> None:
    """Best-effort transcript persistence must never break a live dialogue."""
    try:
        from app.services.recording_timeline import append_dialogue_timeline_message

        append_dialogue_timeline_message(
            str(session_id),
            role=role,
            text=text,
            request_id=request_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "对话文本落盘失败 sid=%s role=%s: %s",
            session_id,
            role,
            exc,
        )
    message_payload = {
        "type": "message",
        "sessionId": str(session_id),
        "role": role,
        "text": str(text),
        "requestId": request_id,
        "serverTimestamp": int(time.time() * 1000),
    }
    with _dialogue_ui_lock:
        history = _dialogue_visible_messages.setdefault(str(session_id), [])
        history.append(dict(message_payload))
        del history[:-64]
    server_room = _server_room(session_id)
    if _dialogue_socketio is not None and server_room and text:
        _dialogue_socketio.emit(
            "server_dialogue_event",
            message_payload,
            room=server_room,
        )


def record_visible_dialogue_message(
    *,
    session_id: str,
    role: str,
    text: str,
    request_id: Optional[str] = None,
) -> None:
    """Public bridge for fixed course speech that is visible to the child."""
    _record_visible_dialogue_message(
        session_id=session_id,
        role=role,
        text=text,
        request_id=request_id,
    )


def _dialogue_context_identity(context: Optional[Dict[str, Any]]) -> str:
    data = context if isinstance(context, dict) else {}
    aliases = (
        ("courseType", "course_type"),
        ("courseId", "course_id"),
        ("itemId", "item_id"),
        ("questionId", "question_id"),
        ("questionIndex", "question_index"),
    )
    values = []
    for primary, legacy in aliases:
        value = data.get(primary)
        if value is None:
            value = data.get(legacy)
        values.append(str(value).strip() if value is not None else "")
    return "|".join(values).strip("|")


def _audit_pending_dialogue_cancelled(
    session_id: str,
    pending: Dict[str, Any],
    reason: str,
) -> None:
    _audit_dialogue(
        "dialogue.tts_cancelled",
        {
            "sessionId": session_id,
            "requestId": pending.get("dialogue_request_id"),
        },
        phase="cancelled",
        status=str(reason or "cancelled"),
        modality="audio",
        details={
            "intent": pending.get("intent"),
            "contextIdentity": pending.get("context_identity"),
            "queuedMs": max(
                0,
                int(
                    (time.monotonic() - float(pending.get("queued_at") or 0))
                    * 1000
                ),
            ),
        },
    )





def _emit_speak(

    *,

    room: Optional[str],

    text: str,

    intent: str,

    delay_ms: int = 0,

    source: str = "dialogue",

    session_id: Optional[str] = None,

    dialogue_request_id: Optional[str] = None,

    page_context: Optional[Dict[str, Any]] = None,

    dialogue_generation: Optional[int] = None,

    _queued_at: Optional[float] = None,

    _expires_at: Optional[float] = None,

) -> bool:

    spoken = (text or "").strip()

    if not spoken:

        logger.warning("跳过空 robot_speak_text intent=%s source=%s", intent, source)

        return False

    resolved_session_id = str(session_id or "").strip()
    if not resolved_session_id and room:
        prefix = "session_"
        suffix = "_child"
        if room.startswith(prefix) and room.endswith(suffix):
            resolved_session_id = room[len(prefix):-len(suffix)]
    if not room or not resolved_session_id:
        logger.warning(
            "拒绝无精确儿童会话的 robot_speak_text intent=%s source=%s",
            intent,
            source,
        )
        return False

    is_agent_reply = source == "dialogue" and intent in ("dialogue", "wake_ack")
    if is_agent_reply and dialogue_generation is None:
        dialogue_generation = _current_dialogue_reply_generation(
            resolved_session_id
        )
    if is_agent_reply and not _dialogue_reply_generation_is_current(
        resolved_session_id,
        dialogue_generation,
    ):
        logger.info(
            "跳过已停止的智能体回复 session=%s request=%s",
            resolved_session_id,
            dialogue_request_id,
        )
        return False

    behavior_id = f"dialogue-{uuid.uuid4().hex[:12]}"
    request_id = f"dialogue-request-{uuid.uuid4().hex[:12]}"
    expression_timeout_ms = min(
        30000,
        max(5000, len(spoken) * 360 + max(0, int(delay_ms or 0)) + 2500),
    )
    try:
        from app.robot import get_robot_service

        robot_service = get_robot_service()
        expression_match = None
        if intent == "dialogue" and source == "dialogue":
            selector = getattr(robot_service, "select_dialogue_reply_emotion", None)
            if callable(selector):
                expression_match = selector(spoken)
        elif intent == "wake_ack":
            wake_selector = getattr(robot_service, "select_dialogue_wake_behavior", None)
            if callable(wake_selector):
                wake_behavior = wake_selector() or {}
                if wake_behavior.get("emotion"):
                    expression_match = {
                        "emotion": wake_behavior["emotion"],
                        "sequence": wake_behavior.get("sequence") or {},
                    }

        reserve = (
            robot_service.reserve_behavior
            if expression_match
            else robot_service.reserve_audio_only_behavior
        )
        reservation = reserve(
            behavior_id=behavior_id,
            request_id=request_id,
            session_id=resolved_session_id,
        )
        if not reservation.get("accepted"):
            if _queued_at is None:
                logger.info(
                    "正式行为忙碌，排队本次对话朗读 session=%s active=%s intent=%s",
                    resolved_session_id,
                    reservation.get("activeBehaviorId"),
                    intent,
                )
            _queue_pending_dialogue_speak(
                resolved_session_id,
                {
                    "room": room,
                    "text": spoken,
                    "intent": intent,
                    "delay_ms": delay_ms,
                    "source": source,
                    "session_id": resolved_session_id,
                    "dialogue_request_id": dialogue_request_id,
                    "page_context": dict(page_context or {}),
                    "context_identity": _dialogue_context_identity(page_context),
                    "queued_at": _queued_at,
                    "expires_at": _expires_at,
                    "dialogue_generation": dialogue_generation,
                },
            )
            return False
        behavior_id = str(reservation.get("behaviorId") or behavior_id)
        behavior_result = None
        if expression_match:
            starter = getattr(robot_service, "start_dialogue_reply_behavior", None)
            if callable(starter):
                behavior_result = starter(
                    emotion=expression_match.get("emotion"),
                    motion=None,
                    sequence=expression_match.get("sequence") or {},
                    behavior_id=behavior_id,
                    request_id=request_id,
                    session_id=resolved_session_id,
                    speech_timeout_ms=expression_timeout_ms,
                )
            if not behavior_result:
                robot_service.abort_behavior(behavior_id)
                expression_match = None
                reservation = robot_service.reserve_audio_only_behavior(
                    behavior_id=behavior_id,
                    request_id=request_id,
                    session_id=resolved_session_id,
                )
                if not reservation.get("accepted"):
                    _queue_pending_dialogue_speak(
                        resolved_session_id,
                        {
                            "room": room,
                            "text": spoken,
                            "intent": intent,
                            "delay_ms": delay_ms,
                            "source": source,
                            "session_id": resolved_session_id,
                            "dialogue_request_id": dialogue_request_id,
                            "page_context": dict(page_context or {}),
                            "context_identity": _dialogue_context_identity(page_context),
                            "queued_at": _queued_at,
                            "expires_at": _expires_at,
                            "dialogue_generation": dialogue_generation,
                        },
                    )
                    return False
    except Exception as exc:
        logger.error("对话语音预占失败: %s", exc, exc_info=True)
        return False

    payload = {

        "text": spoken,

        "intent": intent,

        "delayMs": max(
            0,
            int(delay_ms or 0),
            int((behavior_result or {}).get("scheduledDelayMs") or 0),
        ),

        "source": source,

        "ttsMode": "browser",

        "sessionId": resolved_session_id,

        "session_id": resolved_session_id,

        "behaviorId": behavior_id,

        "behavior_id": behavior_id,

        "interactionId": behavior_id,

        "requestId": request_id,

        "request_id": request_id,

        "dialogueRequestId": dialogue_request_id,

        "speechRate": float(Config.BROWSER_SPEECH_RATE),

    }
    if expression_match:
        payload["expression"] = expression_match["emotion"]

    timeout_ms = min(
        30000,
        max(
            5000,
            len(spoken) * 360 + int(payload["delayMs"]) + 1500,
        ),
    )
    try:
        # Keep the final generation check, dispatch and active-id publication
        # atomic with teacher stop. A stop that wins this lock suppresses the
        # output; a stop immediately after dispatch aborts its exact behavior.
        with _dialogue_reply_control_lock:
            if is_agent_reply and not _dialogue_reply_generation_is_current(
                resolved_session_id,
                dialogue_generation,
            ):
                robot_service.abort_behavior(behavior_id)
                return False
            if not robot_service.set_behavior_audio_expected(
                behavior_id,
                1,
                session_id=resolved_session_id,
                timeout_ms=timeout_ms,
            ):
                robot_service.abort_behavior(behavior_id)
                logger.warning(
                    "对话语音下发后未能提交行为锁 session=%s behavior=%s",
                    resolved_session_id,
                    behavior_id,
                )
                return False
            # Exactly one room-scoped delivery. Direct+broadcast duplicates
            # could cancel/restart speech and leak dialogue to another child.
            try:
                emit("robot_speak_text", payload, room=room, include_self=True)
            except Exception:
                from app.services.keyword_listen import KeywordListenService

                sio = KeywordListenService._resolve_socketio()
                if sio is None:
                    raise
                sio.emit("robot_speak_text", payload, room=room)
            if is_agent_reply:
                _active_dialogue_reply_behaviors[resolved_session_id] = behavior_id
    except Exception as exc:
        robot_service.abort_behavior(behavior_id)
        logger.error("对话语音下发失败: %s", exc, exc_info=True)
        return False

    _audit_dialogue(
        "dialogue.tts_dispatched",
        {"sessionId": resolved_session_id, "requestId": dialogue_request_id},
        phase="dispatched",
        status="sent",
        modality="audio",
        details={
            "intent": intent,
            "textLength": len(spoken),
            "behaviorRequestId": request_id,
            "behaviorId": behavior_id,
        },
    )

    logger.info(

        "robot_speak_text intent=%s source=%s room=%s text=%s",

        intent,

        source,

        room,

        spoken[:40],

    )
    return True


def _schedule_pending_dialogue_speak_flush(session_id: str) -> bool:
    sid = str(session_id or "").strip()
    if not sid:
        return False

    timer = None

    def flush_once() -> None:
        with _pending_dialogue_speak_lock:
            if _pending_dialogue_speak_timers.get(sid) is timer:
                _pending_dialogue_speak_timers.pop(sid, None)
        flush_pending_dialogue_speak(sid)
        if pending_dialogue_speak_queued(sid):
            _schedule_pending_dialogue_speak_flush(sid)

    with _pending_dialogue_speak_lock:
        existing = _pending_dialogue_speak_timers.get(sid)
        if existing is not None and existing.is_alive():
            return False
        timer = threading.Timer(_PENDING_DIALOGUE_RETRY_SEC, flush_once)
        timer.daemon = True
        _pending_dialogue_speak_timers[sid] = timer
    timer.start()
    return True


def _queue_pending_dialogue_speak(session_id: str, payload: Dict[str, Any]) -> None:
    sid = str(session_id or "").strip()
    if not sid or not (payload.get("text") or "").strip():
        return
    dialogue_generation = payload.get("dialogue_generation")
    if dialogue_generation is not None and not _dialogue_reply_generation_is_current(
        sid,
        dialogue_generation,
    ):
        return
    now = time.monotonic()
    queued = dict(payload)
    queued["queued_at"] = float(payload.get("queued_at") or now)
    queued["expires_at"] = float(
        payload.get("expires_at")
        or (queued["queued_at"] + _PENDING_DIALOGUE_TTL_SEC)
    )
    queued["context_identity"] = str(
        payload.get("context_identity")
        or _dialogue_context_identity(payload.get("page_context"))
    )
    with _dialogue_reply_control_lock:
        if dialogue_generation is not None and not _dialogue_reply_generation_is_current(
            sid,
            dialogue_generation,
        ):
            return
        with _pending_dialogue_speak_lock:
            previous = _pending_dialogue_speak.get(sid)
            _pending_dialogue_speak[sid] = queued
    if previous and previous.get("dialogue_request_id") != queued.get(
        "dialogue_request_id"
    ):
        _audit_pending_dialogue_cancelled(sid, previous, "superseded")
    _schedule_pending_dialogue_speak_flush(sid)


def cancel_pending_dialogue_speak(
    session_id: Optional[str],
    *,
    reason: str = "context_changed",
) -> bool:
    sid = str(session_id or "").strip()
    if not sid:
        return False
    with _pending_dialogue_speak_lock:
        pending = _pending_dialogue_speak.pop(sid, None)
        timer = _pending_dialogue_speak_timers.pop(sid, None)
    if timer is not None:
        timer.cancel()
    if not pending:
        return False
    _audit_pending_dialogue_cancelled(sid, pending, reason)
    logger.info(
        "清除过期对话朗读 session=%s reason=%s request=%s",
        sid,
        reason,
        pending.get("dialogue_request_id"),
    )
    return True


def cancel_pending_dialogue_speak_for_context(
    session_id: Optional[str],
    new_context: Optional[Dict[str, Any]],
    *,
    reason: str = "context_changed",
) -> bool:
    """Cancel only when a committed course/question identity has advanced."""
    sid = str(session_id or "").strip()
    if not sid:
        return False
    new_identity = _dialogue_context_identity(new_context)
    with _pending_dialogue_speak_lock:
        pending = dict(_pending_dialogue_speak.get(sid) or {})
    if not pending:
        return False
    old_identity = str(pending.get("context_identity") or "")
    if old_identity and new_identity and old_identity == new_identity:
        return False
    return cancel_pending_dialogue_speak(sid, reason=reason)


def pending_dialogue_speak_queued(session_id: Optional[str]) -> bool:
    sid = str(session_id or "").strip()
    if not sid:
        return False
    expired = None
    with _pending_dialogue_speak_lock:
        pending = _pending_dialogue_speak.get(sid)
        if pending and float(pending.get("expires_at") or 0) <= time.monotonic():
            expired = _pending_dialogue_speak.pop(sid, None)
        queued = sid in _pending_dialogue_speak
    if expired:
        _audit_pending_dialogue_cancelled(sid, expired, "expired")
    return queued


def flush_pending_dialogue_speak(session_id: Optional[str]) -> bool:
    """Replay the latest queued LLM/wake utterance after the mutex frees."""
    sid = str(session_id or "").strip()
    if not sid:
        return False
    with _pending_dialogue_speak_lock:
        pending = _pending_dialogue_speak.pop(sid, None)
    if not pending:
        return False
    if float(pending.get("expires_at") or 0) <= time.monotonic():
        _audit_pending_dialogue_cancelled(sid, pending, "expired")
        return False
    pending_identity = str(pending.get("context_identity") or "")
    if pending_identity:
        try:
            from app.dialogue.page_context_store import get_interactive_page_context

            current_identity = _dialogue_context_identity(
                get_interactive_page_context(sid)
            )
        except Exception:
            current_identity = ""
        if current_identity and current_identity != pending_identity:
            _audit_pending_dialogue_cancelled(sid, pending, "context_changed")
            return False
    spoken = _emit_speak(
        room=pending.get("room"),
        text=str(pending.get("text") or ""),
        intent=str(pending.get("intent") or "dialogue"),
        delay_ms=int(pending.get("delay_ms") or 0),
        source=str(pending.get("source") or "dialogue"),
        session_id=sid,
        dialogue_request_id=pending.get("dialogue_request_id"),
        page_context=pending.get("page_context"),
        dialogue_generation=pending.get("dialogue_generation"),
        _queued_at=float(pending.get("queued_at") or time.monotonic()),
        _expires_at=float(pending.get("expires_at") or time.monotonic()),
    )
    if not spoken and pending_dialogue_speak_queued(sid):
        return False
    return bool(spoken)


def _child_room(session_id: Any) -> Optional[str]:

    if session_id and session_id != "default":

        return f"session_{session_id}_child"

    return None


def _teacher_room(session_id: Any) -> Optional[str]:
    if session_id and session_id != "default":
        return f"session_{session_id}_teacher"
    return None


def _server_room(session_id: Any) -> Optional[str]:
    if session_id and session_id != "default":
        return f"session_{session_id}_server"
    return None






def _try_keyword_auto_praise_from_dialogue(
    *,
    session_id: str,
    text: str,
    page_context: Dict[str, Any],
    stt_provider: Optional[str] = None,
    request_id: Optional[str] = None,
    consume_course_miss: bool = True,
) -> bool:
    """Route a curriculum answer before wake/LLM; return whether consumed."""
    transcript = (text or "").strip()
    if not transcript:
        return False
    try:
        from app.services.keyword_listen import get_keyword_listen_service

        keyword_service = get_keyword_listen_service()
        praised = keyword_service.try_auto_praise_from_transcript(
            str(session_id),
            transcript,
        )
        consume_as_course_answer = False
        if not praised and consume_course_miss:
            consume_check = getattr(
                keyword_service,
                "should_consume_dialogue_turn",
                None,
            )
            if callable(consume_check):
                consume_as_course_answer = bool(consume_check(str(session_id)))
    except Exception as exc:  # noqa: BLE001
        logger.debug("keyword_listen dialogue eval failed: %s", exc)
        return False
    if not praised and not consume_as_course_answer:
        return False

    awake = False
    try:
        awake = bool(
            get_dialogue_service().is_session_awake(session_id, page_context)
        )
    except Exception:
        awake = False

    payload: Dict[str, Any] = {
        "ok": True,
        "awake": awake,
        "transcript": transcript,
        "keywordHit": bool(praised),
        "courseAnswer": True,
        "reply": None,
        "requestId": request_id,
    }
    if stt_provider:
        payload["sttProvider"] = stt_provider
    emit("child_dialogue_result", payload)
    event_name = "dialogue_keyword_hit" if praised else "dialogue_course_answer_miss"
    _audit_dialogue(
        event_name,
        {"sessionId": session_id, "requestId": request_id},
        actor="child",
        source="child_ui",
        phase="completed",
        status="keyword_hit" if praised else "course_answer_miss",
        details={"transcript": transcript, "sttProvider": stt_provider},
    )
    logger.info(
        "课程作答由关键词状态机消费，跳过LLM sid=%s hit=%s text=%s",
        session_id,
        praised,
        transcript[:40],
    )
    return True


def _handle_dialogue_utterance(

    *,

    session_id: str,

    child_text: str,

    page_context: Dict[str, Any],

    room: Optional[str],

    stt_provider: Optional[str] = None,

    request_id: Optional[str] = None,

) -> None:

    """唤醒门控 → LLM。未唤醒时仅接受唤醒词；题目切换后需重新唤醒。"""

    svc = get_dialogue_service()
    request_id = str(request_id or f"dialogue-turn-{uuid.uuid4().hex[:12]}")
    turn_generation = _current_dialogue_reply_generation(session_id)

    # 题目指纹变化时清空历史并退出唤醒

    svc._sync_history_for_context(session_id, page_context)



    transcript = (child_text or "").strip()

    llm_text = transcript
    _record_visible_dialogue_message(
        session_id=session_id,
        role="child",
        text=transcript,
        request_id=request_id,
    )
    _audit_dialogue(
        "dialogue_utterance_received",
        {"sessionId": session_id, "requestId": request_id},
        actor="child",
        source="child_ui",
        phase="received",
        status="accepted",
        details={"transcript": transcript, "sttProvider": stt_provider},
    )

    # 唤醒词优先建立对话状态。未唤醒时，课程关键词状态机继续处理作答；
    # 已唤醒后只有真正的课程关键词命中才截断，普通对话必须继续进入 LLM。
    awake_before_turn = bool(svc.is_session_awake(session_id, page_context))
    wake_candidate = False
    if not awake_before_turn:
        try:
            wake_candidate, _ = parse_wake_utterance(transcript)
        except Exception:
            wake_candidate = False
    if not wake_candidate and _try_keyword_auto_praise_from_dialogue(
        session_id=str(session_id),
        text=transcript,
        page_context=page_context,
        stt_provider=stt_provider,
        request_id=request_id,
        consume_course_miss=not awake_before_turn,
    ):
        return

    if not awake_before_turn:

        from app.config import Config

        if not bool(Config.DIALOGUE_WAKE_WORD_ENABLED):
            _audit_dialogue(
                "dialogue_utterance_rejected",
                {"sessionId": session_id, "requestId": request_id},
                phase="wake_gate",
                status="not_awake",
                details={"wakeWordEnabled": False, "textLength": len(transcript)},
            )
            emit(
                "child_dialogue_result",
                {
                    "ok": False,
                    "error": "not_awake",
                    "awake": False,
                    "transcript": transcript,
                    "hint": "请由教师端点击唤醒智能体",
                    "requestId": request_id,
                },
            )
            return

        matched, remainder = parse_wake_utterance(transcript)

        if not matched:

            logger.info(

                "对话未唤醒，忽略非唤醒语句 sid=%s text=%s",

                session_id,

                transcript[:40],

            )

            emit(

                "child_dialogue_result",

                {

                    "ok": False,

                    "error": "not_awake",

                    "awake": False,

                    "transcript": transcript,

                    "hint": "请说：麦麦",

                    "requestId": request_id,

                },

            )
            return



        wake_activated = _activate_dialogue_wake(
            session_id,
            page_context,
            expected_generation=turn_generation,
            service=svc,
        )
        if not wake_activated:
            emit(
                "child_dialogue_result",
                {
                    "ok": False,
                    "error": "agent_stopped",
                    "awake": False,
                    "transcript": transcript,
                    "reply": None,
                    "requestId": request_id,
                },
            )
            return
        _audit_dialogue(
            "dialogue_wake_word_matched",
            {"sessionId": session_id, "requestId": request_id},
            actor="child",
            source="wake_word",
            phase="applied",
            status="awake",
            details={"remainder": remainder, "soundPlayed": not bool(remainder)},
        )

        logger.info(

            "对话已唤醒 sid=%s remainder=%s",

            session_id,

            (remainder or "")[:40],

        )



        if not remainder:

            _record_visible_dialogue_message(

                session_id=session_id,

                role="maimai",

                text=WAKE_ACK_REPLY,

                request_id=request_id,

            )

            _emit_speak(

                room=room,

                text=WAKE_ACK_REPLY,

                intent="wake_ack",

                delay_ms=0,

                source="dialogue",

                session_id=session_id,

                dialogue_request_id=request_id,

                page_context=page_context,

                dialogue_generation=turn_generation,

            )

            emit(

                "child_dialogue_result",

                {

                    "ok": True,

                    "awake": True,

                    "wake": True,

                    "transcript": transcript,

                    "reply": {

                        "reply": WAKE_ACK_REPLY,

                        "strategy": "wake_ack",

                        "provider": "wake",

                    },

                    "requestId": request_id,

                },

            )

            return



        # 唤醒词 + 后续内容：进入对话模式，仅把后续送 LLM（不再单独念「我在这里」）

        llm_text = remainder

        if _try_keyword_auto_praise_from_dialogue(
            session_id=str(session_id),
            text=remainder,
            page_context=page_context,
            stt_provider=stt_provider,
            request_id=request_id,
            # An explicit wake word means the child is addressing the agent.
            # A curriculum miss must not swallow the remainder before the LLM
            # has a chance to answer it.  A real course hit still wins.
            consume_course_miss=False,
        ):
            return

    reply_generation = turn_generation
    reply_started = time.perf_counter()
    reply = svc.generate_reply(

        llm_text,

        session_id=str(session_id),

        page_context=page_context,

    )
    reply_duration_ms = round((time.perf_counter() - reply_started) * 1000, 3)

    if not _dialogue_reply_generation_is_current(session_id, reply_generation):
        emit(
            "child_dialogue_result",
            {
                "ok": False,
                "error": "agent_stopped",
                "awake": False,
                "transcript": transcript,
                "reply": None,
                "requestId": request_id,
            },
        )
        _audit_dialogue(
            "dialogue_reply_cancelled",
            {"sessionId": session_id, "requestId": request_id},
            phase="cancelled",
            status="agent_stopped",
            modality="audio_text",
            details={"replyDurationMs": reply_duration_ms},
        )
        return

    speech_dispatched = _emit_speak(

        room=room,

        text=reply["reply"],

        intent="dialogue",

        delay_ms=0,

        source="dialogue",

        session_id=session_id,

        dialogue_request_id=request_id,

        page_context=page_context,

        dialogue_generation=reply_generation,

    )

    payload: Dict[str, Any] = {

        "ok": True,

        "awake": True,

        "transcript": transcript,

        "reply": reply,

        "requestId": request_id,

        "speechDelivery": (
            "dispatched"
            if speech_dispatched
            else "queued"
            if pending_dialogue_speak_queued(session_id)
            else "failed"
        ),

    }

    if stt_provider:

        payload["sttProvider"] = stt_provider

    if llm_text != transcript:

        payload["llmText"] = llm_text

        payload["wake"] = True

    _record_visible_dialogue_message(
        session_id=session_id,
        role="maimai",
        text=reply.get("reply", ""),
        request_id=request_id,
    )
    emit("child_dialogue_result", payload)
    _audit_dialogue(
        "dialogue_reply_generated",
        {"sessionId": session_id, "requestId": request_id},
        phase="completed",
        status="ok",
        modality="audio_text",
        details={
            "transcript": transcript,
            "reply": reply.get("reply"),
            "provider": reply.get("provider"),
            "strategy": reply.get("strategy"),
            "sttProvider": stt_provider,
            "replyDurationMs": reply_duration_ms,
        },
    )

    logger.info(

        "对话轮次 sid=%s transcript=%s reply=%s",

        session_id,

        transcript[:40],

        reply.get("reply", "")[:40],

    )





def register_dialogue_events(socketio) -> None:
    global _dialogue_socketio
    _dialogue_socketio = socketio

    @socketio.on("server_dialogue_watch")
    def handle_server_dialogue_watch(data):
        data = data if isinstance(data, dict) else {}
        target = _resolve_dialogue_target(data, allow_standby=True)
        if not target.get("ok"):
            emit("server_dialogue_control_ack", {
                "success": False,
                "action": "watch",
                "error": target.get("error"),
                "requestId": data.get("requestId"),
            })
            return
        session_id = target["sessionId"]
        join_room(_server_room(session_id))
        page_context = merge_page_context({}, session_id)
        runtime = dict(_dialogue_runtime_state.get(session_id) or {})
        with _dialogue_ui_lock:
            messages = [
                dict(item)
                for item in _dialogue_visible_messages.get(session_id, [])
            ]
        emit("server_dialogue_control_ack", {
            "success": True,
            "action": "watch",
            "sessionId": session_id,
            "trainingSessionId": target["trainingSessionId"],
            "standby": bool(target.get("standby")),
            "awake": bool(get_dialogue_service().is_session_awake(session_id, page_context)),
            **runtime,
            "messages": messages,
            "requestId": data.get("requestId"),
        })
        # Runtime state may have been emitted during training_prepare before the
        # child finished joining its exact room.  A watch is therefore an
        # explicit state handshake, not a passive dependency on a past event.
        socketio.emit(
            "child_dialogue_runtime_control",
            {
                "sessionId": session_id,
                "trainingSessionId": target["trainingSessionId"],
                "action": "state_request",
                "requestId": data.get("requestId"),
            },
            room=target["childRoom"],
        )

    @socketio.on("server_dialogue_unwatch")
    def handle_server_dialogue_unwatch(data):
        data = data if isinstance(data, dict) else {}
        session_id = str(data.get("sessionId") or data.get("session_id") or "").strip()
        room = _server_room(session_id)
        if room:
            leave_room(room)
        emit("server_dialogue_control_ack", {
            "success": True,
            "action": "unwatch",
            "sessionId": session_id,
            "requestId": data.get("requestId"),
        })

    @socketio.on("server_dialogue_runtime_control")
    def handle_server_dialogue_runtime_control(data):
        data = data if isinstance(data, dict) else {}
        request_id = str(data.get("requestId") or f"server-dialogue-{uuid.uuid4().hex[:12]}")
        target = _resolve_dialogue_target(data, allow_standby=True)
        action = str(data.get("action") or "").strip().lower()
        if action not in {"listen_start", "listen_stop", "unlock_audio", "set_voice"}:
            emit("server_dialogue_control_ack", {
                "success": False,
                "action": action,
                "error": "unsupported_action",
                "requestId": request_id,
            })
            return
        if not target.get("ok"):
            emit("server_dialogue_control_ack", {
                "success": False,
                "action": action,
                "error": target.get("error"),
                "requestId": request_id,
            })
            return
        voice_name = str(data.get("voiceName") or "").strip()[:200]
        if action == "set_voice" and not voice_name:
            emit("server_dialogue_control_ack", {
                "success": False,
                "action": action,
                "error": "voice_name_missing",
                "requestId": request_id,
            })
            return
        if action == "set_voice" and not is_fixed_browser_tts_voice_name(voice_name):
            emit("server_dialogue_control_ack", {
                "success": False,
                "action": action,
                "error": "voice_locked",
                "fixedVoiceName": FIXED_BROWSER_TTS_VOICE_NAME,
                "requestId": request_id,
            })
            return
        payload = {
            "sessionId": target["sessionId"],
            "trainingSessionId": target["trainingSessionId"],
            "action": action,
            "requestId": request_id,
        }
        if action == "set_voice":
            payload["voiceName"] = FIXED_BROWSER_TTS_VOICE_NAME
        socketio.emit(
            "child_dialogue_runtime_control",
            payload,
            room=target["childRoom"],
        )
        emit("server_dialogue_control_ack", {"success": True, **payload})

    @socketio.on("server_dialogue_text")
    def handle_server_dialogue_text(data):
        data = data if isinstance(data, dict) else {}
        request_id = str(data.get("requestId") or f"server-dialogue-turn-{uuid.uuid4().hex[:12]}")
        target = _resolve_dialogue_target(data, allow_standby=True)
        if not target.get("ok"):
            emit("server_dialogue_control_ack", {
                "success": False,
                "action": "text",
                "error": target.get("error"),
                "requestId": request_id,
            })
            return
        text_value = str(data.get("text") or "").strip()
        if not text_value or len(text_value) > 2000:
            emit("server_dialogue_control_ack", {
                "success": False,
                "action": "text",
                "error": "empty_text" if not text_value else "text_too_long",
                "requestId": request_id,
            })
            return
        session_id = target["sessionId"]
        page_context = merge_page_context({}, session_id)
        get_dialogue_service().bind_pending_awake_context(session_id, page_context)
        try:
            _handle_dialogue_utterance(
                session_id=session_id,
                child_text=text_value,
                page_context=page_context,
                room=target["childRoom"],
                stt_provider="server-text",
                request_id=request_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Server 对话文字处理失败: %s", exc, exc_info=True)
            emit("server_dialogue_control_ack", {
                "success": False,
                "action": "text",
                "error": str(exc),
                "requestId": request_id,
            })
            return
        emit("server_dialogue_control_ack", {
            "success": True,
            "action": "text",
            "sessionId": session_id,
            "trainingSessionId": target["trainingSessionId"],
            "requestId": request_id,
        })

    @socketio.on("teacher_dialogue_wake")
    def handle_teacher_dialogue_wake(data):
        data = data or {}
        request_id = str(
            data.get("requestId") or data.get("request_id") or f"manual-wake-{uuid.uuid4().hex[:12]}"
        )
        target = _resolve_dialogue_target(data, allow_standby=True)
        if not target.get("ok"):
            emit("teacher_dialogue_control_ack", {
                "success": False,
                "action": "wake",
                "error": target.get("error"),
                "requestId": request_id,
            })
            return
        session_id = target["sessionId"]
        # 教师端的 questionId 可能仍是课点占位值；交互 iframe 生成首题后，
        # 由儿童端的 committed pageContext 完成绑定，避免首句话被误判为换题。
        _activate_dialogue_wake(
            session_id,
            defer_context_binding=True,
        )
        payload = {
            "success": True,
            "action": "wake",
            "awake": True,
            "silent": True,
            "speechDelivery": "suppressed",
            "sessionId": session_id,
            "trainingSessionId": target["trainingSessionId"],
            "reason": "teacher_manual",
            "requestId": request_id,
        }
        emit("child_dialogue_wake_state", payload, room=target["childRoom"], include_self=False)
        emit("teacher_dialogue_control_ack", payload)
        _audit_dialogue(
            "dialogue_manual_wake",
            payload,
            actor="teacher_ui",
            source="teacher_ui",
            phase="applied",
            status="awake",
            details={
                "soundPlayed": False,
                "soundQueued": False,
                "silentManualWake": True,
                "contextBinding": "child_committed",
            },
        )

    @socketio.on("teacher_dialogue_sleep")
    def handle_teacher_dialogue_sleep(data):
        data = data or {}
        request_id = str(
            data.get("requestId") or data.get("request_id") or f"manual-sleep-{uuid.uuid4().hex[:12]}"
        )
        target = _resolve_dialogue_target(data, allow_standby=True)
        if not target.get("ok"):
            emit("teacher_dialogue_control_ack", {
                "success": False,
                "action": "sleep",
                "error": target.get("error"),
                "requestId": request_id,
            })
            return
        session_id = target["sessionId"]
        get_dialogue_service().clear_awake(session_id)
        cancelled = _cancel_dialogue_replies(
            session_id,
            reason="teacher_manual_stop",
        )
        payload = {
            "success": True,
            "action": "sleep",
            "awake": False,
            "listeningPreserved": True,
            "replyCancelled": bool(
                cancelled["pendingCancelled"] or cancelled["activeCancelled"]
            ),
            "sessionId": session_id,
            "trainingSessionId": target["trainingSessionId"],
            "reason": "teacher_manual",
            "requestId": request_id,
        }
        emit("child_dialogue_wake_state", payload, room=target["childRoom"], include_self=False)
        emit("teacher_dialogue_control_ack", payload)
        _audit_dialogue(
            "dialogue_manual_sleep",
            payload,
            actor="teacher_ui",
            source="teacher_ui",
            phase="applied",
            status="asleep",
            details={
                "listeningPreserved": True,
                "pendingReplyCancelled": cancelled["pendingCancelled"],
                "activeReplyCancelled": cancelled["activeCancelled"],
            },
        )

    @socketio.on("teacher_dialogue_visibility")
    def handle_teacher_dialogue_visibility(data):
        data = data or {}
        request_id = str(
            data.get("requestId") or data.get("request_id") or f"dialogue-visibility-{uuid.uuid4().hex[:12]}"
        )
        target = _resolve_manual_wake_target(data)
        if not target.get("ok"):
            emit("teacher_dialogue_control_ack", {
                "success": False,
                "action": "visibility",
                "error": target.get("error"),
                "requestId": request_id,
            })
            return
        session_id = target["sessionId"]
        visible = bool(data.get("visible"))
        with _dialogue_ui_lock:
            _dialogue_ui_visible[session_id] = visible
        payload = {
            "success": True,
            "action": "visibility",
            "visible": visible,
            "sessionId": session_id,
            "trainingSessionId": target["trainingSessionId"],
            "requestId": request_id,
        }
        emit("child_dialogue_visibility", payload, room=_child_room(session_id), include_self=False)
        emit("teacher_dialogue_control_ack", payload)
        _audit_dialogue(
            "dialogue_panel_visibility",
            payload,
            actor="teacher_ui",
            source="teacher_ui",
            phase="applied",
            status="visible" if visible else "hidden",
            modality="child_screen",
            details={"visible": visible},
        )

    @socketio.on("child_dialogue_control_state_request")
    def handle_child_dialogue_control_state_request(data):
        data = data or {}
        session_id = str(data.get("sessionId") or data.get("session_id") or "").strip()
        with _dialogue_ui_lock:
            visible = _dialogue_ui_visible.get(session_id, True)
        from app.config import Config
        raw_context = data.get("pageContext") or data.get("page_context") or {}
        page_context = merge_page_context(
            raw_context if isinstance(raw_context, dict) else {},
            session_id,
        )
        awake = bool(get_dialogue_service().is_session_awake(session_id, page_context))
        emit("child_dialogue_control_state", {
            "success": True,
            "sessionId": session_id,
            "visible": visible,
            "awake": awake,
            "wakeWordEnabled": bool(Config.DIALOGUE_WAKE_WORD_ENABLED),
        })

    @socketio.on("teacher_dialogue_state_request")
    def handle_teacher_dialogue_state_request(data):
        data = data or {}
        target = _resolve_manual_wake_target(data)
        if not target.get("ok"):
            emit("teacher_dialogue_control_state", {
                "success": False,
                "error": target.get("error"),
                "sessionId": data.get("sessionId") or data.get("session_id"),
            })
            return
        session_id = target["sessionId"]
        raw_context = data.get("pageContext") or data.get("page_context") or {}
        page_context = merge_page_context(
            raw_context if isinstance(raw_context, dict) else {},
            session_id,
        )
        with _dialogue_ui_lock:
            visible = _dialogue_ui_visible.get(session_id, True)
        emit("teacher_dialogue_control_state", {
            "success": True,
            "sessionId": session_id,
            "trainingSessionId": target["trainingSessionId"],
            "awake": bool(get_dialogue_service().is_session_awake(session_id, page_context)),
            "visible": visible,
        })

    @socketio.on("child_dialogue_runtime_state")
    def handle_child_dialogue_runtime_state(data):
        data = data or {}
        session_id = str(data.get("sessionId") or data.get("session_id") or "").strip()
        if not session_id:
            return
        try:
            from app.sockets.events import get_connected_child_sid

            if get_connected_child_sid(session_id) != request.sid:
                logger.warning("忽略非当前儿童端的对话状态: session=%s sid=%s", session_id, request.sid)
                return
        except Exception:
            return
        raw_context = data.get("pageContext") or data.get("page_context") or {}
        if isinstance(raw_context, dict):
            page_context = merge_page_context(raw_context, session_id)
            get_dialogue_service().bind_pending_awake_context(session_id, page_context)
        voice_state = project_fixed_browser_tts_runtime_state(data)
        payload = {
            "success": True,
            "sessionId": session_id,
            "requestId": data.get("requestId") or data.get("request_id"),
            "awake": bool(data.get("awake")),
            "listening": bool(data.get("listening")),
            "recognitionActive": bool(data.get("recognitionActive")),
            "microphoneBlocked": bool(data.get("microphoneBlocked")),
            "reason": data.get("reason"),
            **voice_state,
        }
        _dialogue_runtime_state[session_id] = dict(payload)
        emit("teacher_dialogue_runtime_state", payload, room=_teacher_room(session_id))
        emit("server_dialogue_event", {"type": "runtime", **payload}, room=_server_room(session_id))

    @socketio.on("child_dialogue_text")

    def handle_child_dialogue_text(data):

        """儿童端已识别文本（或调试文本）→ 唤醒门控 → LLM → 浏览器朗读。"""

        try:

            data = data or {}

            session_id = str(
                data.get("sessionId") or data.get("session_id") or ""
            ).strip()

            try:
                from app.sockets.events import get_connected_child_sid

                exact_child_sid = get_connected_child_sid(session_id)
            except Exception:
                exact_child_sid = None
            if not session_id or exact_child_sid != request.sid:
                logger.warning(
                    "拒绝未绑定精确会话的儿童对话文本 session=%s sid=%s",
                    session_id,
                    request.sid,
                )
                emit("child_dialogue_result", {
                    "ok": False,
                    "error": "child_session_not_bound",
                    "requestId": data.get("requestId") or data.get("request_id"),
                })
                return

            child_text = (data.get("text") or "").strip()

            recognition_provider = str(
                data.get("recognitionProvider")
                or data.get("recognition_provider")
                or ""
            ).strip()[:80] or None

            dialogue_request_id = str(
                data.get("requestId")
                or data.get("request_id")
                or f"dialogue-turn-{uuid.uuid4().hex[:12]}"
            )

            raw_ctx = data.get("pageContext") or data.get("page_context") or {}

            page_context = merge_page_context(

                raw_ctx if isinstance(raw_ctx, dict) else {},

                session_id,

            )

            # runtime_state 可能因网络时序晚到；首条儿童转写同样是可信的
            # committed 上下文，可在进入唤醒门控前完成绑定。
            get_dialogue_service().bind_pending_awake_context(
                session_id,
                page_context,
            )

            room = _child_room(session_id)



            if not child_text:

                emit("child_dialogue_result", {
                    "ok": False,
                    "error": "empty_text",
                    "requestId": dialogue_request_id,
                })

                return

            duplicate_reason = _claim_dialogue_turn(
                session_id,
                dialogue_request_id,
                child_text,
                page_context,
                recognition_provider=recognition_provider,
            )
            if duplicate_reason:
                logger.info(
                    "忽略重复对话轮次 sid=%s request=%s reason=%s text=%s",
                    session_id,
                    dialogue_request_id,
                    duplicate_reason,
                    child_text[:40],
                )
                emit("child_dialogue_result", {
                    "ok": False,
                    "error": "duplicate_utterance",
                    "reason": duplicate_reason,
                    "transcript": child_text,
                    "requestId": dialogue_request_id,
                })
                return

            _audit_dialogue(
                "dialogue.text_received",
                {"sessionId": session_id, "requestId": dialogue_request_id},
                actor="child",
                source="child_ui",
                phase="received",
                status="accepted",
                client_timestamp=(data.get("clientTiming") or {}).get("sentAtClientMs"),
                details={
                    "clientTiming": data.get("clientTiming") or {},
                    "recognitionProvider": recognition_provider,
                },
            )



            logger.info(

                "对话页上下文 sid=%s course=%s prompt=%s target=%s options=%s wrong=%s",

                session_id,

                page_context.get("courseType"),

                (page_context.get("prompt") or "")[:40],

                (page_context.get("target") or "")[:40],

                len(page_context.get("options") or []),

                page_context.get("wrongAttempts"),

            )

            _handle_dialogue_utterance(

                session_id=session_id,

                child_text=child_text,

                page_context=page_context,

                room=room,

                stt_provider=recognition_provider,

                request_id=dialogue_request_id,

            )

        except Exception as exc:  # noqa: BLE001

            logger.error("child_dialogue_text 失败: %s", exc, exc_info=True)

            emit("child_dialogue_result", {"ok": False, "error": str(exc)})



    @socketio.on("child_dialogue_audio")
    def handle_child_dialogue_audio(data):
        """兼容旧儿童端；生产识别已统一为浏览器返回文本。"""
        payload = data if isinstance(data, dict) else {}
        request_id = str(
            payload.get("requestId")
            or payload.get("request_id")
            or f"dialogue-turn-{uuid.uuid4().hex[:12]}"
        )
        logger.info("拒绝旧音频识别请求 request=%s：请使用浏览器语音识别", request_id)
        emit("child_dialogue_result", {
            "ok": False,
            "error": "browser_speech_required",
            "stage": "stt",
            "requestId": request_id,
        })

    @socketio.on("dialogue_latency_event")
    def handle_dialogue_latency_event(data):
        """Persist child-side result/TTS milestones without trusting its clock."""
        payload = data if isinstance(data, dict) else {}
        phase = str(payload.get("phase") or "").strip().lower()
        if phase not in {
            "result_received", "tts_command_received", "tts_started", "tts_ended"
        }:
            return
        session_id = payload.get("sessionId") or payload.get("session_id")
        request_id = payload.get("requestId") or payload.get("request_id")
        if not session_id or not request_id:
            return
        _audit_dialogue(
            f"dialogue.client_{phase}",
            {"sessionId": session_id, "requestId": request_id},
            actor="child",
            source="child_ui",
            phase=phase,
            status=str(payload.get("status") or "observed"),
            modality="audio" if phase.startswith("tts_") else None,
            client_timestamp=payload.get("clientTimestamp"),
            details={
                "commandReceivedAtClientMs": payload.get("commandReceivedAtClientMs"),
                "actualAtClientMs": payload.get("actualAtClientMs"),
                "clientStageMs": payload.get("clientStageMs"),
                "provider": payload.get("provider"),
                "reason": payload.get("reason"),
            },
        )



    @socketio.on("child_dialogue_sleep")

    def handle_child_dialogue_sleep(data):

        """手动退出唤醒（或前端检测到题目指纹变化时同步）。"""

        try:

            data = data or {}

            session_id = str(
                data.get("sessionId") or data.get("session_id") or ""
            ).strip()

            try:
                from app.sockets.events import get_connected_child_sid

                exact_child_sid = get_connected_child_sid(session_id)
            except Exception:
                exact_child_sid = None
            if not session_id or exact_child_sid != request.sid:
                return

            get_dialogue_service().clear_awake(session_id)
            _cancel_dialogue_replies(
                session_id,
                reason=str(data.get("reason") or "child_sleep"),
            )

            emit(

                "child_dialogue_wake_state",

                {

                    "awake": False,

                    "sessionId": session_id,

                    "reason": data.get("reason") or "manual_sleep",

                },

            )
            emit(
                "teacher_dialogue_runtime_state",
                {
                    "success": True,
                    "sessionId": session_id,
                    "awake": False,
                    "listening": True,
                    "reason": data.get("reason") or "manual_sleep",
                },
                room=_teacher_room(session_id),
            )

            logger.info(

                "对话手动休眠 sid=%s reason=%s",

                session_id,

                data.get("reason") or "manual_sleep",

            )
            _audit_dialogue(
                "dialogue_sleep",
                data,
                actor="child",
                source="child_ui",
                phase="applied",
                status="asleep",
                details={"reason": data.get("reason") or "manual_sleep"},
            )

        except Exception as exc:  # noqa: BLE001

            logger.error("child_dialogue_sleep 失败: %s", exc, exc_info=True)

            emit("child_dialogue_result", {"ok": False, "error": str(exc)})



    @socketio.on("request_question_speak")

    def handle_request_question_speak(data):

        """调试/补发：按课型朗读提问句；排序须带 category+rule / variant。"""

        data = data or {}

        course_type = data.get("courseType") or data.get("course_type")

        session_id = data.get("sessionId") or data.get("session_id")

        category = data.get("category")

        rule = data.get("rule")

        variant = data.get("variant")

        room = _child_room(session_id)

        ct = str(course_type or "").strip().lower()

        if ct in ("ordering", "sequencing"):

            from app.dialogue.phrases import ordering_phrase_key



            variant = variant or ordering_phrase_key(category, rule)

            if not variant:

                # 禁止裸 ordering →「按规则选一选」/旧兜底

                logger.info(

                    "request_question_speak 忽略 ordering（缺 category/rule） sid=%s",

                    session_id,

                )

                return

        item_name = None

        if ct == "onomatopoeia":

            from app.dialogue.phrases import resolve_item_display_name

            from app.dialogue.page_context_store import get_interactive_page_context



            item_name = resolve_item_display_name(

                data,

                get_interactive_page_context(session_id),

            )

        text = pick_phrase("question", course_type, variant=variant, name=item_name)

        speech_dispatched = _emit_speak(
            room=room,
            text=text,
            intent="question",
            source="manual",
            session_id=session_id,
            page_context=merge_page_context(session_id),
        )
        if speech_dispatched:
            record_visible_dialogue_message(
                session_id=str(session_id),
                role="maimai",
                text=text,
                request_id=data.get("requestId") or data.get("request_id"),
            )



    logger.info("对话 Socket 事件已注册")


