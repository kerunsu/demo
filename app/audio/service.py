"""
语音播放服务
处理 play_resource 事件中的语音触发逻辑
"""
import time
from typing import Dict, Any, Optional
from app.utils.logger import setup_logger
from .events import get_audio_emitter

logger = setup_logger('audio_service')


class AudioService:
    """
    语音播放服务

    负责处理 play_resource 事件中的语音播放需求，
    根据 aux 参数和课程类型决定播放什么语音。
    DIALOGUE_TTS_MODE=browser 时改为下发 robot_speak_text（浏览器朗读），关掉预录。
    """

    def __init__(self):
        self._emitter = None

    @property
    def emitter(self):
        if self._emitter is None:
            self._emitter = get_audio_emitter()
        return self._emitter

    @staticmethod
    def _tts_mode() -> str:
        # Product mode is browser TTS only. Legacy file fields remain readable
        # for database compatibility, but course playback never selects them.
        return "browser"

    @staticmethod
    def _room_has_participants(
        socketio,
        room: Optional[str],
    ) -> Optional[bool]:
        """Return room occupancy, or None when the manager cannot inspect it."""
        if not room:
            return False
        try:
            participants = socketio.server.manager.get_participants("/", room)
            return next(iter(participants), None) is not None
        except Exception:
            return None

    def _emit_browser_phrase(
        self,
        *,
        room: Optional[str],
        intent: str,
        course_type: Optional[str],
        delay_ms: int,
        session_id: Optional[str],
        variant: Optional[str] = None,
        text: Optional[str] = None,
        name: Optional[str] = None,
        behavior_id: Optional[str] = None,
        request_id: Optional[str] = None,
        question_id: Optional[str] = None,
    ) -> bool:
        try:
            from app.dialogue.phrases import pick_phrase

            spoken = (text or "").strip()
            if not spoken:
                spoken = pick_phrase(
                    intent,
                    course_type,
                    variant=variant,
                    name=name,
                    recent_key=f"{session_id}:{intent}:{variant or course_type or ''}",
                )
            if not self.emitter or not getattr(self.emitter, "socketio", None):
                logger.warning("[AudioService] emitter 未就绪，无法发送 robot_speak_text")
                return False
            payload = {
                "text": spoken,
                "intent": intent,
                "courseType": course_type,
                "variant": variant,
                "delayMs": max(0, int(delay_ms or 0)),
                "source": "aux",
                "ttsMode": "browser",
                "sessionId": session_id,
                "protocolVersion": "1",
                "modality": "speech",
                "startAtServerMs": int(time.time() * 1000) + max(0, int(delay_ms or 0)),
            }
            if behavior_id:
                payload["behaviorId"] = str(behavior_id)
                payload["behavior_id"] = str(behavior_id)
                payload["interactionId"] = str(behavior_id)
            if request_id:
                payload["requestId"] = str(request_id)
                payload["request_id"] = str(request_id)
            if question_id:
                payload["questionId"] = str(question_id)
                payload["question_id"] = str(question_id)
            # Never turn a missing/empty session room into a global broadcast:
            # another child must not receive or acknowledge this utterance.
            if not room:
                logger.warning(
                    "[AudioService] robot_speak_text 缺少目标儿童房间，拒绝下发"
                )
                return False
            if self._room_has_participants(
                self.emitter.socketio,
                room,
            ) is False:
                logger.warning(
                    "[AudioService] %s 暂无儿童成员，拒绝下发 robot_speak_text",
                    room,
                )
                return False
            self.emitter.socketio.emit("robot_speak_text", payload, room=room)
            logger.info(
                "[AudioService] robot_speak_text intent=%s course=%s variant=%s text=%s room=%s",
                intent,
                course_type,
                variant,
                spoken,
                room,
            )
            # browser TTS 播放期间暂停连续 ASR 匹配，避免回采误表扬
            intent_l = str(intent or "").strip().lower()
            gate_entry = {
                "question": "question",
                "praise": "praise",
                "hint": "hint",
                "encourage": "praise",
            }.get(intent_l)
            if session_id and gate_entry:
                try:
                    from app.services import get_analysis_service

                    get_analysis_service().update_system_audio_state(
                        str(session_id),
                        gate_entry,
                        "playing",
                    )
                except Exception as gate_error:  # noqa: BLE001
                    logger.debug(
                        "[AudioService] browser TTS ASR 门控开始失败: %s",
                        gate_error,
                    )
                if intent_l in ("praise", "hint", "encourage"):
                    try:
                        from app.services.keyword_listen import get_keyword_listen_service

                        if intent_l == "praise":
                            get_keyword_listen_service().note_teacher_praise(
                                str(session_id)
                            )
                        else:
                            get_keyword_listen_service().disarm(
                                str(session_id),
                                reason=f"system_speak:{intent_l}",
                            )
                    except Exception as kw_err:  # noqa: BLE001
                        logger.debug(
                            "[AudioService] keyword_listen disarm failed: %s",
                            kw_err,
                        )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("[AudioService] 发送 browser 话术失败: %s", exc, exc_info=True)
            return False

    @staticmethod
    def _interactive_intent(audio_type: str) -> str:
        """配对/排序专用音频键 → 话术 intent（排序题干多为 category_rule 键）。"""
        key = (audio_type or "").strip().lower()
        if key in ("praise", "encourage", "hint"):
            return key
        # question / ordering_bigger / size_bigger 等一律当提问话术
        return "question"

    @staticmethod
    def _ordering_question_variant(course_type: str, audio_type: str) -> Optional[str]:
        """排序提问：从 audio_type / category_rule 解析话术 variant。"""
        ct = (course_type or "").strip().lower()
        if ct not in ("ordering", "sequencing"):
            return None
        from app.dialogue.phrases import normalize_ordering_question_key

        return normalize_ordering_question_key(audio_type)

    def play_interactive_course_audio(
        self,
        session_id: Optional[str],
        course_type: str,
        audio_type: str,
        *,
        delay_ms: int = 0,
        category: Optional[str] = None,
        rule: Optional[str] = None,
        text: Optional[str] = None,
        behavior_id: Optional[str] = None,
        request_id: Optional[str] = None,
        question_id: Optional[str] = None,
    ) -> bool:
        """
        配对/排序交互页答对或切题时播语音。
        DIALOGUE_TTS_MODE=browser 时下发 robot_speak_text（话术库），不播预录 MP3。
        排序提问按 category+rule / audio_type / 显式 text 选用「选出更大的那张」等规则句。
        """
        if not course_type or not audio_type:
            return False
        tts_mode = self._tts_mode()
        use_browser = tts_mode in ("browser", "both")
        use_file = tts_mode in ("file", "both")
        child_room = f"session_{session_id}_child" if session_id else None
        intent = self._interactive_intent(audio_type)
        variant = None
        spoken = (text or "").strip() or None
        if intent == "question":
            from app.dialogue.phrases import ordering_phrase_key

            variant = ordering_phrase_key(category, rule) or self._ordering_question_variant(
                course_type, audio_type
            )
            # 排序：禁止落到「按规则选一选」；无 variant 时再从 audio_type 抠
            if (
                not spoken
                and (course_type or "").strip().lower() in ("ordering", "sequencing")
                and not variant
            ):
                logger.warning(
                    "[AudioService] ordering 提问缺少 category/rule/variant "
                    "cat=%s rule=%s audio=%s",
                    category,
                    rule,
                    audio_type,
                )
        triggered = False

        if use_browser:
            triggered = self._emit_browser_phrase(
                room=child_room,
                intent=intent,
                course_type=course_type,
                delay_ms=delay_ms,
                session_id=session_id,
                variant=variant,
                text=spoken,
                behavior_id=behavior_id,
                request_id=request_id,
                question_id=question_id,
            ) or triggered

        if use_file:
            result = self.emitter.emit_for_course(
                room=child_room,
                course_type=course_type,
                audio_type=audio_type,
                delay_ms=delay_ms,
                behavior_id=behavior_id,
                request_id=request_id,
            )
            logger.info(
                "[AudioService] interactive emit_for_course type=%s audio=%s ok=%s",
                course_type,
                audio_type,
                result,
            )
            triggered = bool(result) or triggered

        return triggered

    @staticmethod
    def _resolve_play_item_name(
        session_id: Optional[str],
        data: Dict[str, Any],
    ) -> Optional[str]:
        """从 play_resource 载荷 / 页上下文 / CourseItem 解析当前课点名。"""
        from app.dialogue.phrases import resolve_item_display_name

        page_ctx = data.get("pageContext") or data.get("page_context") or {}
        name = resolve_item_display_name(data, page_ctx if isinstance(page_ctx, dict) else {})
        if name:
            return name
        if session_id:
            try:
                from app.dialogue.page_context_store import get_interactive_page_context

                name = resolve_item_display_name(get_interactive_page_context(session_id))
                if name:
                    return name
            except Exception as exc:  # noqa: BLE001
                logger.debug("[AudioService] 读页上下文取名失败: %s", exc)
        item_id = data.get("itemId") or data.get("item_id")
        if item_id is not None:
            try:
                from database.models import CourseItem, db

                item = db.session.get(CourseItem, int(item_id))
                if item:
                    name = resolve_item_display_name(
                        {
                            "name": getattr(item, "name", None),
                            "speechTarget": getattr(item, "speech_target", None),
                        }
                    )
                    if name:
                        return name
            except Exception as exc:  # noqa: BLE001
                logger.debug("[AudioService] CourseItem 取名失败: %s", exc)
        return None

    def process_play_resource(
        self,
        session_id: Optional[str],
        data: Dict[str, Any],
        *,
        sequence_delay_ms: int = 0,
        behavior_id: Optional[str] = None,
        request_id: Optional[str] = None,
        return_details: bool = False,
    ) -> Any:
        def response(
            triggered: bool,
            dispatch_count: int = 0,
            *,
            deferred: bool = False,
        ) -> Any:
            # browser/file are alternative transports for one correlated
            # utterance. In "both" debug mode the child deliberately dedupes
            # them by behaviorId, so the behavior waits for one real terminal
            # callback instead of a second callback that will never arrive.
            effective_count = 1 if triggered and dispatch_count else 0
            details = {
                'triggered': bool(triggered),
                'dispatchCount': effective_count,
                'transportDispatchCount': max(0, int(dispatch_count or 0)),
                'behaviorId': str(behavior_id) if behavior_id else None,
                'requestId': str(request_id) if request_id else None,
                'deferred': bool(deferred),
            }
            return details if return_details else details['triggered']

        try:
            aux = data.get('aux', {}) or {}
            course_type = data.get('courseType')
            tts_mode = self._tts_mode()

            logger.info(
                "[AudioService] process_play_resource session_id=%s course_type=%s aux=%s tts_mode=%s",
                session_id,
                course_type,
                aux,
                tts_mode,
            )

            if not course_type:
                logger.warning(
                    "process_play_resource: 缺少 courseType (session_id=%s)",
                    session_id,
                )
                return response(False)

            child_room = f"session_{session_id}_child" if session_id else None
            delay_ms = max(0, int(sequence_delay_ms or 0))
            try:
                from app.robot import get_robot_service
                delay_ms += get_robot_service().resolve_audio_offset_ms(data)
            except Exception as e:
                logger.warning("[AudioService] 读取行为语音偏移失败，使用 0ms: %s", e)

            triggered = False
            dispatch_count = 0

            def record_dispatch(result: Any) -> bool:
                nonlocal triggered, dispatch_count
                ok = bool(result)
                if ok:
                    triggered = True
                    dispatch_count += 1
                return ok

            use_browser = tts_mode in ("browser", "both")
            use_file = tts_mode in ("file", "both")

            if aux.get('attention') or aux.get('reward'):
                # These live engagement states have no legacy MP3 branch.
                # Server selects the text and the child renders browser TTS.
                intent = 'attention' if aux.get('attention') else 'reward'
                record_dispatch(self._emit_browser_phrase(
                    room=child_room,
                    intent=intent,
                    course_type='global',
                    delay_ms=delay_ms,
                    session_id=session_id,
                    behavior_id=behavior_id,
                    request_id=request_id,
                ))

            elif aux.get('question'):
                # 排序提问应由 sequencing_question_ready（带 category+rule）触发；
                # 忽略教师端裸 aux.question，避免盖成「按规则选一选」。
                ct = str(course_type or '').strip().lower()
                if ct in ('ordering', 'sequencing'):
                    page_context = data.get('pageContext')
                    if not isinstance(page_context, dict):
                        page_context = data.get('page_context')
                    if not isinstance(page_context, dict):
                        page_context = {}
                    category = data.get('category') or page_context.get('category')
                    rule = data.get('rule') or page_context.get('rule')
                    prompt = (
                        data.get('prompt')
                        or page_context.get('prompt')
                        or None
                    )
                    if category and rule:
                        try:
                            from app.audio.manifest_io import ordering_audio_type

                            ordering_type = ordering_audio_type(category, rule)
                        except Exception:
                            ordering_type = 'question'
                        ok = self.play_interactive_course_audio(
                            session_id=session_id,
                            course_type='ordering',
                            audio_type=ordering_type,
                            delay_ms=delay_ms,
                            category=category,
                            rule=rule,
                            text=prompt,
                            behavior_id=behavior_id,
                            request_id=request_id,
                        )
                        return response(bool(ok), 1 if ok else 0)
                    logger.info(
                        "[AudioService] 忽略 ordering 裸 aux.question，等待 sequencing_question_ready"
                    )
                    return response(False, deferred=True)
                if use_browser:
                    item_name = None
                    if ct == "onomatopoeia":
                        item_name = self._resolve_play_item_name(session_id, data)
                    record_dispatch(self._emit_browser_phrase(
                        room=child_room,
                        intent="question",
                        course_type=course_type,
                        delay_ms=delay_ms,
                        session_id=session_id,
                        name=item_name,
                        behavior_id=behavior_id,
                        request_id=request_id,
                    ))
                if use_file:
                    result = self.emitter.emit_for_course(
                        room=child_room,
                        course_type=course_type,
                        audio_type='question',
                        delay_ms=delay_ms,
                        behavior_id=behavior_id,
                        request_id=request_id,
                    )
                    logger.info("[AudioService] emit_for_course question: %s", result)
                    record_dispatch(result)

            elif aux.get('praise'):
                if use_browser:
                    record_dispatch(self._emit_browser_phrase(
                        room=child_room,
                        intent="praise",
                        course_type=course_type,
                        delay_ms=delay_ms,
                        session_id=session_id,
                        behavior_id=behavior_id,
                        request_id=request_id,
                    ))
                if use_file:
                    result = self.emitter.emit_for_course(
                        room=child_room,
                        course_type=course_type,
                        audio_type='praise',
                        delay_ms=delay_ms,
                        behavior_id=behavior_id,
                        request_id=request_id,
                    )
                    logger.info("[AudioService] emit_for_course praise: %s", result)
                    record_dispatch(result)

            elif aux.get('hint'):
                if use_browser:
                    record_dispatch(self._emit_browser_phrase(
                        room=child_room,
                        intent="hint",
                        course_type=course_type,
                        delay_ms=delay_ms,
                        session_id=session_id,
                        behavior_id=behavior_id,
                        request_id=request_id,
                    ))
                if use_file:
                    item_id = data.get('itemId') or data.get('item_id')
                    played = False
                    if item_id is not None:
                        try:
                            from database.models import CourseItem, db
                            item = db.session.get(CourseItem, int(item_id))
                            hint_path = (item.hint_audio or '').strip() if item else ''
                            if hint_path:
                                result = self.emitter.emit_file_path(
                                    room=child_room,
                                    file_path=hint_path,
                                    entry_id=f'item_{item_id}_hint',
                                    delay_ms=delay_ms,
                                    behavior_id=behavior_id,
                                    request_id=request_id,
                                )
                                logger.info("[AudioService] item hint: %s path=%s", result, hint_path)
                                played = bool(result)
                                record_dispatch(result)
                        except Exception as e:
                            logger.warning("[AudioService] 读取课点 hint 失败: %s", e)
                    if not played:
                        result = self.emitter.emit_for_course(
                            room=child_room,
                            course_type=course_type,
                            audio_type='hint',
                            item_id=int(item_id) if item_id is not None else None,
                            delay_ms=delay_ms,
                            behavior_id=behavior_id,
                            request_id=request_id,
                        )
                        logger.info("[AudioService] emit_for_course hint: %s", result)
                        record_dispatch(result)

            elif aux.get('socialGreetingIntro'):
                if use_browser:
                    record_dispatch(self._emit_browser_phrase(
                        room=child_room,
                        intent="social_greeting_intro",
                        course_type=course_type,
                        delay_ms=delay_ms,
                        session_id=session_id,
                        behavior_id=behavior_id,
                        request_id=request_id,
                    ))
                if use_file:
                    result = self.emitter.emit_for_course(
                        room=child_room,
                        course_type=course_type,
                        audio_type='social_greeting_intro',
                        delay_ms=delay_ms,
                        behavior_id=behavior_id,
                        request_id=request_id,
                    )
                    logger.info("[AudioService] 社交初见打招呼(file): %s", result)
                    record_dispatch(result)

            elif aux.get('socialGreetingPlay'):
                if use_browser:
                    record_dispatch(self._emit_browser_phrase(
                        room=child_room,
                        intent="social_greeting_play",
                        course_type=course_type,
                        delay_ms=delay_ms,
                        session_id=session_id,
                        behavior_id=behavior_id,
                        request_id=request_id,
                    ))
                if use_file:
                    result = self.emitter.emit_for_course(
                        room=child_room,
                        course_type=course_type,
                        audio_type='social_greeting_play',
                        delay_ms=delay_ms,
                        behavior_id=behavior_id,
                        request_id=request_id,
                    )
                    logger.info("[AudioService] 社交一起玩耍吧(file): %s", result)
                    record_dispatch(result)

            elif aux.get('socialFarewellBye'):
                if use_browser:
                    record_dispatch(self._emit_browser_phrase(
                        room=child_room,
                        intent="social_farewell_bye",
                        course_type=course_type,
                        delay_ms=delay_ms,
                        session_id=session_id,
                        behavior_id=behavior_id,
                        request_id=request_id,
                    ))
                if use_file:
                    result = self.emitter.emit_for_course(
                        room=child_room,
                        course_type=course_type,
                        audio_type='social_farewell_bye',
                        delay_ms=delay_ms,
                        behavior_id=behavior_id,
                        request_id=request_id,
                    )
                    logger.info("[AudioService] 社交再见(file): %s", result)
                    record_dispatch(result)

            elif aux.get('socialFarewellReply'):
                if use_browser:
                    record_dispatch(self._emit_browser_phrase(
                        room=child_room,
                        intent="social_farewell_reply",
                        course_type=course_type,
                        delay_ms=delay_ms,
                        session_id=session_id,
                        behavior_id=behavior_id,
                        request_id=request_id,
                    ))
                if use_file:
                    result = self.emitter.emit_for_course(
                        room=child_room,
                        course_type=course_type,
                        audio_type='social_farewell_reply',
                        delay_ms=delay_ms,
                        behavior_id=behavior_id,
                        request_id=request_id,
                    )
                    logger.info("[AudioService] 社交回应(file): %s", result)
                    record_dispatch(result)

            if not triggered:
                logger.info(
                    "[AudioService] play_resource 未触发语音 session=%s aux=%s",
                    session_id,
                    aux,
                )
            return response(triggered, dispatch_count)

        except Exception as e:
            logger.error("处理语音播放失败 session=%s err=%s", session_id, e, exc_info=True)
            return response(False)


_audio_service: Optional[AudioService] = None


def get_audio_service() -> AudioService:
    global _audio_service
    if _audio_service is None:
        _audio_service = AudioService()
        logger.info("语音服务已初始化")
    return _audio_service


def init_audio_service() -> AudioService:
    global _audio_service
    _audio_service = AudioService()
    logger.info("语音服务已手动初始化")
    return _audio_service
