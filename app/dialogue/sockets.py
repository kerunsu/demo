"""对话相关 Socket 事件：语音轮次 / 文本轮次。"""



from __future__ import annotations



from typing import Any, Dict, Optional
import threading
import time

import uuid



from flask import request, session as flask_session
from flask_socketio import emit



from app.dialogue.page_context_store import merge_page_context

from app.dialogue.phrases import pick_phrase

from app.dialogue.service import (

    WAKE_ACK_REPLY,

    get_dialogue_service,

    parse_wake_utterance,

)

from app.dialogue.stt import transcribe_audio_base64

from app.utils.logger import setup_logger



logger = setup_logger("dialogue.sockets")

_dialogue_ui_lock = threading.RLock()
_dialogue_ui_visible: Dict[str, bool] = {}
_pending_dialogue_speak_lock = threading.RLock()
_pending_dialogue_speak: Dict[str, Dict[str, Any]] = {}


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





def _emit_speak(

    *,

    room: Optional[str],

    text: str,

    intent: str,

    delay_ms: int = 0,

    source: str = "dialogue",

    session_id: Optional[str] = None,

    dialogue_request_id: Optional[str] = None,

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

    behavior_id = f"dialogue-{uuid.uuid4().hex[:12]}"
    request_id = f"dialogue-request-{uuid.uuid4().hex[:12]}"
    try:
        from app.robot import get_robot_service

        robot_service = get_robot_service()
        expression_match = None
        if intent == "dialogue" and source == "dialogue":
            selector = getattr(robot_service, "select_dialogue_reply_emotion", None)
            if callable(selector):
                expression_match = selector(spoken)
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
                },
            )
            return False
        behavior_id = str(reservation.get("behaviorId") or behavior_id)
        behavior_result = None
        if expression_match:
            starter = getattr(robot_service, "start_dialogue_reply_behavior", None)
            if callable(starter):
                behavior_result = starter(
                    emotion=expression_match["emotion"],
                    behavior_id=behavior_id,
                    request_id=request_id,
                    session_id=resolved_session_id,
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

    }
    if expression_match:
        payload["expression"] = expression_match["emotion"]
        payload["expressionMatch"] = dict(expression_match)

    timeout_ms = min(
        30000,
        max(
            5000,
            len(spoken) * 360 + int(payload["delayMs"]) + 1500,
        ),
    )
    try:
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
        # Exactly one room-scoped delivery.  Direct+broadcast duplicates could
        # cancel/restart speech and leaked dialogue to unrelated children.
        try:
            emit("robot_speak_text", payload, room=room, include_self=True)
        except Exception:
            from app.services.keyword_listen import KeywordListenService

            sio = KeywordListenService._resolve_socketio()
            if sio is None:
                raise
            sio.emit("robot_speak_text", payload, room=room)
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


def _queue_pending_dialogue_speak(session_id: str, payload: Dict[str, Any]) -> None:
    sid = str(session_id or "").strip()
    if not sid or not (payload.get("text") or "").strip():
        return
    with _pending_dialogue_speak_lock:
        _pending_dialogue_speak[sid] = dict(payload)


def pending_dialogue_speak_queued(session_id: Optional[str]) -> bool:
    sid = str(session_id or "").strip()
    if not sid:
        return False
    with _pending_dialogue_speak_lock:
        return sid in _pending_dialogue_speak


def flush_pending_dialogue_speak(session_id: Optional[str]) -> bool:
    """Replay the latest queued LLM/wake utterance after the mutex frees."""
    sid = str(session_id or "").strip()
    if not sid:
        return False
    with _pending_dialogue_speak_lock:
        pending = _pending_dialogue_speak.pop(sid, None)
    if not pending:
        return False
    spoken = _emit_speak(
        room=pending.get("room"),
        text=str(pending.get("text") or ""),
        intent=str(pending.get("intent") or "dialogue"),
        delay_ms=int(pending.get("delay_ms") or 0),
        source=str(pending.get("source") or "dialogue"),
        session_id=sid,
    )
    if not spoken and pending_dialogue_speak_queued(sid):
        return False
    return bool(spoken)


def _child_room(session_id: Any) -> Optional[str]:

    if session_id and session_id != "default":

        return f"session_{session_id}_child"

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

    # 题目指纹变化时清空历史并退出唤醒

    svc._sync_history_for_context(session_id, page_context)



    transcript = (child_text or "").strip()

    llm_text = transcript
    _audit_dialogue(
        "dialogue_utterance_received",
        {"sessionId": session_id, "requestId": request_id},
        actor="child",
        source="child_ui",
        phase="received",
        status="accepted",
        details={"transcript": transcript, "sttProvider": stt_provider},
    )

    # 唤醒词优先建立对话状态；其余命名/拟声作答全部由课程状态机消费。
    wake_candidate = False
    if not svc.is_session_awake(session_id, page_context):
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
    ):
        return

    if not svc.is_session_awake(session_id, page_context):

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

                    "hint": "请说：麦麦，麦麦",

                    "requestId": request_id,

                },

            )

            return



        svc.set_awake(session_id, page_context)
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

            _emit_speak(

                room=room,

                text=WAKE_ACK_REPLY,

                intent="wake_ack",

                delay_ms=0,

                source="dialogue",

                session_id=session_id,

                dialogue_request_id=request_id,

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

    reply_started = time.perf_counter()
    reply = svc.generate_reply(

        llm_text,

        session_id=str(session_id),

        page_context=page_context,

    )
    reply_duration_ms = round((time.perf_counter() - reply_started) * 1000, 3)

    _emit_speak(

        room=room,

        text=reply["reply"],

        intent="dialogue",

        delay_ms=0,

        source="dialogue",

        session_id=session_id,

        dialogue_request_id=request_id,

    )

    payload: Dict[str, Any] = {

        "ok": True,

        "awake": True,

        "transcript": transcript,

        "reply": reply,

        "requestId": request_id,

    }

    if stt_provider:

        payload["sttProvider"] = stt_provider

    if llm_text != transcript:

        payload["llmText"] = llm_text

        payload["wake"] = True

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

    @socketio.on("teacher_dialogue_wake")
    def handle_teacher_dialogue_wake(data):
        data = data or {}
        access = _authorize_teacher_control(data)
        if not access.get("ok"):
            emit("teacher_dialogue_control_ack", {
                "success": False, "action": "wake", "error": access.get("error")
            })
            return
        session_id = str(data.get("sessionId") or data.get("session_id") or "").strip()
        if not session_id:
            emit("teacher_dialogue_control_ack", {
                "success": False, "action": "wake", "error": "session_id_missing"
            })
            return
        page_context = merge_page_context({}, session_id)
        get_dialogue_service().set_awake(session_id, page_context)
        payload = {
            "success": True,
            "action": "wake",
            "awake": True,
            "sessionId": session_id,
            "trainingSessionId": access["trainingSessionId"],
            "reason": "teacher_manual",
        }
        emit("child_dialogue_wake_state", payload, room=_child_room(session_id), include_self=False)
        emit("teacher_dialogue_control_ack", payload)
        _audit_dialogue(
            "dialogue_manual_wake",
            payload,
            actor=f"teacher:{access['teacherId']}",
            source="teacher_ui",
            phase="applied",
            status="awake",
            details={"soundPlayed": False},
        )

    @socketio.on("teacher_dialogue_visibility")
    def handle_teacher_dialogue_visibility(data):
        data = data or {}
        access = _authorize_teacher_control(data)
        if not access.get("ok"):
            emit("teacher_dialogue_control_ack", {
                "success": False, "action": "visibility", "error": access.get("error")
            })
            return
        session_id = str(data.get("sessionId") or data.get("session_id") or "").strip()
        if not session_id:
            emit("teacher_dialogue_control_ack", {
                "success": False, "action": "visibility", "error": "session_id_missing"
            })
            return
        visible = bool(data.get("visible"))
        with _dialogue_ui_lock:
            _dialogue_ui_visible[session_id] = visible
        payload = {
            "success": True,
            "action": "visibility",
            "visible": visible,
            "sessionId": session_id,
            "trainingSessionId": access["trainingSessionId"],
        }
        emit("child_dialogue_visibility", payload, room=_child_room(session_id), include_self=False)
        emit("teacher_dialogue_control_ack", payload)
        _audit_dialogue(
            "dialogue_panel_visibility",
            payload,
            actor=f"teacher:{access['teacherId']}",
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
        emit("child_dialogue_control_state", {
            "success": True,
            "sessionId": session_id,
            "visible": visible,
            "wakeWordEnabled": bool(Config.DIALOGUE_WAKE_WORD_ENABLED),
        })

    @socketio.on("child_dialogue_text")

    def handle_child_dialogue_text(data):

        """儿童端已识别文本（或调试文本）→ 唤醒门控 → LLM → 浏览器朗读。"""

        try:

            data = data or {}

            session_id = data.get("sessionId") or data.get("session_id") or "default"

            child_text = (data.get("text") or "").strip()

            dialogue_request_id = str(
                data.get("requestId")
                or data.get("request_id")
                or f"dialogue-turn-{uuid.uuid4().hex[:12]}"
            )

            raw_ctx = data.get("pageContext") or data.get("page_context") or {}

            page_context = merge_page_context(

                raw_ctx if isinstance(raw_ctx, dict) else {},

                str(session_id) if session_id else None,

            )

            room = _child_room(session_id)



            if not child_text:

                emit("child_dialogue_result", {
                    "ok": False,
                    "error": "empty_text",
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
                details={"clientTiming": data.get("clientTiming") or {}},
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

                session_id=str(session_id),

                child_text=child_text,

                page_context=page_context,

                room=room,

                request_id=dialogue_request_id,

            )

        except Exception as exc:  # noqa: BLE001

            logger.error("child_dialogue_text 失败: %s", exc, exc_info=True)

            emit("child_dialogue_result", {"ok": False, "error": str(exc)})



    @socketio.on("child_dialogue_audio")

    def handle_child_dialogue_audio(data):

        """浏览器麦克风采集 → FunASR → 唤醒门控 → LLM → 浏览器 TTS。"""

        try:

            data = data or {}

            session_id = data.get("sessionId") or data.get("session_id") or "default"

            audio_b64 = data.get("audioBase64") or data.get("audio_base64") or ""

            mime_type = data.get("mimeType") or data.get("mime_type") or "audio/webm"

            dialogue_request_id = str(
                data.get("requestId")
                or data.get("request_id")
                or f"dialogue-turn-{uuid.uuid4().hex[:12]}"
            )

            client_timing = (
                data.get("clientTiming")
                if isinstance(data.get("clientTiming"), dict)
                else {}
            )

            raw_ctx = data.get("pageContext") or data.get("page_context") or {}

            page_context = merge_page_context(

                raw_ctx if isinstance(raw_ctx, dict) else {},

                str(session_id) if session_id else None,

            )

            room = _child_room(session_id)



            _audit_dialogue(
                "dialogue.audio_received",
                {"sessionId": session_id, "requestId": dialogue_request_id},
                actor="child",
                source="child_ui",
                phase="received",
                status="accepted",
                client_timestamp=client_timing.get("sentAtClientMs"),
                details={
                    "mimeType": mime_type,
                    "base64Chars": len(str(audio_b64 or "")),
                    "clientTiming": client_timing,
                },
            )

            stt_started = time.perf_counter()
            stt = transcribe_audio_base64(audio_b64, mime_type=mime_type)
            stt_duration_ms = round((time.perf_counter() - stt_started) * 1000, 3)

            _audit_dialogue(
                "dialogue.stt_completed",
                {"sessionId": session_id, "requestId": dialogue_request_id},
                phase="completed",
                status="ok" if stt.get("ok") else "failed",
                degraded=not bool(stt.get("ok")),
                error=stt.get("error") if not stt.get("ok") else None,
                details={
                    "durationMs": stt_duration_ms,
                    "provider": stt.get("provider"),
                    "timing": stt.get("timing") or {},
                    "transcriptLength": len(str(stt.get("transcript") or "")),
                },
            )

            if not stt.get("ok"):

                emit(

                    "child_dialogue_result",

                    {

                        "ok": False,

                        "error": stt.get("error") or "stt_failed",

                        "stage": "stt",
                        "requestId": dialogue_request_id,

                    },

                )

                return



            transcript = stt["transcript"]

            logger.info(

                "对话页上下文(audio) sid=%s course=%s prompt=%s target=%s options=%s wrong=%s",

                session_id,

                page_context.get("courseType"),

                (page_context.get("prompt") or "")[:40],

                (page_context.get("target") or "")[:40],

                len(page_context.get("options") or []),

                page_context.get("wrongAttempts"),

            )

            _handle_dialogue_utterance(

                session_id=str(session_id),

                child_text=transcript,

                page_context=page_context,

                room=room,

                stt_provider=stt.get("provider"),

                request_id=dialogue_request_id,

            )

        except Exception as exc:  # noqa: BLE001

            logger.error("child_dialogue_audio 失败: %s", exc, exc_info=True)

            emit("child_dialogue_result", {"ok": False, "error": str(exc)})


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

            session_id = data.get("sessionId") or data.get("session_id") or "default"

            get_dialogue_service().clear_awake(str(session_id))

            emit(

                "child_dialogue_wake_state",

                {

                    "awake": False,

                    "sessionId": session_id,

                    "reason": data.get("reason") or "manual_sleep",

                },

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

        _emit_speak(
            room=room,
            text=text,
            intent="question",
            source="manual",
            session_id=session_id,
        )



    logger.info("对话 Socket 事件已注册")


