"""
WebSocket事件处理器
处理各种WebSocket事件的业务逻辑
"""
import time
import functools
import threading
from typing import Dict, Any, Optional, List
from app.session import get_session_manager
from app.session.session_model import SessionStatus, Session
from app.queue import get_video_queue, get_audio_queue
from app.services import get_media_service, get_analysis_service, get_feedback_service
from app.behavior import get_behavior_service, make_question_id
from app.services.recording_timeline import (
    allocate_human_dir_name,
    begin_recording_session,
    finalize_recording_session,
    load_student_label,
    mark_course_segment,
    resolve_course_type_id,
)
from app.utils.logger import setup_logger


logger = setup_logger('socket_handlers')

# 同一 session 缺失时避免逐帧刷屏（agent 未停或仅走 Socket 时的兜底）
_MISSING_SESSION_LOG_INTERVAL_SEC = 30.0
_missing_session_log_at: Dict[str, float] = {}
_strict_capture_start_lock = threading.RLock()

_INTERACTIVE_COURSE_TYPES = frozenset({'pairing', 'ordering', 'matching', 'sequencing'})
_SPEECH_COURSE_TYPES = frozenset({'naming', 'speech', 'onomatopoeia', 'mimic'})

_DEFAULT_SPEECH_PROMPTS = {
    'naming': '这是什么呀',
    'speech': '这是什么呀',
    'onomatopoeia': '听听，这是什么声音呀？',
    'mimic': '跟我做一样的动作吧',
}


def _default_prompt_for_course(course_type: str, *, item_name: Optional[str] = None) -> str:
    ct = str(course_type or '').strip().lower()
    if ct == 'onomatopoeia':
        from app.dialogue.phrases import format_onomatopoeia_question

        return format_onomatopoeia_question(item_name)
    return _DEFAULT_SPEECH_PROMPTS.get(ct, '')


def _sync_dialogue_page_context_for_play(
    session_id: Optional[str],
    *,
    course_type: str,
    course_id: Any = None,
    item_id: Any = None,
    question_id: Any = None,
    question_index: Any = None,
    item_name: Optional[str] = None,
    speech_target: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    play_resource 时重建对话页上下文。
    命名/拟声/模仿：覆盖写入当前物品，清掉配对/排序残留。
    进入互动课：至少写入课型，等 iframe 再补全题面。
    """
    if not session_id:
        return None
    try:
        from app.dialogue.page_context_store import (
            clear_interactive_page_context,
            set_interactive_page_context,
        )

        ct = str(course_type or '').strip().lower() or 'default'
        label = (speech_target or item_name or '').strip()
        display_name = (item_name or speech_target or '').strip()

        if ct in _SPEECH_COURSE_TYPES:
            # 先清再写：丢掉配对/排序 options/rule 等残留
            clear_interactive_page_context(session_id)
            cue = ""
            try:
                from app.dialogue.image_semantics import item_cue_from_label

                cue = item_cue_from_label(label) or item_cue_from_label(display_name)
            except Exception:  # noqa: BLE001
                cue = ""
            clean = {
                k: v
                for k, v in {
                    'courseType': ct,
                    'courseId': course_id,
                    'itemId': item_id,
                    'questionId': question_id,
                    'questionIndex': question_index,
                    'target': label,
                    'targetText': label,
                    'speechTarget': label,
                    'name': item_name or label,
                    'label': label,
                    'targetDescription': cue or None,
                    'prompt': _default_prompt_for_course(ct, item_name=display_name),
                }.items()
                if v is not None and v != ''
            }
            set_interactive_page_context(session_id, clean)
            return clean

        if ct in _INTERACTIVE_COURSE_TYPES:
            # 课型切换时丢掉命名残留；题面由 iframe postMessage 补全
            set_interactive_page_context(
                session_id,
                {
                    'courseType': ct,
                    'courseId': course_id,
                    'itemId': item_id,
                    'questionId': question_id,
                    'questionIndex': question_index,
                    'target': None,
                    'speechTarget': None,
                    'name': None,
                    'label': None,
                },
            )
            return {'courseType': ct, 'courseId': course_id, 'itemId': item_id}

        # 其它课型：至少刷新课型/条目，避免旧互动上下文污染
        clear_interactive_page_context(session_id)
        clean = {
            k: v
            for k, v in {
                'courseType': ct,
                'courseId': course_id,
                'itemId': item_id,
                'questionId': question_id,
                'questionIndex': question_index,
                'target': label or None,
                'speechTarget': label or None,
                'name': item_name or label or None,
                'prompt': _default_prompt_for_course(ct, item_name=display_name) or None,
            }.items()
            if v is not None and v != ''
        }
        if clean:
            set_interactive_page_context(session_id, clean)
        return clean or None
    except Exception as e:
        logger.warning('同步对话页上下文失败: %s', e)
        return None


def _warn_missing_session(event: str, session_id: str) -> None:
    key = f"{event}:{session_id}"
    now = time.time()
    last = _missing_session_log_at.get(key, 0.0)
    if now - last < _MISSING_SESSION_LOG_INTERVAL_SEC:
        return
    _missing_session_log_at[key] = now
    logger.warning("%s事件引用的会话不存在: session_id=%s", event, session_id)


def _close_runtime_session(
    session_id: str,
    *,
    send_summary: bool = False,
    stop_media: bool = True,
    end_analysis: bool = True,
    strict: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    规范收尾一个 runtime session：停录制 → 结束分析 → 结束会话 → 移除。
    返回 analysis end_session 摘要（若有）。
    """
    session_manager = get_session_manager()
    session = session_manager.get_session(session_id)
    if not session:
        if strict:
            raise RuntimeError(f'runtime_session_not_found:{session_id}')
        return None

    summary = None
    errors: List[str] = []
    if stop_media:
        try:
            media_service = get_media_service()
            media_stopped = media_service.stop_recording(session_id)
            if strict and media_stopped is False:
                errors.append('stop_media:return_false')
        except Exception as e:
            logger.warning("停止录制失败: session=%s err=%s", session_id, e)
            errors.append(f'stop_media:{e}')

    if end_analysis:
        try:
            analysis_service = get_analysis_service()
            summary = analysis_service.end_session(session_id)
            if send_summary and summary:
                get_feedback_service().send_session_summary(session_id, summary)
        except Exception as e:
            logger.warning("结束分析会话失败: session=%s err=%s", session_id, e)
            errors.append(f'end_analysis:{e}')

    # In lifecycle/finalize flows, keep the runtime session registered and
    # retryable when a required external cleanup step failed.
    if strict and errors:
        raise RuntimeError(
            f'runtime_cleanup_failed:{session_id}:' + ';'.join(errors)
        )

    try:
        if session.is_active():
            session_manager.end_session(session_id, SessionStatus.COMPLETED)
    except Exception as e:
        logger.warning("结束会话状态失败: session=%s err=%s", session_id, e)
        errors.append(f'end_session:{e}')

    if strict and errors:
        raise RuntimeError(
            f'runtime_cleanup_failed:{session_id}:' + ';'.join(errors)
        )

    try:
        session_manager.remove_session(session_id)
    except Exception as e:
        logger.warning("移除会话失败: session=%s err=%s", session_id, e)
        errors.append(f'remove_session:{e}')

    if strict and errors:
        raise RuntimeError(
            f'runtime_cleanup_failed:{session_id}:' + ';'.join(errors)
        )

    # 保留 recording path registry，供 agent 异步补传到 human_dir
    return summary if isinstance(summary, dict) else None


def _find_continuous_session(
    student_id: Optional[int],
    training_session_id: Optional[str] = None,
) -> Optional[Session]:
    """查找学生当前整场连续录制 runtime session。"""
    if student_id is None:
        return None
    session_manager = get_session_manager()
    for sess in session_manager.get_sessions_by_student(int(student_id)):
        if not sess.is_active():
            continue
        if (
            training_session_id
            and getattr(sess, 'training_session_id', None) != training_session_id
        ):
            continue
        meta = sess.metadata or {}
        if meta.get('continuous_recording') or meta.get('recording_mode') == 'continuous':
            return sess
    for sess in session_manager.get_sessions_by_student(int(student_id)):
        if (
            sess.is_active()
            and (
                not training_session_id
                or getattr(sess, 'training_session_id', None) == training_session_id
            )
        ):
            return sess
    return None


def _refresh_session_paths(session: Session) -> None:
    """在登记 human_dir 后刷新会话上的音视频路径。"""
    from app.config import Config

    session.video_file_path = str(Config.get_video_file_path(session.session_id))
    session.audio_file_path = str(Config.get_audio_file_path(session.session_id))
    session.result_file_path = str(Config.get_result_file_path(session.session_id))
    get_session_manager().update_session(session)


def start_preflight_capture(training_session_id: str) -> Dict[str, Any]:
    """Start the formal recorder for an explicitly strict prepared session.

    This adapter intentionally reuses the legacy recording/session services;
    it is the reversible strangler seam until those services are migrated to
    ``CapturePort``.

    Legacy (non-strict) prepare already starts capture during prepare_training;
    readiness still calls this callback, so an active continuous session for the
    same training id is treated as an idempotent success rather than a miss.
    """
    with _strict_capture_start_lock:
        session_manager = get_session_manager()
        training_key = str(training_session_id)
        candidates = [
            sess for sess in session_manager.list_all_sessions()
            if str(getattr(sess, 'training_session_id', '') or '') == training_key
        ]
        target = next(
            (
                sess for sess in candidates
                if bool((sess.metadata or {}).get('strict_preflight'))
            ),
            None,
        )
        if target is None:
            # Browser/legacy prepare: recorder is already running for this training.
            legacy = next(
                (
                    sess for sess in candidates
                    if sess.is_active()
                    or bool((sess.metadata or {}).get('capture_started'))
                    or bool((sess.metadata or {}).get('continuous_recording'))
                ),
                None,
            )
            if legacy is not None:
                return {
                    'ok': True,
                    'idempotent': True,
                    'sessionId': legacy.session_id,
                    'legacy': True,
                }
            return {
                'ok': False,
                'error': 'strict_preflight_session_not_found',
                'message': (
                    '服务端录制会话已丢失（常见于后端刚重启）。'
                    '请返回选课，重新点击开始评估/训练后再开课。'
                ),
            }
        metadata = target.metadata or {}
        target.metadata = metadata
        if metadata.get('capture_started'):
            return {'ok': True, 'idempotent': True, 'sessionId': target.session_id}
        if target.status == SessionStatus.FAILED:
            # A teacher retry reuses the reserved media identity, but none of
            # the previous failed attempt's state or uplink evidence.
            target.status = SessionStatus.CREATED
            target.started_at = None
            target.ended_at = None
            metadata.pop('error', None)
            from app.routes.media_upload import reset_media_session_meta
            reset_media_session_meta(target.session_id)
        human_dir = metadata.get('human_dir_name')
        if not human_dir:
            return {'ok': False, 'error': 'strict_preflight_missing_session_layout'}
        timeline_started = False
        media_service = get_media_service()
        try:
            begin_recording_session(
                media_session_id=target.session_id,
                training_session_id=str(training_session_id),
                student_id=target.student_id,
                human_dir_name=human_dir,
                n=int(metadata.get('recording_n') or 1),
            )
            timeline_started = True
            _refresh_session_paths(target)
            media_started = media_service.start_recording(
                target.session_id,
                student_id=target.student_id,
            )
            if media_started is not True:
                raise RuntimeError('media_service_start_failed')
            if target.status == SessionStatus.CREATED:
                target.start()
            metadata['capture_started'] = True
            metadata['preflight_only'] = False
            metadata.pop('capture_start_error', None)
            session_manager.update_session(target)
            return {'ok': True, 'sessionId': target.session_id, 'captureStarted': True}
        except Exception as exc:
            try:
                media_service.stop_recording(target.session_id)
            except Exception:
                pass
            if timeline_started:
                try:
                    finalize_recording_session(target.session_id, status='start_failed')
                except Exception:
                    pass
            metadata['capture_started'] = False
            metadata['preflight_only'] = True
            metadata['capture_start_error'] = str(exc)
            if target.is_active():
                target.fail(str(exc))
            session_manager.update_session(target)
            logger.error('strict preflight 正式采集启动失败: %s', exc, exc_info=True)
            return {
                'ok': False,
                'error': str(exc),
                'sessionId': target.session_id,
                'rolledBack': True,
            }


def _apply_analysis_targets(
    session_id: str,
    *,
    course_type: str,
    resolved_file: Optional[str],
    aux_data: Dict[str, Any],
) -> None:
    analysis_service = get_analysis_service()
    target_image = resolved_file or aux_data.get('targetImage') or aux_data.get('imagePath')

    if target_image and course_type in ['imitation', 'pose', 'mimic']:
        if target_image.startswith('/'):
            image_path = target_image[1:]
        else:
            image_path = target_image
        if not image_path.startswith('static'):
            image_path = f"static/{image_path}"

        if analysis_service.set_pose_target_from_path(session_id, image_path):
            logger.info("姿态目标已设置: session_id=%s, path=%s", session_id, image_path)
        else:
            logger.warning("设置姿态目标失败: session_id=%s, path=%s", session_id, image_path)

    target_text = aux_data.get('targetText') or aux_data.get('text')
    if target_text and course_type in ['naming', 'speech', 'onomatopoeia']:
        analysis_service.set_speech_target(session_id, target_text)
        logger.info("语音目标已设置: session_id=%s, text=%s", session_id, target_text)

def _freeze_active_profile_version(session: Session, *, course_id: Any, course_type: str) -> Optional[str]:
    """Freeze the server-selected interaction profile on first course use."""
    metadata = dict(session.metadata or {})
    if 'activeProfileVersion' in metadata:
        return metadata.get('activeProfileVersion')
    try:
        from app.robot import get_robot_service

        version = get_robot_service().get_active_profile_version(
            course_id=course_id,
            course_type=course_type,
            session_id=session.session_id,
        )
    except Exception as exc:
        logger.warning('冻结 InteractionProfileV2 版本失败，保持 legacy: %s', exc)
        version = None
    metadata['activeProfileVersion'] = version
    metadata['activeProfileVersionSource'] = 'server'
    session.metadata = metadata
    get_session_manager().update_session(session)
    return version


class PlayResourceHandler:
    """处理play_resource事件"""

    @staticmethod
    def _resolve_course_type(course_id: Any, fallback: str = 'default') -> str:
        """从数据库根据 course_id 推导课程 type（前端兼容的英文枚举），失败则回退 fallback。"""
        if not course_id:
            return fallback

        try:
            from database.models import Course

            course = Course.query.get(course_id)
            if not course:
                return fallback

            course_dict = course.to_dict()
            course_type = course_dict.get('type')
            return course_type or fallback
        except Exception as e:
            logger.warning("解析课程类型失败: course_id=%s, err=%s", course_id, e)
            return fallback

    @staticmethod
    def handle(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        处理播放资源事件

        Returns:
            含 session_id / training_session_id 等的字典
        """
        try:
            if not data or data.get('action') != 'play':
                logger.warning("无效的play_resource事件数据: %s", data)
                return None

            student_id = data.get('studentId')
            course_id = data.get('courseId')
            item_id = data.get('itemId')
            aux = data.get('aux', {})
            question_index = int(data.get('questionIndex') or data.get('itemIndex') or 0)

            resolved_course_type = PlayResourceHandler._resolve_course_type(
                course_id,
                fallback=data.get('courseType', 'default')
            )
            data['courseType'] = resolved_course_type

            if student_id is None:
                logger.warning("play_resource事件缺少studentId字段")
            else:
                logger.info(
                    "处理play_resource事件: studentId=%s, courseId=%s, itemId=%s, aux=%s",
                    student_id, course_id, item_id, aux
                )

            is_aux_operation = False
            existing_session = None
            session_manager = get_session_manager()
            behavior = get_behavior_service()

            aux_flags = aux if isinstance(aux, dict) else {}
            has_aux_flag = bool(
                aux_flags.get('question')
                or aux_flags.get('praise')
                or aux_flags.get('hint')
                or aux_flags.get('socialGreetingIntro')
                or aux_flags.get('socialGreetingPlay')
                or aux_flags.get('socialFarewellBye')
                or aux_flags.get('socialFarewellReply')
            )
            interactive_types = {'pairing', 'ordering', 'matching', 'sequencing'}

            if has_aux_flag and course_id:
                requested_runtime_id = (
                    data.get('sessionId')
                    or data.get('session_id')
                    or data.get('runtimeSessionId')
                )
                requested_training_id = (
                    data.get('trainingSessionId')
                    or data.get('training_session_id')
                )
                if requested_runtime_id:
                    requested_session = session_manager.get_session(
                        str(requested_runtime_id)
                    )
                    all_sessions = [requested_session] if requested_session else []
                else:
                    all_sessions = session_manager.list_all_sessions()
                for sess in all_sessions:
                    if not sess.is_active() or sess.course_id != course_id:
                        continue
                    # aux 必须精确归属于当前儿童和训练，不能复用“第一个同课点”
                    # 的旧会话，否则语音会投递到另一个 session 房间。
                    if student_id is not None and sess.student_id != int(student_id):
                        continue
                    if (
                        requested_training_id
                        and getattr(sess, 'training_session_id', None)
                        != requested_training_id
                    ):
                        continue
                    # 有 item 的课程：同 course+item 复用
                    if item_id is not None:
                        if sess.course_item_id != item_id:
                            continue
                        # 社交打招呼/再见无 media_file，resolved_file 为空仍应复用做 aux
                        if not sess.resolved_file_path:
                            sess_type = (sess.metadata or {}).get('course_type') or resolved_course_type
                            if sess_type != 'social' and resolved_course_type != 'social':
                                continue
                    else:
                        # 配对/排序等 itemId 为空：同学生同 course 复用
                        if student_id is not None and sess.student_id != student_id:
                            continue
                        sess_type = (sess.metadata or {}).get('course_type') or resolved_course_type
                        if sess_type not in interactive_types and resolved_course_type not in interactive_types:
                            # 仍允许 item_id 为空时复用同 course 的 active session
                            if sess.course_item_id is not None:
                                continue
                    is_aux_operation = True
                    existing_session = sess
                    logger.info(
                        "检测到aux操作，复用会话: session_id=%s, item_id=%s, file=%s",
                        sess.session_id, item_id, sess.resolved_file_path
                    )
                    break

            if is_aux_operation and existing_session:
                course_type = data.get('courseType', 'default')
                behavior_animation = None
                if aux.get('praise'):
                    try:
                        from app.robot import get_robot_service
                        behavior_animation = get_robot_service().resolve_encouragement_animation(data)
                        if behavior_animation:
                            logger.info(
                                "[AuxOperation] resolved encouragement animation: session_id=%s, animation=%s",
                                existing_session.session_id, behavior_animation
                            )
                    except Exception as e:
                        logger.error("Failed to resolve encouragement animation: %s", e, exc_info=True)
                    try:
                        from app.services.keyword_listen import get_keyword_listen_service

                        get_keyword_listen_service().note_teacher_praise(
                            existing_session.session_id
                        )
                    except Exception as kw_err:
                        logger.debug('keyword_listen teacher praise note failed: %s', kw_err)

                return {
                    'session_id': existing_session.session_id,
                    'training_session_id': getattr(existing_session, 'training_session_id', None),
                    'question_id': getattr(existing_session, 'question_id', None),
                    'resolved_file': existing_session.resolved_file_path,
                    'is_aux_operation': True,
                    'behavior_animation': behavior_animation,
                    'audio_pending': True,
                    'recording_mode': 'continuous',
                    'human_dir_name': (existing_session.metadata or {}).get('human_dir_name'),
                    'mode': (existing_session.metadata or {}).get('mode'),
                }

            # 训练会话：优先教师 payload（prepare_training 已开），再复用 active
            training_session_id = (
                data.get('trainingSessionId')
                or data.get('training_session_id')
            )
            if not training_session_id and student_id is not None:
                training_session_id = behavior.get_active_training_id(int(student_id))
            if not training_session_id:
                training = behavior.open_training(
                    student_id=int(student_id) if student_id is not None else None,
                    metadata={'source': 'play_resource'}
                )
                training_session_id = training.training_session_id

            # ---- 方案 B：复用整场 media session，切题不启停录制 ----
            session = _find_continuous_session(
                int(student_id) if student_id is not None else None,
                training_session_id,
            )
            created_new_media = False
            if session is None:
                name, age = load_student_label(
                    int(student_id) if student_id is not None else None
                )
                human_dir, n = allocate_human_dir_name(
                    student_id=int(student_id) if student_id is not None else None,
                    student_name=name,
                    student_age=age,
                )
                session = session_manager.create_session(
                    student_id=student_id,
                    course_id=course_id,
                    course_item_id=item_id,
                    training_session_id=training_session_id,
                    question_id=make_question_id(course_id, item_id, question_index),
                    question_index=question_index,
                    metadata={
                        'continuous_recording': True,
                        'recording_mode': 'continuous',
                        'human_dir_name': human_dir,
                        'recording_n': n,
                        'source': 'play_resource',
                        'course_type': resolved_course_type,
                    },
                )
                begin_recording_session(
                    media_session_id=session.session_id,
                    training_session_id=training_session_id,
                    student_id=int(student_id) if student_id is not None else None,
                    human_dir_name=human_dir,
                    n=n,
                )
                _refresh_session_paths(session)
                session.start()
                session_manager.update_session(session)
                get_media_service().start_recording(
                    session.session_id,
                    student_id=student_id,
                    course_id=course_id,
                    course_item_id=item_id,
                )
                created_new_media = True
                logger.warning(
                    "play_resource 无 prepare 会话，已兜底创建连续录制: media=%s human=%s",
                    session.session_id, human_dir,
                )

            # 关闭上一题行为窗口（不关媒体 / 不 end_analysis）
            prev_qid = getattr(session, 'question_id', None)
            prev_ts = getattr(session, 'training_session_id', None) or training_session_id
            was_warmup = bool((session.metadata or {}).get('warmup'))
            if prev_qid and prev_ts and not was_warmup:
                try:
                    behavior.close_window(prev_ts, prev_qid, analysis_summary=None)
                except Exception as e:
                    logger.warning("关闭上一题窗口失败: %s", e)

            question_id = make_question_id(course_id, item_id, question_index)

            _freeze_active_profile_version(
                session,
                course_id=course_id,
                course_type=resolved_course_type,
            )

            meta = dict(session.metadata or {})
            meta['warmup'] = False
            meta['continuous_recording'] = True
            meta['recording_mode'] = 'continuous'
            meta['source'] = 'play_resource'
            meta['course_type'] = resolved_course_type
            meta['aux'] = data.get('aux', {})
            session.course_id = course_id
            session.course_item_id = item_id
            session.training_session_id = training_session_id
            session.question_id = question_id
            session.question_index = question_index
            session.metadata = meta
            session_manager.update_session(session)

            behavior.open_window(
                training_session_id,
                course_id=course_id,
                course_item_id=item_id,
                question_index=question_index,
                course_type=resolved_course_type,
                runtime_session_id=session.session_id,
                question_id=question_id,
            )
            try:
                from app.monitor.events import append_monitor_event

                if prev_qid and prev_ts and not was_warmup:
                    append_monitor_event(
                        "question_close",
                        f"关闭课点窗口 {prev_qid}",
                        training_session_id=prev_ts,
                        question_id=prev_qid,
                    )
                append_monitor_event(
                    "question_open",
                    f"打开课点 {resolved_course_type} #{int(question_index) + 1}",
                    training_session_id=training_session_id,
                    question_id=question_id,
                )
            except Exception:
                pass

            try:
                ct_id = resolve_course_type_id(course_id)
                mark_course_segment(
                    session.session_id,
                    course_id=int(course_id) if course_id is not None else None,
                    course_item_id=int(item_id) if item_id is not None else None,
                    course_type_id=ct_id,
                    question_id=question_id,
                )
            except Exception as e:
                logger.warning("timeline 打点失败: %s", e)

            resolved_file = None
            item_name = None
            speech_target = None
            if course_id and item_id:
                try:
                    from database.models import CourseItem
                    from app.utils.resource_utils import is_folder_path, get_random_file_from_folder

                    course_item = CourseItem.query.get(item_id)
                    if course_item:
                        item_name = course_item.name
                        speech_target = (course_item.speech_target or course_item.name or '').strip() or None
                        if course_item.media_file:
                            media_path = course_item.media_file
                            if is_folder_path(media_path):
                                resolved_file = get_random_file_from_folder(media_path)
                                if resolved_file:
                                    logger.info("随机选择资源: %s -> %s", media_path, resolved_file)
                            else:
                                resolved_file = media_path
                        else:
                            logger.warning("CourseItem.media_file为空: item_id=%s", item_id)
                    else:
                        logger.warning("CourseItem不存在: item_id=%s", item_id)
                except Exception as e:
                    logger.error("处理文件夹路径失败: %s", e, exc_info=True)

            if resolved_file:
                session.resolved_file_path = resolved_file
                session_manager.update_session(session)

            page_ctx = _sync_dialogue_page_context_for_play(
                session.session_id,
                course_type=resolved_course_type,
                course_id=course_id,
                item_id=item_id,
                question_id=question_id,
                question_index=question_index,
                item_name=item_name,
                speech_target=speech_target,
            )

            try:
                analysis_service = get_analysis_service()
                course_type = data.get('courseType', 'default')
                interactive_no_auto_praise = {
                    'pairing', 'ordering', 'matching', 'sequencing'
                }
                course_config = {
                    'course_type': course_type,
                    'enable_realtime': True,
                    'enable_window': True,
                    'enable_triggers': course_type not in interactive_no_auto_praise,
                    'pose_threshold': 0.85,
                    'attention_threshold': 0.3
                }
                analysis_service.reconfigure_session(session.session_id, course_config)
                logger.info(
                    "分析会话就绪(连续): session_id=%s created_media=%s",
                    session.session_id, created_new_media,
                )
                aux_for_targets = dict(data.get('aux', {}) or {})
                if speech_target and not (
                    aux_for_targets.get('targetText') or aux_for_targets.get('text')
                ):
                    aux_for_targets['targetText'] = speech_target
                _apply_analysis_targets(
                    session.session_id,
                    course_type=course_type,
                    resolved_file=resolved_file,
                    aux_data=aux_for_targets,
                )
                try:
                    from app.services.keyword_listen import get_keyword_listen_service

                    kw_state = get_keyword_listen_service().prepare(
                        session.session_id,
                        course_type=course_type,
                        item_id=item_id,
                        speech_target=speech_target,
                        name=item_name,
                    )
                    # 拟声：优先用更短的拟声词作 ASR 比对目标（metrics），表扬仍走 keyword_listen
                    if kw_state.keywords and course_type in (
                        'naming',
                        'speech',
                        'onomatopoeia',
                    ):
                        asr_target = kw_state.primary_target
                        if course_type == 'onomatopoeia' and len(kw_state.keywords) > 1:
                            asr_target = min(kw_state.keywords, key=len)
                        if asr_target:
                            analysis_service.set_speech_target(
                                session.session_id,
                                asr_target,
                            )
                except Exception as kw_err:
                    logger.warning('keyword_listen prepare failed: %s', kw_err)
            except Exception as e:
                logger.error("启动/重配置分析会话失败: %s", e)

            human_dir = (session.metadata or {}).get('human_dir_name')
            logger.info(
                "连续录制切题: media=%s training=%s question=%s human=%s",
                session.session_id, training_session_id, question_id, human_dir,
            )

            return {
                'session_id': session.session_id,
                'training_session_id': training_session_id,
                'question_id': question_id,
                'question_index': question_index,
                'resolved_file': resolved_file,
                'recording_mode': 'continuous',
                'human_dir_name': human_dir,
                'audio_pending': True,
                'speech_target': speech_target,
                'item_name': item_name,
                'page_context': page_ctx,
                # prepare_training 写入的会话模式才是服务端事实源；教师端
                # 刷新或旧缓存不得把评估/干预语义悄悄切换。
                'mode': (session.metadata or {}).get('mode'),
            }

        except Exception as e:
            logger.error("处理play_resource事件失败: %s", e, exc_info=True)
            return {
                'session_id': None,
                'training_session_id': None,
                'resolved_file': None
            }

class VideoFrameHandler:
    """处理video_frame事件"""

    @staticmethod
    def handle(data: Dict[str, Any]) -> bool:
        try:
            session_id = data.get('sessionId')
            frame_data = data.get('frame')
            timestamp = data.get('timestamp')

            if not session_id:
                logger.warning("video_frame事件缺少sessionId字段")
                return False

            if not frame_data:
                logger.warning("video_frame事件缺少frame字段")
                return False

            session_manager = get_session_manager()
            session = session_manager.get_session(session_id)

            if not session:
                _warn_missing_session("video_frame", session_id)
                return False

            session.total_frames += 1

            video_queue = get_video_queue()
            success = video_queue.put(session_id, frame_data, timestamp)

            if success:
                logger.debug(
                    "收到视频帧并放入队列: session_id=%s, frame_count=%s, "
                    "queue_size=%s, timestamp=%s",
                    session_id, session.total_frames,
                    video_queue.size(session_id), timestamp
                )
                try:
                    analysis_service = get_analysis_service()
                    analysis_service.process_video_frame(session_id, frame_data, timestamp)
                except Exception as e:
                    logger.error("分析视频帧失败: %s", e)
                try:
                    from app.routes.media_upload import remember_probe_frame
                    remember_probe_frame(session_id, frame_data)
                except Exception:
                    pass
            else:
                logger.warning("视频帧放入队列失败: session_id=%s", session_id)

            return success

        except Exception as e:
            logger.error("处理video_frame事件失败: %s", e, exc_info=True)
            return False


class AudioChunkHandler:
    """处理audio_chunk事件"""

    @staticmethod
    def handle(data: Dict[str, Any]) -> bool:
        try:
            session_id = data.get('sessionId')
            chunk_data = data.get('chunk')
            timestamp = data.get('timestamp')

            if not session_id:
                logger.warning("audio_chunk事件缺少sessionId字段")
                return False

            if not chunk_data:
                logger.warning("audio_chunk事件缺少chunk字段")
                return False

            session_manager = get_session_manager()
            session = session_manager.get_session(session_id)

            if not session:
                _warn_missing_session("audio_chunk", session_id)
                return False

            session.total_audio_chunks += 1

            audio_queue = get_audio_queue()
            success = audio_queue.put(session_id, chunk_data, timestamp)

            if success:
                logger.debug(
                    "收到音频块并放入队列: session_id=%s, chunk_count=%s, "
                    "queue_size=%s, timestamp=%s",
                    session_id, session.total_audio_chunks,
                    audio_queue.size(session_id), timestamp
                )
                try:
                    analysis_service = get_analysis_service()
                    analysis_service.process_audio_chunk(session_id, chunk_data, timestamp)
                except Exception as e:
                    logger.error("分析音频块失败: %s", e)
            else:
                logger.warning("音频块放入队列失败: session_id=%s", session_id)

            return success

        except Exception as e:
            logger.error("处理audio_chunk事件失败: %s", e, exc_info=True)
            return False


_prepare_idempotency_lock = threading.RLock()
_prepare_idempotency_cache: Dict[str, Dict[str, Any]] = {}
_prepare_logical_cache: Dict[str, Dict[str, Any]] = {}
_PREPARE_LOGICAL_TTL_SEC = 15.0
_single_workflow_transition_lock = threading.RLock()


def _single_workflow_transition(handler):
    """Serialize replacement of the product's one global training workflow."""

    @functools.wraps(handler)
    def wrapped(data: Dict[str, Any]) -> Dict[str, Any]:
        with _single_workflow_transition_lock:
            return handler(data or {})

    return wrapped


def _is_strict_prepare_reservation(session: Session) -> bool:
    meta = session.metadata or {}
    status = getattr(getattr(session, 'status', None), 'value', None)
    return bool(
        status == 'created'
        and meta.get('strict_preflight')
        and meta.get('preflight_only')
        and not meta.get('capture_started')
    )


def _prepare_result_is_live(result: Dict[str, Any]) -> bool:
    session_id = result.get('session_id')
    if not session_id:
        return False
    session = get_session_manager().get_session(str(session_id))
    if session is None:
        return False
    return bool(session.is_active() or _is_strict_prepare_reservation(session))


def _idempotent_prepare(handler):
    """同一个前端 requestId 只创建一次训练，断线重试返回原结果。"""

    @functools.wraps(handler)
    def wrapped(data: Dict[str, Any]) -> Dict[str, Any]:
        payload = data or {}
        request_id = str(
            payload.get('requestId') or payload.get('operationId') or ''
        ).strip()
        student_id = payload.get('studentId') or payload.get('student_id')
        if not request_id:
            return handler(payload)

        cache_key = f'{student_id}:{request_id}'
        logical_key = f"{student_id}:{payload.get('mode') or 'training'}"
        with _prepare_idempotency_lock:
            cached = _prepare_idempotency_cache.get(cache_key)
            if cached is not None and _prepare_result_is_live(cached):
                result = dict(cached)
                result['idempotentReplay'] = True
                return result
            if cached is not None:
                _prepare_idempotency_cache.pop(cache_key, None)

            now = time.monotonic()
            logical = _prepare_logical_cache.get(logical_key)
            if logical is not None:
                age = now - float(logical.get('cached_at') or 0)
                logical_result = dict(logical.get('result') or {})
                if age <= _PREPARE_LOGICAL_TTL_SEC and _prepare_result_is_live(logical_result):
                    logical_result['idempotentReplay'] = True
                    logical_result['request_id'] = request_id
                    logger.info(
                        'prepare_training 复用在途准备: student=%s mode=%s session=%s age=%.2fs',
                        student_id,
                        payload.get('mode') or 'training',
                        logical_result.get('session_id'),
                        age,
                    )
                    return logical_result
                _prepare_logical_cache.pop(logical_key, None)

            result = handler(payload)
            if result.get('success'):
                result = dict(result)
                result['request_id'] = request_id
                _prepare_idempotency_cache[cache_key] = dict(result)
                _prepare_logical_cache[logical_key] = {
                    'cached_at': now,
                    'result': dict(result),
                }
                # 页面生命周期内最多保留最近 256 个请求，防止常驻服务无界增长。
                while len(_prepare_idempotency_cache) > 256:
                    _prepare_idempotency_cache.pop(
                        next(iter(_prepare_idempotency_cache))
                    )
            return result

    return wrapped


class PrepareTrainingHandler:
    """教师点击开始评估/训练：开训练 + 整场连续录制（warmup 起点，暂不分析）"""

    @staticmethod
    @_idempotent_prepare
    @_single_workflow_transition
    def handle(data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            student_id = data.get('studentId') or data.get('student_id')
            if student_id is None:
                return {'success': False, 'error': 'missing_student_id'}

            student_id = int(student_id)
            mode = data.get('mode') or 'training'
            requested_preflight = str(
                data.get('preflightMode') or data.get('preflight_mode') or 'legacy'
            ).strip().lower()
            if requested_preflight not in ('auto', 'strict', 'legacy'):
                raise ValueError('invalid_preflight_mode')
            from app.config import Config
            strict_preflight = bool(data.get('strictPreflight')) or (
                requested_preflight == 'strict'
                or (
                    requested_preflight == 'auto'
                    and Config.get_child_media_mode() == 'agent'
                )
            )
            behavior = get_behavior_service()
            session_manager = get_session_manager()

            # 产品部署只有一套教师/儿童/机器人。新建任何训练都先结束所有
            # 旧 workflow，而不只处理同一个学生；旧平板、旧标签页和误触
            # 都不能留下第二条录制或动作链路。
            superseded_sessions: List[str] = []
            cleanup_warnings: List[Dict[str, str]] = []
            for sess in list(session_manager.list_all_sessions()):
                meta = sess.metadata or {}
                strict_reservation = _is_strict_prepare_reservation(sess)
                if not sess.is_active() and not strict_reservation:
                    continue
                try:
                    if strict_reservation:
                        sess.cancel()
                        session_manager.update_session(sess)
                        session_manager.remove_session(sess.session_id)
                    else:
                        try:
                            finalize_recording_session(
                                sess.session_id, status='superseded'
                            )
                        except Exception as exc:
                            cleanup_warnings.append({
                                'sessionId': str(sess.session_id),
                                'error': f'finalize_recording:{exc}',
                            })
                        _close_runtime_session(
                            sess.session_id,
                            send_summary=False,
                            strict=False,
                        )
                    superseded_sessions.append(str(sess.session_id))
                    logger.info("prepare 前已关闭旧 workflow: session=%s", sess.session_id)
                except Exception as exc:
                    # Last-resort local eviction is safe here: the child Runtime
                    # also performs an atomic takeover when record/start receives
                    # the new sessionId.
                    cleanup_warnings.append({
                        'sessionId': str(sess.session_id),
                        'error': str(exc),
                    })
                    try:
                        session_manager.remove_session(sess.session_id)
                        superseded_sessions.append(str(sess.session_id))
                    except Exception:
                        pass

            superseded_trainings: List[str] = []
            list_active_training_ids = getattr(
                getattr(behavior, 'store', None),
                'list_active_training_ids',
                None,
            )
            active_training_ids = (
                list(list_active_training_ids())
                if callable(list_active_training_ids)
                else []
            )
            for old_training_id in active_training_ids:
                try:
                    behavior.finalize(str(old_training_id))
                    superseded_trainings.append(str(old_training_id))
                except Exception as exc:
                    cleanup_warnings.append({
                        'trainingSessionId': str(old_training_id),
                        'error': f'finalize_behavior:{exc}',
                    })

            training = behavior.open_training(
                student_id=student_id,
                metadata={
                    'source': 'prepare_training',
                    'mode': mode,
                },
            )
            training_session_id = training.training_session_id
            question_id = f"{training_session_id}_warmup"

            name, age = load_student_label(student_id)
            human_dir, n = allocate_human_dir_name(
                student_id=student_id,
                student_name=name,
                student_age=age,
            )

            session = session_manager.create_session(
                student_id=student_id,
                course_id=None,
                course_item_id=None,
                training_session_id=training_session_id,
                question_id=question_id,
                question_index=-1,
                metadata={
                    'warmup': True,
                    'continuous_recording': True,
                    'recording_mode': 'continuous',
                    'human_dir_name': human_dir,
                    'recording_n': n,
                    'source': 'prepare_training',
                    'mode': mode,
                    'strict_preflight': strict_preflight,
                    'preflight_only': strict_preflight,
                    'capture_started': not strict_preflight,
                },
            )
            if not strict_preflight:
                begin_recording_session(
                    media_session_id=session.session_id,
                    training_session_id=training_session_id,
                    student_id=student_id,
                    human_dir_name=human_dir,
                    n=n,
                )
                _refresh_session_paths(session)
                session.start()
                session_manager.update_session(session)

                try:
                    get_media_service().start_recording(
                        session.session_id,
                        student_id=student_id,
                    )
                except Exception as e:
                    logger.warning("连续录制 media_service 启动失败（儿童端仍可开 agent）: %s", e)

            # 故意不调用 analysis_service.start_session / behavior.open_window
            logger.info(
                "prepare_training 完成(连续): student=%s training=%s media=%s human=%s mode=%s",
                student_id, training_session_id, session.session_id, human_dir, mode
            )
            return {
                'success': True,
                'session_id': session.session_id,
                'training_session_id': training_session_id,
                'question_id': question_id,
                'mode': mode,
                'recording_mode': 'continuous',
                'human_dir_name': human_dir,
                'preflight_only': strict_preflight,
                'capture_started': not strict_preflight,
                'preflight_mode': 'strict' if strict_preflight else 'legacy',
                'superseded_session_ids': superseded_sessions,
                'superseded_training_ids': superseded_trainings,
                'cleanup_warnings': cleanup_warnings,
            }
        except Exception as e:
            logger.error("prepare_training 失败: %s", e, exc_info=True)
            return {'success': False, 'error': str(e)}


class CancelPrepareTrainingHandler:
    """选课页返回：停止整场连续录制（此时通常仍为 warmup），不 finalize 训练"""

    @staticmethod
    def handle(data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            student_id = data.get('studentId') or data.get('student_id')
            training_session_id = (
                data.get('trainingSessionId') or data.get('training_session_id')
            )
            behavior = get_behavior_service()
            session_manager = get_session_manager()

            if student_id is not None:
                student_id = int(student_id)
            if not training_session_id and student_id is not None:
                training_session_id = behavior.get_active_training_id(student_id)

            stopped: List[str] = []
            failed: List[Dict[str, str]] = []
            sessions = []
            if training_session_id:
                sessions = [
                    s for s in session_manager.list_all_sessions()
                    if getattr(s, 'training_session_id', None) == training_session_id
                    and (
                        student_id is None
                        or getattr(s, 'student_id', None) == student_id
                    )
                ]
            elif student_id is not None:
                sessions = list(session_manager.get_sessions_by_student(student_id))

            for sess in sessions:
                meta = sess.metadata or {}
                strict_reservation = _is_strict_prepare_reservation(sess)
                if not sess.is_active() and not strict_reservation:
                    continue
                # 连续录制：cancel 可停仍为 warmup 的整场 session
                if not (meta.get('warmup') or meta.get('continuous_recording')):
                    continue
                try:
                    if strict_reservation:
                        # Strict prepare has no formal recording or Runtime
                        # session yet; cancel only the reserved application
                        # session and do not invent media artifacts.
                        sess.cancel()
                        session_manager.update_session(sess)
                        session_manager.remove_session(sess.session_id)
                    else:
                        finalize_recording_session(sess.session_id, status='cancelled')
                        _close_runtime_session(
                            sess.session_id,
                            send_summary=False,
                            strict=True,
                        )
                    stopped.append(sess.session_id)
                except Exception as e:
                    logger.warning("cancel prepare 关闭连续录制失败: %s", e)
                    failed.append({
                        'sessionId': sess.session_id,
                        'error': str(e),
                    })

            logger.info(
                "cancel_prepare_training: student=%s training=%s stopped=%s",
                student_id, training_session_id, stopped
            )
            return {
                'success': not failed,
                'trainingSessionId': training_session_id,
                'stoppedSessions': stopped,
                'failedSessions': failed,
                'error': (
                    'cancel_runtime_cleanup_failed' if failed else None
                ),
            }
        except Exception as e:
            logger.error("cancel_prepare_training 失败: %s", e, exc_info=True)
            return {'success': False, 'error': str(e)}


class StopRecordingHandler:
    """处理stop_recording事件"""

    @staticmethod
    def handle(data: Dict[str, Any]) -> bool:
        try:
            session_id = data.get('sessionId')

            if not session_id:
                student_id = data.get('studentId')
                course_id = data.get('courseId')
                item_id = data.get('itemId')

                if student_id is not None and course_id is not None:
                    session_manager = get_session_manager()
                    sessions = session_manager.get_sessions_by_student(student_id)

                    matching_session = None
                    for s in sessions:
                        if s.course_id == course_id:
                            if item_id is None:
                                if s.course_item_id is None and s.is_active():
                                    matching_session = s
                                    break
                            else:
                                if s.course_item_id == item_id and s.is_active():
                                    matching_session = s
                                    break

                    if matching_session:
                        session_id = matching_session.session_id
                    else:
                        logger.warning(
                            "无法找到匹配的会话: studentId=%s, courseId=%s, itemId=%s",
                            student_id, course_id, item_id
                        )
                        return False
                else:
                    logger.warning("stop_recording事件缺少sessionId或必要的查找字段")
                    return False

            session_manager = get_session_manager()
            session = session_manager.get_session(session_id)

            if not session:
                logger.warning("stop_recording事件引用的会话不存在: session_id=%s", session_id)
                return False

            # 关窗（若有）
            try:
                behavior = get_behavior_service()
                ts_id = getattr(session, 'training_session_id', None)
                qid = getattr(session, 'question_id', None)
                summary = _close_runtime_session(session_id, send_summary=True)
                if ts_id and qid:
                    behavior.close_window(ts_id, qid, analysis_summary=summary)
            except Exception as e:
                logger.error("stop_recording 收尾失败: %s", e, exc_info=True)
                return False

            logger.info("停止录制: session_id=%s", session_id)
            return True

        except Exception as e:
            logger.error("处理stop_recording事件失败: %s", e, exc_info=True)
            return False


_finalize_idempotency_lock = threading.RLock()
_finalize_idempotency_cache: Dict[str, Dict[str, Any]] = {}


def _idempotent_finalize(handler):
    """相同 operationId 的 finalize 重试只返回第一次聚合结果。"""

    @functools.wraps(handler)
    def wrapped(data: Dict[str, Any]) -> Dict[str, Any]:
        payload = data or {}
        operation_id = str(
            payload.get('operationId') or payload.get('requestId') or ''
        ).strip()
        training_id = str(
            payload.get('trainingSessionId')
            or payload.get('training_session_id')
            or ''
        ).strip()
        if not operation_id or not training_id:
            return handler(payload)

        cache_key = f'{training_id}:{operation_id}'
        with _finalize_idempotency_lock:
            cached = _finalize_idempotency_cache.get(cache_key)
            if cached is not None:
                result = dict(cached)
                result['idempotentReplay'] = True
                return result
            result = handler(payload)
            if result.get('success'):
                _finalize_idempotency_cache[cache_key] = dict(result)
                while len(_finalize_idempotency_cache) > 256:
                    _finalize_idempotency_cache.pop(
                        next(iter(_finalize_idempotency_cache))
                    )
            return result

    return wrapped


class FinalizeTrainingHandler:
    """整次训练 finalize：停整场连续录制 + 回填 timeline"""

    @staticmethod
    @_idempotent_finalize
    def handle(data: Dict[str, Any]) -> Dict[str, Any]:
        behavior = get_behavior_service()
        session_manager = get_session_manager()

        training_session_id = data.get('trainingSessionId') or data.get('training_session_id')
        student_id = data.get('studentId')

        if not training_session_id and student_id is not None:
            training_session_id = behavior.get_active_training_id(int(student_id))

        if not training_session_id:
            return {
                'success': False,
                'error': 'missing_training_session_id',
                'trainingSessionId': None,
            }

        training_session_id = str(training_session_id)
        normalized_student_id = (
            int(student_id) if student_id is not None else None
        )
        get_training = getattr(behavior, 'get_training', None)
        if callable(get_training):
            training_record = get_training(training_session_id)
            if training_record is None:
                return {
                    'success': False,
                    'error': 'training_session_not_found',
                    'trainingSessionId': training_session_id,
                }
            if (
                normalized_student_id is not None
                and getattr(training_record, 'student_id', None)
                != normalized_student_id
            ):
                logger.warning(
                    '拒绝 finalize 非所属训练: training=%s student=%s actual=%s',
                    training_session_id,
                    normalized_student_id,
                    getattr(training_record, 'student_id', None),
                )
                return {
                    'success': False,
                    'error': 'training_student_mismatch',
                    'trainingSessionId': training_session_id,
                }

        runtime_ids: List[str] = []
        stopped_runtime_ids: List[str] = []
        cleanup_failures: List[Dict[str, str]] = []
        human_dir_name = None
        try:
            # trainingSessionId 是破坏性收尾操作的主键；studentId 只校验归属。
            # 旧教师页不得因为学生相同而关闭该学生后来开启的新训练。
            for sess in list(session_manager.list_all_sessions()):
                if (
                    getattr(sess, 'training_session_id', None)
                    != training_session_id
                ):
                    continue
                if (
                    normalized_student_id is not None
                    and getattr(sess, 'student_id', None)
                    != normalized_student_id
                ):
                    logger.warning(
                        '拒绝 finalize 非所属训练: training=%s student=%s actual=%s',
                        training_session_id,
                        normalized_student_id,
                        getattr(sess, 'student_id', None),
                    )
                    return {
                        'success': False,
                        'error': 'runtime_session_student_mismatch',
                        'trainingSessionId': training_session_id,
                    }
                runtime_ids.append(sess.session_id)

            for rid in runtime_ids:
                sess = session_manager.get_session(rid)
                qid = getattr(sess, 'question_id', None) if sess else None
                is_warmup = bool((sess.metadata or {}).get('warmup')) if sess else False
                if sess:
                    human_dir_name = (sess.metadata or {}).get('human_dir_name') or human_dir_name
                if sess and (sess.metadata or {}).get('strict_preflight') and not (sess.metadata or {}).get('capture_started'):
                    # A strict prepare may be finalized before the readiness
                    # gate starts capture.  There is no timeline/Runtime
                    # handle to stop in this branch.
                    try:
                        if sess.status == SessionStatus.CREATED:
                            sess.status = SessionStatus.COMPLETED
                        session_manager.update_session(sess)
                        session_manager.remove_session(rid)
                        stopped_runtime_ids.append(rid)
                    except Exception as e:
                        cleanup_failures.append({
                            'sessionId': rid,
                            'error': f'strict_preflight_finalize:{e}',
                        })
                    continue
                try:
                    finalize_recording_session(rid, status='finalized')
                except Exception as e:
                    logger.warning("finalize timeline 失败: %s", e)
                    cleanup_failures.append({
                        'sessionId': rid,
                        'error': f'finalize_recording:{e}',
                    })
                try:
                    summary = _close_runtime_session(
                        rid,
                        send_summary=False,
                        # A terminal class exit must clear local recording
                        # state even when media/analyzer cleanup is degraded.
                        strict=False,
                    )
                    if qid and not is_warmup:
                        behavior.close_window(
                            training_session_id,
                            qid,
                            analysis_summary=summary,
                        )
                    stopped_runtime_ids.append(rid)
                except Exception as e:
                    logger.warning("finalize runtime 收尾失败: %s", e)
                    cleanup_failures.append({
                        'sessionId': rid,
                        'error': str(e),
                    })
        except Exception as e:
            logger.error("finalize 收尾 runtime session 失败: %s", e, exc_info=True)
            cleanup_failures.append({
                'sessionId': '',
                'error': str(e),
            })

        try:
            summary = behavior.finalize(training_session_id)
        except Exception as e:
            logger.error("finalize 聚合失败: %s", e, exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'trainingSessionId': training_session_id,
            }

        return {
            'success': True,
            'trainingSessionId': training_session_id,
            'status': 'FINALIZED',
            'stoppedRuntimeSessions': stopped_runtime_ids,
            'humanDirName': human_dir_name,
            'recordingMode': 'continuous',
            'cleanupWarnings': cleanup_failures,
            'summaryPreview': {
                'window_count': summary.window_count,
                'attention_avg': (summary.attention or {}).get('avg_score'),
                'limitations': summary.limitations,
            },
        }
