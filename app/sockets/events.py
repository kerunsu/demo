"""
WebSocket事件处理
使用Flask-SocketIO装饰器注册事件处理函数

事件列表：
- connect/disconnect: 连接管理
- client_presence: 教师/儿童页面登记在线（连接 + 周期心跳）
- prepare_training / cancel_prepare_training: 开始评估/训练即开 warmup 录制
- readiness_start / readiness_cancel / readiness_child_report: 开课就绪门
- readiness_update / readiness_complete: 录制门状态与正式采集命令
- play_resource: 播放资源（教师端 -> 儿童端）
- video_frame: 视频帧数据（儿童端 -> 后端）
- audio_chunk: 音频块数据（儿童端 -> 后端）
- stop_recording: 停止录制（教师端 -> 后端 -> 儿童端）
- match_result: 匹配结果（后端 -> 教师端）[新增]
- attention_update: 注意力更新（后端 -> 教师端）[新增]
- session_summary: 会话总结（后端 -> 教师端）[新增]
- trigger_action: 触发动作（后端 -> 儿童端）[新增]
- analysis_result: 分析结果（后端 -> 教师端）[新增]
"""
from flask import current_app, has_app_context, request, session
from flask_socketio import emit, join_room, leave_room
from app.sockets.handlers import (
    PlayResourceHandler,
    VideoFrameHandler,
    AudioChunkHandler,
    StopRecordingHandler,
    FinalizeTrainingHandler,
    PrepareTrainingHandler,
    CancelPrepareTrainingHandler,
    start_preflight_capture,
)
from app.config import Config
from app.utils.logger import setup_logger
from app.sockets.robot_events import register_robot_events
from app.services.readiness_service import get_readiness_service
from app.services.teacher_control import get_teacher_control_registry
from collections import OrderedDict
import threading
import time
import uuid
from typing import Any, Dict, Optional

logger = setup_logger('socket_events')

_PLAY_REQUEST_TTL_SECONDS = 300.0
_PLAY_REQUEST_CACHE_LIMIT = 2048
_play_request_lock = threading.RLock()
_play_request_cache = OrderedDict()
_TEACHER_RATING_TTL_SECONDS = 300.0
_TEACHER_RATING_CACHE_LIMIT = 512
_teacher_rating_lock = threading.RLock()
_teacher_rating_cache = OrderedDict()
_DEFERRED_QUESTION_TTL_SECONDS = 60.0
_PENDING_ITEM_QUESTION_TTL_SECONDS = 45.0
# Hard rule: pairing/ordering item switch must ask. Busy-reservation retries
# for questions (0.1s * N); keep high enough to outlast greetings/praise.
_INTERACTIVE_QUESTION_BUSY_RETRIES = 80
_INTERACTIVE_QUESTION_BUSY_RETRY_SEC = 0.1
# Cap multimodal lead-in so item-switch asks feel immediate.
_INTERACTIVE_QUESTION_AUDIO_DELAY_CAP_MS = 80
_deferred_question_lock = threading.RLock()
_deferred_ordering_questions: Dict[str, Dict[str, Any]] = {}
# Latest-wins pending ask per runtime session (pairing/ordering item switch).
_pending_interactive_questions: Dict[str, Dict[str, Any]] = {}
_interactive_input_state: Dict[str, Dict[str, Any]] = {}
_socketio_server = None


def _authenticated_teacher() -> Optional[Dict[str, Any]]:
    """Read identity only from Flask's signed session cookie."""
    teacher_id = session.get('teacher_id')
    username = str(session.get('teacher_username') or '').strip()
    try:
        teacher_id = int(teacher_id)
    except (TypeError, ValueError):
        return None
    return {'teacherId': teacher_id, 'username': username}


def _training_session_id_for_payload(data: Optional[Dict[str, Any]]) -> Optional[str]:
    payload = data if isinstance(data, dict) else {}
    training_id = (
        payload.get('trainingSessionId')
        or payload.get('training_session_id')
    )
    if training_id:
        return str(training_id)
    runtime_id = payload.get('sessionId') or payload.get('session_id')
    if not runtime_id:
        return None
    try:
        from app.session import get_session_manager

        runtime = get_session_manager().get_session(str(runtime_id))
        resolved = getattr(runtime, 'training_session_id', None) if runtime else None
        return str(resolved) if resolved else None
    except Exception:
        return None


def _runtime_session_ids_for_training(training_session_id: Any) -> list:
    training_id = str(training_session_id or '').strip()
    if not training_id:
        return []
    try:
        from app.session import get_session_manager

        return [
            str(runtime.session_id)
            for runtime in get_session_manager().list_active_sessions()
            if str(getattr(runtime, 'training_session_id', '') or '')
            == training_id
        ]
    except Exception:
        return []


def _teacher_control_access(
    data: Optional[Dict[str, Any]],
    *,
    claim: bool = False,
) -> Dict[str, Any]:
    teacher = _authenticated_teacher()
    if not teacher:
        return {
            'ok': False,
            'writable': False,
            'error': 'teacher_auth_required',
        }
    training_id = _training_session_id_for_payload(data)
    if not training_id:
        return {
            'ok': False,
            'writable': False,
            'error': 'training_session_id_missing',
            'teacher': teacher,
        }
    registry = get_teacher_control_registry()
    operation = registry.claim if claim else registry.authorize
    kwargs = {
        'teacher_id': teacher['teacherId'],
        'sid': request.sid,
    }
    if claim:
        kwargs['teacher_username'] = teacher['username']
    result = operation(training_id, **kwargs)
    if (
        not claim
        and result.get('error') == 'control_lease_missing'
    ):
        # 自愈：lease 因过期/崩溃丢失时由当前连接自动重建。只有 lease
        # 确实不存在（而非被其他教师持有）才会走到这里；重建用本连接
        # 的 sid，不会抢走其他教师控制权。
        logger.info(
            "control_lease_missing，自动重建租约: training=%s sid=%s",
            training_id, request.sid,
        )
        kwargs['teacher_username'] = teacher['username']
        result = registry.claim(training_id, **kwargs)
    result['teacher'] = teacher
    result['trainingSessionId'] = training_id
    return result


def _control_rejection(access: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'success': False,
        'error': access.get('error') or 'observer_read_only',
        'controlRole': (
            (access.get('lease') or {}).get('controlRole') or 'observer'
        ),
        'lease': access.get('lease'),
        'trainingSessionId': access.get('trainingSessionId'),
    }


def _notify_replaced_teacher(access: Dict[str, Any]) -> None:
    """同一教师的新连接接管后，让被替换的旧连接立即降级为 observer。

    claim 返回的 replacedSid 指向刚被本连接顶替的旧 socket；
    旧窗口据此切到只读观察模式，避免其 UI 仍显示 controller 但操作全被拒。
    """
    replaced_sid = access.get('replacedSid')
    if not replaced_sid or replaced_sid == request.sid:
        return
    try:
        emit(
            'teacher_control_state',
            {
                'success': False,
                'error': 'control_taken_over',
                'controlRole': 'observer',
                'trainingSessionId': access.get('trainingSessionId'),
            },
            to=replaced_sid,
        )
        logger.info("已通知被接管教师窗口降级: old_sid=%s", replaced_sid)
    except Exception as e:  # noqa: BLE001
        logger.warning("通知旧窗口降级失败: %s", e)


def _teacher_write_allowed(event_name: str, data: Optional[Dict[str, Any]]) -> bool:
    access = _teacher_control_access(data)
    if access.get('ok') and access.get('writable'):
        return True
    emit('teacher_control_rejected', {
        **_control_rejection(access),
        'event': event_name,
    })
    return False


def _prune_play_request_cache(now: float) -> None:
    expired = [
        key for key, entry in _play_request_cache.items()
        if float(entry.get('expiresAt') or 0) <= now
    ]
    for key in expired:
        _play_request_cache.pop(key, None)
    while len(_play_request_cache) > _PLAY_REQUEST_CACHE_LIMIT:
        _play_request_cache.popitem(last=False)


def _claim_play_request(
    request_id: str,
    *,
    requester_sid: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return an existing entry, or atomically claim a new requestId."""
    now = time.monotonic()
    with _play_request_lock:
        _prune_play_request_cache(now)
        existing = _play_request_cache.get(request_id)
        if existing:
            if requester_sid:
                # A reconnect retry owns the readiness reply from now on.
                existing['requesterSid'] = str(requester_sid)
            _play_request_cache.move_to_end(request_id)
            return dict(existing)
        _play_request_cache[request_id] = {
            'status': 'processing',
            'expiresAt': now + _PLAY_REQUEST_TTL_SECONDS,
            'requesterSid': requester_sid,
        }
        _prune_play_request_cache(now)
        return None


def _update_play_request(
    request_id: str,
    *,
    behavior_id: Optional[str] = None,
    requester_sid: Optional[str] = None,
    ack: Optional[Dict[str, Any]] = None,
    content_forward_data: Optional[Dict[str, Any]] = None,
    child_room: Optional[str] = None,
    child_sid: Optional[str] = None,
    is_aux: Optional[bool] = None,
    interaction_context: Optional[Dict[str, Any]] = None,
    keep: bool = True,
) -> None:
    with _play_request_lock:
        if not keep:
            _play_request_cache.pop(request_id, None)
            return
        entry = _play_request_cache.setdefault(request_id, {})
        entry['expiresAt'] = time.monotonic() + _PLAY_REQUEST_TTL_SECONDS
        if behavior_id:
            entry['behaviorId'] = str(behavior_id)
        if requester_sid:
            entry['requesterSid'] = str(requester_sid)
        if is_aux is not None:
            entry['isAux'] = bool(is_aux)
        if interaction_context is not None:
            entry['interactionContext'] = dict(interaction_context)
        if content_forward_data is not None and not bool(is_aux):
            entry['contentForwardData'] = dict(content_forward_data)
            entry['childRoom'] = str(child_room or '')
            entry['childSid'] = str(child_sid or '')
        if ack is not None:
            entry['status'] = 'completed'
            entry['ack'] = dict(ack)
        _play_request_cache.move_to_end(request_id)


def _emit_play_resource_ack(ack: Dict[str, Any]) -> None:
    """发送 play_resource_ack，并把结果写入全量交互审计时间线。

    教师端“点了没反应”的每个分支（lease 拒绝 / 幂等重放 / 行为繁忙 /
    启动失败 / 成功）都经由此处。ack 落盘后可直接对照 question 推进与
    行为 busy 状态，无需再依赖控制台现场。
    """
    try:
        from app.behavior.audit_timeline import record_audit_event
        record_audit_event(
            'play_resource_ack',
            training_session_id=ack.get('trainingSessionId'),
            runtime_session_id=ack.get('sessionId'),
            question_id=ack.get('questionId'),
            request_id=ack.get('requestId'),
            behavior_id=ack.get('behaviorId') or ack.get('interactionId'),
            actor='server',
            source='server',
            category='course_interaction',
            phase='response',
            status=(
                'accepted' if ack.get('accepted')
                else str(ack.get('reason') or 'rejected')
            ),
            modality=ack.get('modality'),
            degraded=not bool(ack.get('accepted')),
            error=ack.get('error') or ack.get('reason'),
            details={
                'reason': ack.get('reason'),
                'message': ack.get('message'),
                'busy': bool(ack.get('busy')),
                'remainingMs': ack.get('remainingMs'),
                'activeBehaviorId': ack.get('activeBehaviorId'),
                'isAux': bool(ack.get('isAux')),
            },
        )
    except Exception:
        pass
    emit('play_resource_ack', ack)


def _interaction_context_for_behavior(behavior_id: Any) -> Optional[Dict[str, Any]]:
    target = str(behavior_id or '').strip()
    if not target:
        return None
    with _play_request_lock:
        for entry in reversed(list(_play_request_cache.values())):
            if str(entry.get('behaviorId') or '') == target:
                context = entry.get('interactionContext')
                return dict(context) if isinstance(context, dict) else None
    return None


def _record_interaction(event_type: str, context: Optional[Dict[str, Any]], **kwargs):
    if not isinstance(context, dict) or not context.get('trainingSessionId'):
        return None
    try:
        from app.behavior import get_behavior_service

        behavior = get_behavior_service()
        if event_type in ('question_presented', 'hint'):
            snapshot = behavior.get_interaction_snapshot(
                str(context['trainingSessionId']), context.get('questionId')
            )
            inferred_no_response = (
                snapshot.get('firstResponseAtMs') is None
                and snapshot.get('lastEventType') not in (None, 'no_response')
                and (
                    event_type == 'hint'
                    or int(snapshot.get('questionPresentationCount') or 0) > 0
                )
            )
            if inferred_no_response:
                behavior.record_interaction(
                    'no_response',
                    str(context['trainingSessionId']),
                    question_id=context.get('questionId'),
                    runtime_session_id=context.get('sessionId'),
                    request_id=context.get('requestId'),
                    behavior_id=context.get('behaviorId'),
                    actor='server',
                    metadata={'inferredFrom': event_type},
                )
        return behavior.record_interaction(
            event_type,
            str(context['trainingSessionId']),
            question_id=context.get('questionId'),
            runtime_session_id=context.get('sessionId'),
            request_id=context.get('requestId'),
            behavior_id=context.get('behaviorId'),
            **kwargs,
        )
    except Exception as exc:
        logger.warning('interaction timeline write failed event=%s: %s', event_type, exc)
        return None


def _record_latency_modality_callback(
    data: Optional[Dict[str, Any]],
    *,
    phase: str,
    modality: Optional[str] = None,
    actor: str = 'child',
    source: str = 'socketio',
):
    """Record the Server receive time of an endpoint readiness/start callback.

    This is deliberately separate from the browser's asynchronous audit upload:
    the diagnostic report must not count telemetry upload time as playback delay.
    """
    payload = dict(data or {})
    behavior_id = (
        payload.get('behaviorId')
        or payload.get('behavior_id')
        or payload.get('interactionId')
        or payload.get('sequenceId')
    )
    context = _interaction_context_for_behavior(behavior_id) or {}
    training_session_id = (
        payload.get('trainingSessionId')
        or payload.get('training_session_id')
        or context.get('trainingSessionId')
        or _training_session_id_for_payload(payload)
    )
    if not training_session_id:
        return None
    normalized_modality = str(
        modality or payload.get('modality') or 'unknown'
    ).strip()
    if normalized_modality == 'speech':
        normalized_modality = 'audio'
    client_timestamp = (
        payload.get('actualAtClientMs')
        if phase == 'started'
        else payload.get('readyAtClientMs')
    )
    try:
        from app.behavior.audit_timeline import record_audit_event

        return record_audit_event(
            f'latency.modality_{phase}_callback',
            training_session_id=training_session_id,
            runtime_session_id=(
                payload.get('sessionId')
                or payload.get('session_id')
                or context.get('sessionId')
            ),
            question_id=(
                payload.get('questionId')
                or payload.get('question_id')
                or context.get('questionId')
            ),
            request_id=(
                payload.get('requestId')
                or payload.get('request_id')
                or context.get('requestId')
            ),
            behavior_id=behavior_id or context.get('behaviorId'),
            actor=actor,
            source=source,
            category='latency',
            phase=phase,
            status=str(payload.get('status') or phase),
            modality=normalized_modality,
            client_timestamp=client_timestamp,
            degraded=str(payload.get('status') or '').lower() in {
                'error', 'failed', 'dropped', 'timeout'
            },
            error=payload.get('error') or payload.get('errorMessage'),
            details={
                'commandReceivedAtClientMs': payload.get(
                    'commandReceivedAtClientMs'
                ),
                'readyAtClientMs': payload.get('readyAtClientMs'),
                'actualAtClientMs': payload.get('actualAtClientMs'),
                'plannedAtClientMs': payload.get('plannedAtClientMs'),
                'entryId': payload.get('entryId') or payload.get('entry_id'),
                'filePath': payload.get('filePath') or payload.get('file_path'),
                'readinessKey': payload.get('readinessKey'),
                # Resource transitions report the real browser-side stages
                # (preflight, decode/load, paint and crossfade).  Keeping this
                # nested object intact lets the Server console explain a slow
                # lower-screen switch without trusting cross-machine clocks.
                'timing': payload.get('timing') if isinstance(
                    payload.get('timing'), dict
                ) else {},
            },
        )
    except Exception:
        logger.debug(
            'latency modality callback audit failed phase=%s modality=%s',
            phase,
            normalized_modality,
            exc_info=True,
        )
        return None
def _interaction_context_from_payload(
    data: Optional[Dict[str, Any]], event_type: str
) -> Optional[Dict[str, Any]]:
    payload = dict(data or {})
    training_id = _training_session_id_for_payload(payload)
    runtime_id = payload.get('sessionId') or payload.get('session_id')
    question_id = payload.get('questionId') or payload.get('question_id')
    if runtime_id and (not training_id or not question_id):
        try:
            from app.behavior import get_behavior_service

            current = get_behavior_service().get_current_context_for_runtime(
                str(runtime_id)
            )
            training_id = training_id or current.get('training_session_id')
            question_id = question_id or current.get('question_id')
        except Exception:
            pass
    if not training_id:
        return None
    return {
        'trainingSessionId': str(training_id),
        'sessionId': str(runtime_id) if runtime_id else None,
        'questionId': str(question_id) if question_id else None,
        'requestId': payload.get('requestId') or payload.get('request_id'),
        'behaviorId': (
            payload.get('behaviorId') or payload.get('behavior_id')
            or payload.get('interactionId')
        ),
        'eventType': event_type,
    }


def _replay_cached_content(socketio, entry: Dict[str, Any]) -> bool:
    """Re-deliver only idempotent content after a teacher reconnect."""
    if not isinstance(entry, dict) or bool(entry.get('isAux')):
        return False
    payload = entry.get('contentForwardData')
    if not isinstance(payload, dict):
        return False
    session_id = payload.get('sessionId') or payload.get('session_id')
    child_sid = _child_owner_for_session(session_id)
    if not child_sid:
        return False
    socketio.emit('play_resource', dict(payload), to=child_sid)
    return True


def _purge_runtime_delivery_state(
    session_ids: Optional[list] = None,
    *,
    training_session_id: Optional[str] = None,
) -> None:
    """Forget ended runtime delivery state without dropping child presence."""
    sessions = {str(value) for value in (session_ids or []) if value}
    training_id = str(training_session_id or '').strip() or None
    with _play_request_lock:
        for request_id, entry in list(_play_request_cache.items()):
            content = entry.get('contentForwardData')
            identity = _child_identity(content) if isinstance(content, dict) else {}
            if (
                identity.get('sessionId') in sessions
                or (
                    training_id
                    and identity.get('trainingSessionId') == training_id
                )
            ):
                _play_request_cache.pop(request_id, None)
    with _deferred_question_lock:
        for session_id in sessions:
            _deferred_ordering_questions.pop(session_id, None)
            pending = _pending_interactive_questions.pop(session_id, None)
            timer = (pending or {}).get('retryTimer')
            if timer is not None:
                timer.cancel()
    with _presence_lock:
        for session_id in sessions:
            _child_session_owners.pop(session_id, None)
        for sid, binding in list(_child_sid_bindings.items()):
            if (
                str(binding.get('sessionId') or '') in sessions
                or (
                    training_id
                    and str(binding.get('trainingSessionId') or '')
                    == training_id
                )
            ):
                _child_sid_bindings.pop(sid, None)
                _child_sync_attempted_sids.discard(sid)


def _prune_teacher_rating_cache(now: float) -> None:
    expired = [
        key
        for key, entry in _teacher_rating_cache.items()
        if float(entry.get('expiresAt') or 0) <= now
    ]
    for key in expired:
        _teacher_rating_cache.pop(key, None)
    while len(_teacher_rating_cache) > _TEACHER_RATING_CACHE_LIMIT:
        _teacher_rating_cache.popitem(last=False)


def _process_teacher_rating(
    data: Optional[Dict[str, Any]],
    *,
    behavior_service=None,
) -> Dict[str, Any]:
    """Persist one rating exactly once and return a correlated ACK."""
    payload = dict(data or {})
    request_id = str(
        payload.get('requestId') or payload.get('request_id') or ''
    ).strip()
    training_session_id = str(
        payload.get('trainingSessionId')
        or payload.get('training_session_id')
        or ''
    ).strip()
    question_id = (
        payload.get('questionId') or payload.get('question_id')
    )
    fingerprint = (
        training_session_id,
        str(question_id or ''),
        repr(payload.get('rating')),
    )

    if not request_id:
        return {
            'success': False,
            'trainingSessionId': training_session_id or None,
            'questionId': question_id,
            'requestId': None,
            'error': 'request_id_missing',
        }

    now = time.monotonic()
    with _teacher_rating_lock:
        _prune_teacher_rating_cache(now)
        cached = _teacher_rating_cache.get(request_id)
        if cached is not None:
            if cached.get('fingerprint') != fingerprint:
                return {
                    'success': False,
                    'trainingSessionId': training_session_id or None,
                    'questionId': question_id,
                    'requestId': request_id,
                    'error': 'request_id_conflict',
                }
            result = dict(cached.get('ack') or {})
            result['idempotentReplay'] = True
            _teacher_rating_cache.move_to_end(request_id)
            return result

        try:
            raw_rating = payload.get('rating')
            if isinstance(raw_rating, bool):
                raise ValueError('rating_must_be_integer_1_to_5')
            rating = int(raw_rating)
            if raw_rating is None or float(raw_rating) != rating:
                raise ValueError('rating_must_be_integer_1_to_5')
            if not training_session_id:
                raise ValueError('training_session_id_missing')

            if behavior_service is None:
                from app.behavior import get_behavior_service

                behavior_service = get_behavior_service()
            response_metrics = (
                behavior_service.get_response_metrics(
                    training_session_id, question_id
                )
                if hasattr(behavior_service, 'get_response_metrics')
                else {}
            )
            authoritative_response_ms = response_metrics.get(
                'responseMsFromFirstQuestion'
            )
            window = behavior_service.record_teacher_rating(
                training_session_id,
                question_id,
                rating=rating,
                response_ms=(authoritative_response_ms
                    if authoritative_response_ms is not None
                    else payload.get('responseMs')),
                response_source=(
                    'server_question_audio_end'
                    if authoritative_response_ms is not None
                    else payload.get('responseSource') or 'teacher_advance'
                ),
                advance_source=payload.get('advanceSource') or 'manual',
                client_recorded_at=payload.get('clientRecordedAt'),
            )
            saved = (window.task_metrics or {}).get('teacher_rating') or {}
            if hasattr(behavior_service, 'record_interaction'):
                behavior_service.record_interaction(
                    'rating', training_session_id,
                    question_id=window.question_id,
                    runtime_session_id=(
                        payload.get('sessionId') or payload.get('session_id')
                    ),
                    request_id=request_id,
                    actor='teacher',
                    client_timestamp=payload.get('clientRecordedAt'),
                    metadata={
                        'rating': saved.get('rating'),
                        'responseMs': saved.get('response_ms'),
                        'responseSource': saved.get('response_source'),
                    },
                )
            result = {
                'success': True,
                'trainingSessionId': training_session_id,
                'questionId': window.question_id,
                'rating': saved.get('rating'),
                'normalizedScore': saved.get('normalized_score'),
                'updatedAt': saved.get('updated_at'),
                'responseMs': saved.get('response_ms'),
                'responseSource': saved.get('response_source'),
                'requestId': request_id,
            }
        except Exception as exc:
            result = {
                'success': False,
                'trainingSessionId': training_session_id or None,
                'questionId': question_id,
                'requestId': request_id,
                'error': str(exc),
            }

        _teacher_rating_cache[request_id] = {
            'fingerprint': fingerprint,
            'ack': dict(result),
            'expiresAt': now + _TEACHER_RATING_TTL_SECONDS,
        }
        _teacher_rating_cache.move_to_end(request_id)
        _prune_teacher_rating_cache(now)
        return result


def should_process_play_audio(
    *,
    audio_pending: bool,
    skip_robot_due_to_busy: bool,
    wants_aux: bool,
    is_aux_op: bool,
) -> bool:
    """Audio is part of one atomic behavior and never survives a busy reject."""
    return bool(audio_pending and not skip_robot_due_to_busy)


def should_reject_atomic_audio(
    *,
    wants_aux: bool,
    audio_details: Optional[Dict[str, Any]],
) -> bool:
    """Return true when a required correlated utterance was not dispatched."""
    details = audio_details if isinstance(audio_details, dict) else {}
    if not wants_aux or bool(details.get('deferred')):
        return False
    return (
        not bool(details.get('triggered'))
        or int(details.get('dispatchCount') or 0) <= 0
    )


def _remaining_behavior_start_delay_ms(robot_result: Dict[str, Any]) -> int:
    """Convert the shared absolute anchor to a fresh relative client delay."""
    start_at = (robot_result or {}).get('startAtEpochMs')
    if start_at is None:
        return max(0, int((robot_result or {}).get('scheduledDelayMs') or 0))
    try:
        return max(0, int(round(float(start_at) - time.time() * 1000.0)))
    except (TypeError, ValueError):
        return max(0, int((robot_result or {}).get('scheduledDelayMs') or 0))


def _build_child_session_forward(
    data: Optional[Dict[str, Any]],
) -> Optional[tuple]:
    """Normalize a payload and its exact child room, or reject it."""
    payload = dict(data or {})
    session_id = payload.get('sessionId') or payload.get('session_id')
    if not session_id:
        return None
    session_id = str(session_id)
    payload['sessionId'] = session_id
    payload['session_id'] = session_id
    return payload, f'session_{session_id}_child'


def _is_deferred_ordering_question(
    data: Optional[Dict[str, Any]],
) -> bool:
    payload = data if isinstance(data, dict) else {}
    course_type = str(
        payload.get('courseType') or payload.get('course_type') or ''
    ).strip().lower()
    aux = payload.get('aux')
    page_context = payload.get('pageContext')
    if not isinstance(page_context, dict):
        page_context = payload.get('page_context')
    if not isinstance(page_context, dict):
        page_context = {}
    has_rule_context = bool(
        (payload.get('category') or page_context.get('category'))
        and (payload.get('rule') or page_context.get('rule'))
    )
    return bool(
        course_type in ('ordering', 'sequencing')
        and isinstance(aux, dict)
        and aux.get('question') is True
        and not has_rule_context
    )


def _start_or_defer_course_behavior(
    robot_service,
    event_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Do not enqueue the known-premature ordering question visual."""
    if _is_deferred_ordering_question(event_data):
        behavior_id = str(
            event_data.get('behaviorId')
            or event_data.get('behavior_id')
            or event_data.get('interactionId')
            or ''
        )
        return {
            'success': True,
            'skipped': True,
            'deferred': True,
            'behaviorId': behavior_id or None,
            'sequenceId': behavior_id or None,
            'scheduledDelayMs': 0,
            'remainingMs': 0,
        }
    return robot_service.trigger_course_event(event_data)


def _remember_deferred_ordering_question(
    session_id: str,
    *,
    payload: Dict[str, Any],
    behavior_id: str,
    request_id: str,
) -> None:
    now = time.monotonic()
    with _deferred_question_lock:
        expired = [
            key
            for key, item in _deferred_ordering_questions.items()
            if float(item.get('expiresAt') or 0) <= now
        ]
        for key in expired:
            _deferred_ordering_questions.pop(key, None)
        _deferred_ordering_questions[str(session_id)] = {
            'payload': dict(payload),
            'behaviorId': str(behavior_id),
            'requestId': str(request_id),
            'expiresAt': now + _DEFERRED_QUESTION_TTL_SECONDS,
        }


def _get_deferred_ordering_question(
    session_id: str,
) -> Optional[Dict[str, Any]]:
    now = time.monotonic()
    with _deferred_question_lock:
        pending = _deferred_ordering_questions.get(str(session_id))
        if not pending:
            return None
        if float(pending.get('expiresAt') or 0) <= now:
            _deferred_ordering_questions.pop(str(session_id), None)
            return None
        return {
            **pending,
            'payload': dict(pending.get('payload') or {}),
        }


def _interactive_question_identity(data: Optional[Dict[str, Any]]) -> Dict[str, str]:
    payload = data if isinstance(data, dict) else {}
    page_context = (
        payload.get('pageContext')
        if isinstance(payload.get('pageContext'), dict)
        else {}
    )
    question_id = payload.get('questionId') or page_context.get('questionId')
    question_index = (
        payload.get('questionIndex')
        if payload.get('questionIndex') is not None
        else page_context.get('questionIndex')
    )
    course_type = payload.get('courseType') or page_context.get('courseType')
    return {
        'questionId': str(question_id or '').strip(),
        'questionIndex': str(question_index if question_index is not None else '').strip(),
        'courseType': str(course_type or '').strip().lower(),
    }


def _interrupt_interactive_prompt(
    session_id: Optional[str],
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """User input wins over a still-playing interactive question prompt."""
    sid = str(session_id or '').strip()
    if not sid:
        return
    _interactive_input_state[sid] = {
        **_interactive_question_identity(data),
        'at': time.monotonic(),
    }
    try:
        from app.robot import get_robot_service
        service = get_robot_service()
        state = service.get_behavior_busy_state() or {}
        active_id = state.get('activeBehaviorId') or state.get('eventId')
        if active_id:
            service.abort_behavior(str(active_id))
    except Exception:
        logger.debug('interactive prompt interrupt failed session=%s', sid, exc_info=True)


def _interactive_input_recent(
    session_id: Optional[str],
    data: Optional[Dict[str, Any]] = None,
    window_ms: int = 2500,
) -> bool:
    sid = str(session_id or '').strip()
    state = _interactive_input_state.get(sid) or {}
    at = state.get('at')
    if not at or (time.monotonic() - float(at)) * 1000 > window_ms:
        return False

    incoming = _interactive_question_identity(data)
    previous_type = str(state.get('courseType') or '')
    incoming_type = incoming['courseType']
    if previous_type and incoming_type and previous_type != incoming_type:
        return False

    previous_id = str(state.get('questionId') or '')
    incoming_id = incoming['questionId']
    if previous_id and incoming_id and previous_id != incoming_id:
        return False

    previous_index = str(state.get('questionIndex') or '')
    incoming_index = incoming['questionIndex']
    if previous_index and incoming_index:
        return previous_index == incoming_index

    return bool(previous_id and incoming_id and previous_id == incoming_id)


def _interactive_question_is_current(
    session_id: Optional[str], data: Optional[Dict[str, Any]]
) -> bool:
    """Reject a delayed retry once the iframe has advanced to another item."""
    if not session_id or not isinstance(data, dict):
        return False
    try:
        from app.dialogue.page_context_store import get_interactive_page_context
        current = get_interactive_page_context(str(session_id)) or {}
    except Exception:
        return True
    expected = _interactive_question_identity(data)
    actual = _interactive_question_identity(current)
    for key in ('courseType', 'questionId', 'questionIndex'):
        if expected.get(key) and actual.get(key) and expected[key] != actual[key]:
            return False
    return True


def _consume_deferred_ordering_question(
    session_id: str,
    behavior_id: str,
) -> None:
    with _deferred_question_lock:
        pending = _deferred_ordering_questions.get(str(session_id))
        if (
            pending
            and str(pending.get('behaviorId') or '') == str(behavior_id)
        ):
            _deferred_ordering_questions.pop(str(session_id), None)


def _remember_pending_item_question(
    session_id: str,
    *,
    kind: str,
    payload: Dict[str, Any],
) -> str:
    """Latest-wins hard queue: item switch ask cannot be permanently dropped."""
    sid = str(session_id or '').strip()
    generation = uuid.uuid4().hex
    if not sid:
        return generation
    app = current_app._get_current_object() if has_app_context() else None
    with _deferred_question_lock:
        now = time.monotonic()
        expired = [
            key
            for key, item in _pending_interactive_questions.items()
            if float(item.get('expiresAt') or 0) <= now
        ]
        for key in expired:
            expired_item = _pending_interactive_questions.pop(key, None)
            expired_timer = (expired_item or {}).get('retryTimer')
            if expired_timer is not None:
                expired_timer.cancel()
        previous = _pending_interactive_questions.pop(sid, None)
        previous_timer = (previous or {}).get('retryTimer')
        if previous_timer is not None:
            previous_timer.cancel()
        _pending_interactive_questions[sid] = {
            'kind': str(kind or '').strip().lower(),
            'payload': dict(payload or {}),
            'generation': generation,
            'expiresAt': now + _PENDING_ITEM_QUESTION_TTL_SECONDS,
            'retryCount': 0,
            'retryTimer': None,
            'dispatching': False,
            'app': app,
        }
    return generation


def _pending_item_question_generation(session_id: Optional[str]) -> Optional[str]:
    sid = str(session_id or '').strip()
    if not sid:
        return None
    with _deferred_question_lock:
        pending = _pending_interactive_questions.get(sid)
        if not pending:
            return None
        if float(pending.get('expiresAt') or 0) <= time.monotonic():
            expired = _pending_interactive_questions.pop(sid, None)
            timer = (expired or {}).get('retryTimer')
            if timer is not None:
                timer.cancel()
            return None
        return str(pending.get('generation') or '') or None


def _clear_pending_item_question(
    session_id: Optional[str],
    *,
    generation: Optional[str] = None,
) -> None:
    sid = str(session_id or '').strip()
    if not sid:
        return
    with _deferred_question_lock:
        pending = _pending_interactive_questions.get(sid)
        if not pending:
            return
        if generation and str(pending.get('generation') or '') != str(generation):
            return
        removed = _pending_interactive_questions.pop(sid, None)
        timer = (removed or {}).get('retryTimer')
        if timer is not None:
            timer.cancel()


def _item_question_still_current(
    session_id: Optional[str],
    question_data: Optional[Dict[str, Any]],
) -> bool:
    """True while this ask generation is still the latest pending item switch."""
    if not isinstance(question_data, dict):
        return True
    generation = question_data.get('_askGeneration')
    if not generation:
        return _interactive_question_is_current(session_id, question_data)
    pending_gen = _pending_item_question_generation(session_id)
    # Pending cleared => ask already landed, expired, or was replaced.
    if not pending_gen or pending_gen != str(generation):
        return False
    return _interactive_question_is_current(session_id, question_data)


def _preempt_busy_behavior_for_item_question(
    session_id: Optional[str],
    robot_service=None,
) -> bool:
    """Abort non-matching chatter so pairing/ordering questions can start now."""
    sid = str(session_id or '').strip()
    try:
        if robot_service is None:
            from app.robot import get_robot_service

            robot_service = get_robot_service()
        state = robot_service.get_behavior_busy_state() or {}
        active_id = state.get('activeBehaviorId') or state.get('eventId')
        if not active_id:
            return False
        aborted = bool(robot_service.abort_behavior(str(active_id)))
        if aborted:
            logger.info(
                '题切换提问抢占忙碌行为: session=%s aborted=%s',
                sid,
                active_id,
            )
        return aborted
    except Exception:
        logger.debug(
            '题切换提问抢占失败 session=%s', sid, exc_info=True
        )
        return False


def _dispatch_pending_item_question(
    session_id: Optional[str],
    generation: Optional[str] = None,
) -> bool:
    """Dispatch the latest item ask through its single session-owned chain."""
    sid = str(session_id or '').strip()
    if not sid:
        return False
    with _deferred_question_lock:
        pending = _pending_interactive_questions.get(sid)
        if not pending:
            return False
        if float(pending.get('expiresAt') or 0) <= time.monotonic():
            expired = _pending_interactive_questions.pop(sid, None)
            timer = (expired or {}).get('retryTimer')
            if timer is not None:
                timer.cancel()
            return False
        current_generation = str(pending.get('generation') or '')
        if generation and current_generation != str(generation):
            return False
        if pending.get('dispatching'):
            return True
        pending['dispatching'] = True
        kind = str(pending.get('kind') or '')
        payload = dict(pending.get('payload') or {})
        retry_count = int(pending.get('retryCount') or 0)
        app = pending.get('app')
    if not payload:
        with _deferred_question_lock:
            current = _pending_interactive_questions.get(sid)
            if current and current.get('generation') == current_generation:
                current['dispatching'] = False
        return False
    logger.info(
        '发送题切换提问: session=%s kind=%s gen=%s retry=%s',
        sid,
        kind,
        current_generation[:8],
        retry_count,
    )
    try:
        def dispatch() -> bool:
            if kind in ('ordering', 'sequencing'):
                return _play_atomic_ordering_question(
                    sid,
                    str(payload.get('audio_type') or 'question'),
                    category=payload.get('category'),
                    rule=payload.get('rule'),
                    text=payload.get('text'),
                    event_data=payload.get('event_data'),
                    _retry_count=retry_count,
                )
            return _play_interactive_course_audio(
                sid,
                str(payload.get('course_type') or 'pairing'),
                'question',
                category=payload.get('category'),
                rule=payload.get('rule'),
                text=payload.get('text'),
                question_data=payload.get('question_data'),
                _retry_count=retry_count,
            )

        if app is not None and not has_app_context():
            with app.app_context():
                return dispatch()
        return dispatch()
    finally:
        with _deferred_question_lock:
            current = _pending_interactive_questions.get(sid)
            if current and current.get('generation') == current_generation:
                current['dispatching'] = False


def _schedule_pending_item_question_retry(
    session_id: Optional[str],
    generation: Optional[str],
    retry_count: int,
) -> bool:
    """Own exactly one retry timer for one pending question generation."""
    sid = str(session_id or '').strip()
    gen = str(generation or '').strip()
    if not sid or not gen:
        return False

    def fire() -> None:
        with _deferred_question_lock:
            current = _pending_interactive_questions.get(sid)
            if not current or str(current.get('generation') or '') != gen:
                return
            if current.get('dispatching'):
                timer = threading.Timer(
                    _INTERACTIVE_QUESTION_BUSY_RETRY_SEC,
                    fire,
                )
                timer.daemon = True
                current['retryTimer'] = timer
                timer.start()
                return
            current['retryTimer'] = None
        _dispatch_pending_item_question(sid, gen)

    with _deferred_question_lock:
        pending = _pending_interactive_questions.get(sid)
        if not pending or str(pending.get('generation') or '') != gen:
            return False
        existing = pending.get('retryTimer')
        if existing is not None and existing.is_alive():
            return True
        pending['retryCount'] = max(0, int(retry_count))
        timer = threading.Timer(_INTERACTIVE_QUESTION_BUSY_RETRY_SEC, fire)
        timer.daemon = True
        pending['retryTimer'] = timer
        timer.start()
    return True


def _flush_pending_item_question(session_id: Optional[str]) -> bool:
    """Ensure the latest ask has one active dispatch/retry owner."""
    sid = str(session_id or '').strip()
    if not sid:
        return False
    with _deferred_question_lock:
        pending = _pending_interactive_questions.get(sid)
        if not pending:
            return False
        timer = pending.get('retryTimer')
        if pending.get('dispatching') or (
            timer is not None and timer.is_alive()
        ):
            return True
        generation = str(pending.get('generation') or '')
    return _dispatch_pending_item_question(sid, generation)


def _schedule_pairing_item_question(
    session_id: Optional[str],
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Hard rule: every pairing item switch asks immediately and is never dropped."""
    sid = str(session_id or '').strip()
    if not sid:
        return False
    event_data = dict(data or {})
    generation = _remember_pending_item_question(
        sid,
        kind='pairing',
        payload={
            'course_type': 'pairing',
            'audio_type': 'question',
            'question_data': event_data,
        },
    )
    event_data = {**event_data, '_askGeneration': generation}
    with _deferred_question_lock:
        pending = _pending_interactive_questions.get(sid)
        if pending and pending.get('generation') == generation:
            pending['payload']['question_data'] = event_data
    return _dispatch_pending_item_question(sid, generation)


def _schedule_ordering_item_question(
    session_id: Optional[str],
    *,
    audio_type: str,
    category: str = None,
    rule: str = None,
    text: str = None,
    event_data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Hard rule: every ordering item switch asks immediately and is never dropped."""
    sid = str(session_id or '').strip()
    if not sid:
        return False
    payload_event = dict(event_data or {})
    generation = _remember_pending_item_question(
        sid,
        kind='ordering',
        payload={
            'course_type': 'ordering',
            'audio_type': audio_type,
            'category': category,
            'rule': rule,
            'text': text,
            'event_data': payload_event,
        },
    )
    payload_event = {**payload_event, '_askGeneration': generation}
    with _deferred_question_lock:
        pending = _pending_interactive_questions.get(sid)
        if pending and pending.get('generation') == generation:
            pending['payload']['event_data'] = payload_event
    return _dispatch_pending_item_question(sid, generation)


def _play_interactive_course_audio(
    session_id: str,
    course_type: str,
    audio_type: str,
    *,
    category: str = None,
    rule: str = None,
    text: str = None,
    behavior_id: str = None,
    request_id: str = None,
    robot_service=None,
    audio_service=None,
    _retry_count: int = 0,
    question_data: Optional[Dict[str, Any]] = None,
) -> bool:
    """Play one interactive utterance inside the global behavior mutex."""
    if not session_id or not course_type or not audio_type:
        return False
    resolved_behavior_id = str(
        behavior_id or f'interactive-audio-{uuid.uuid4().hex[:12]}'
    )
    resolved_request_id = str(
        request_id or f'interactive-request-{uuid.uuid4().hex[:12]}'
    )
    try:
        if robot_service is None:
            from app.robot import get_robot_service

            robot_service = get_robot_service()
        reservation = robot_service.reserve_behavior(
            behavior_id=resolved_behavior_id,
            request_id=resolved_request_id,
            session_id=str(session_id),
        )
        if not reservation.get('accepted'):
            logger.info(
                '互动语音暂缓: session=%s type=%s q=%s/%s active=%s retry=%s',
                session_id,
                audio_type,
                (question_data or {}).get('questionId'),
                (question_data or {}).get('questionIndex'),
                reservation.get('activeBehaviorId'),
                _retry_count,
            )
            generation = (
                question_data.get('_askGeneration')
                if isinstance(question_data, dict)
                else None
            )
            # Item-switch asks have one session-owned retry chain.  The
            # completion event may flush it, but must never create a second
            # chain racing the first one.
            if generation:
                if _retry_count == 0 or _retry_count % 3 == 0:
                    _preempt_busy_behavior_for_item_question(
                        session_id, robot_service=robot_service
                    )
                if (
                    _retry_count < _INTERACTIVE_QUESTION_BUSY_RETRIES
                    and _item_question_still_current(
                        session_id, question_data
                    )
                ):
                    _schedule_pending_item_question_retry(
                        session_id,
                        generation,
                        _retry_count + 1,
                    )
                return False

            # Non-item/manual question compatibility path.
            if audio_type == 'question' and (
                _retry_count == 0 or _retry_count % 3 == 0
            ):
                if _preempt_busy_behavior_for_item_question(
                    session_id, robot_service=robot_service
                ):
                    return _play_interactive_course_audio(
                        session_id=session_id,
                        course_type=course_type,
                        audio_type=audio_type,
                        category=category,
                        rule=rule,
                        text=text,
                        behavior_id=resolved_behavior_id,
                        request_id=resolved_request_id,
                        robot_service=robot_service,
                        audio_service=audio_service,
                        _retry_count=_retry_count + 1,
                        question_data=question_data,
                    )
            max_retries = (
                _INTERACTIVE_QUESTION_BUSY_RETRIES
                if audio_type == 'question'
                else 15
            )
            if _retry_count < max_retries:
                if audio_type == 'question' and not _item_question_still_current(
                    session_id, question_data
                ):
                    return False
                retry_delay = (
                    _INTERACTIVE_QUESTION_BUSY_RETRY_SEC
                    if audio_type == 'question'
                    else 0.25
                )
                retry_timer = threading.Timer(
                    retry_delay,
                    _play_interactive_course_audio,
                    kwargs={
                        'session_id': session_id,
                        'course_type': course_type,
                        'audio_type': audio_type,
                        'category': category,
                        'rule': rule,
                        'text': text,
                        'behavior_id': resolved_behavior_id,
                        'request_id': resolved_request_id,
                        'robot_service': robot_service,
                        'audio_service': audio_service,
                        '_retry_count': _retry_count + 1,
                        'question_data': question_data,
                    },
                )
                retry_timer.daemon = True
                retry_timer.start()
            return False
        resolved_behavior_id = str(
            reservation.get('behaviorId') or resolved_behavior_id
        )
        # Automatic interactive feedback must use the same multimodal plan as
        # a teacher click. Resolve the active course context so praise/question
        # also carries the configured expression and motion.
        runtime_session = None
        try:
            from app.session import get_session_manager
            runtime_session = get_session_manager().get_session(str(session_id))
        except Exception:
            runtime_session = None
        aux_key = 'question' if audio_type == 'question' else (
            'praise' if audio_type == 'praise' else 'hint'
        )
        behavior_payload = {
            'action': 'play',
            'sessionId': str(session_id),
            'courseType': course_type,
            'aux': {aux_key: True},
            'behaviorId': resolved_behavior_id,
            'behavior_id': resolved_behavior_id,
            'interactionId': resolved_behavior_id,
            'requestId': resolved_request_id,
            'request_id': resolved_request_id,
        }
        if runtime_session is not None:
            behavior_payload.update({
                'studentId': getattr(runtime_session, 'student_id', None),
                'courseId': getattr(runtime_session, 'course_id', None),
                'itemId': getattr(runtime_session, 'course_item_id', None),
                'trainingSessionId': getattr(runtime_session, 'training_session_id', None),
            })
        # Interactive iframe context is authoritative while the runtime
        # session remains on the parent course shell. It contains the actual
        # course/item that owns the praise/question mapping.
        try:
            from app.dialogue.page_context_store import get_interactive_page_context
            page_ctx = get_interactive_page_context(str(session_id)) or {}
            if isinstance(page_ctx, dict):
                behavior_payload['courseId'] = (
                    page_ctx.get('courseId') or page_ctx.get('course_id')
                    or behavior_payload.get('courseId')
                )
                behavior_payload['itemId'] = (
                    page_ctx.get('itemId') or page_ctx.get('item_id')
                    or behavior_payload.get('itemId')
                )
                behavior_payload['studentId'] = (
                    page_ctx.get('studentId') or page_ctx.get('student_id')
                    or behavior_payload.get('studentId')
                )
                behavior_payload['trainingSessionId'] = (
                    page_ctx.get('trainingSessionId') or page_ctx.get('training_session_id')
                    or behavior_payload.get('trainingSessionId')
                )
                behavior_payload['category'] = page_ctx.get('category') or category
                behavior_payload['rule'] = page_ctx.get('rule') or rule
        except Exception:
            pass
        try:
            from app.behavior import get_behavior_service
            behavior_ctx = get_behavior_service().get_current_context_for_runtime(str(session_id)) or {}
            if isinstance(behavior_ctx, dict):
                for target, keys in {
                    'courseId': ('course_id', 'courseId'),
                    'itemId': ('course_item_id', 'item_id', 'itemId'),
                    'studentId': ('student_id', 'studentId'),
                    'trainingSessionId': ('training_session_id', 'trainingSessionId'),
                }.items():
                    if not behavior_payload.get(target):
                        for key in keys:
                            if behavior_ctx.get(key):
                                behavior_payload[target] = behavior_ctx[key]
                                break
        except Exception:
            pass
        robot_result = robot_service.trigger_course_event(behavior_payload)
        if not robot_result.get('success'):
            robot_service.abort_behavior(resolved_behavior_id)
            return False
        behavior_animation = None
        child_sid = None
        if audio_type == 'praise':
            try:
                resolve_animation = getattr(
                    robot_service,
                    'resolve_encouragement_animation',
                    None,
                )
                if callable(resolve_animation):
                    behavior_animation = resolve_animation(behavior_payload)
                    child_sid = _child_owner_for_session(str(session_id))
            except Exception:
                logger.warning(
                    '互动课鼓励动画解析失败 session=%s',
                    session_id,
                    exc_info=True,
                )
        if behavior_animation and child_sid:
            animation_payload = {
                **behavior_payload,
                'protocolVersion': '1',
                'behaviorAnimation': behavior_animation,
                'praiseVideo': behavior_animation,
                'behaviorStartAtMs': robot_result.get('startAtEpochMs'),
                'startAtServerMs': robot_result.get('startAtEpochMs'),
                'behaviorStartDelayMs': _remaining_behavior_start_delay_ms(
                    robot_result
                ),
                'modality': 'childAnimation',
            }
            _update_play_request(
                resolved_request_id,
                behavior_id=resolved_behavior_id,
                is_aux=True,
                interaction_context={
                    'trainingSessionId': behavior_payload.get('trainingSessionId'),
                    'sessionId': str(session_id),
                    'questionId': (question_data or {}).get('questionId'),
                    'requestId': resolved_request_id,
                    'behaviorId': resolved_behavior_id,
                    'eventType': 'praise',
                    'isAux': True,
                },
            )
            if _socketio_server is not None:
                _socketio_server.emit(
                    'prepare_behavior_animation',
                    animation_payload,
                    to=child_sid,
                )
        audio_delay_ms = _remaining_behavior_start_delay_ms(robot_result)
        try:
            audio_delay_ms += int(robot_service.resolve_audio_offset_ms(behavior_payload) or 0)
        except Exception:
            pass
        if audio_type == 'question':
            audio_delay_ms = min(
                max(0, int(audio_delay_ms)),
                _INTERACTIVE_QUESTION_AUDIO_DELAY_CAP_MS,
            )
        if audio_service is None:
            from app.audio import get_audio_service

            audio_service = get_audio_service()
        ok = audio_service.play_interactive_course_audio(
            session_id=session_id,
            course_type=course_type,
            audio_type=audio_type,
            delay_ms=audio_delay_ms,
            category=category,
            rule=rule,
            text=text,
            behavior_id=resolved_behavior_id,
            request_id=resolved_request_id,
            question_id=(question_data or {}).get('questionId'),
        )
        if not ok:
            robot_service.abort_behavior(resolved_behavior_id)
            return False
        if not robot_service.set_behavior_audio_expected(
            resolved_behavior_id,
            1,
            session_id=str(session_id),
        ):
            robot_service.abort_behavior(resolved_behavior_id)
            return False
        set_animation_expected = getattr(
            robot_service,
            'set_behavior_animation_expected',
            None,
        )
        if callable(set_animation_expected):
            if not set_animation_expected(
                resolved_behavior_id,
                bool(behavior_animation and child_sid),
                session_id=str(session_id),
            ):
                robot_service.abort_behavior(resolved_behavior_id)
                return False
        if audio_type == 'question':
            generation = None
            if isinstance(question_data, dict):
                generation = question_data.get('_askGeneration')
            _clear_pending_item_question(session_id, generation=generation)
        logger.info(
            '互动课语音: session=%s type=%s audio=%s behavior=%s '
            'cat=%s rule=%s text=%s',
            session_id,
            course_type,
            audio_type,
            resolved_behavior_id,
            category,
            rule,
            (text or '')[:24],
        )
        return True
    except Exception as exc:
        try:
            if robot_service:
                robot_service.abort_behavior(resolved_behavior_id)
        except Exception:
            pass
        logger.warning('互动课语音失败: %s', exc)
        return False


def _dispatch_v2_speech_commands(
    commands: Any,
    *,
    session_id: str,
    child_room: str,
    behavior_id: str,
    request_id: str,
    base_delay_ms: int = 0,
) -> Dict[str, Any]:
    """Deliver V2 profile speech through the existing child speech event."""
    dispatched = 0
    for command in commands if isinstance(commands, list) else []:
        if not isinstance(command, dict):
            continue
        text = str(command.get('text') or '').strip()
        if not text:
            continue
        metadata = command.get('metadata') if isinstance(command.get('metadata'), dict) else {}
        line_id = command.get('lineId') or command.get('line_id')
        payload = {
            'text': text,
            'intent': line_id or metadata.get('intent') or 'interaction-plan',
            'delayMs': max(0, int(base_delay_ms or 0)) + max(
                0, int(metadata.get('delayMs') or 0)
            ),
            'source': 'interaction-plan',
            'ttsMode': metadata.get('ttsMode') or 'browser',
            'pauseAsr': bool(command.get('pauseAsr', command.get('pause_asr', True))),
            'sessionId': session_id,
            'session_id': session_id,
            'behaviorId': behavior_id,
            'behavior_id': behavior_id,
            'interactionId': behavior_id,
            'requestId': request_id,
            'request_id': request_id,
        }
        if line_id:
            payload['lineId'] = line_id
        audio_asset = command.get('audioAsset') or command.get('audio_asset') or metadata.get('audioAsset')
        if audio_asset:
            payload['audioAsset'] = audio_asset
        emit('robot_speak_text', payload, room=child_room, include_self=True)
        dispatched += 1
    return {
        'triggered': dispatched > 0,
        'dispatchCount': dispatched,
        'deferred': False,
    }


def _play_atomic_ordering_question(
    session_id: str,
    audio_type: str,
    *,
    category: str = None,
    rule: str = None,
    text: str = None,
    event_data: Optional[Dict[str, Any]] = None,
    robot_service=None,
    audio_service=None,
    runtime_session=None,
    _retry_count: int = 0,
) -> bool:
    """Start the real rule utterance and its visual as one behavior."""
    if not session_id:
        return False
    pending = _get_deferred_ordering_question(str(session_id))
    source = dict((pending or {}).get('payload') or {})
    source.update(dict(event_data or {}))
    if runtime_session is None:
        try:
            from app.session import get_session_manager

            runtime_session = get_session_manager().get_session(
                str(session_id)
            )
        except Exception:
            runtime_session = None
    behavior_id = str(
        (pending or {}).get('behaviorId')
        or source.get('behaviorId')
        or source.get('behavior_id')
        or f'ordering-question-{uuid.uuid4().hex[:12]}'
    )
    request_id = str(
        (pending or {}).get('requestId')
        or source.get('requestId')
        or source.get('request_id')
        or f'ordering-question-request-{uuid.uuid4().hex[:12]}'
    )
    if robot_service is None:
        from app.robot import get_robot_service

        robot_service = get_robot_service()
    reservation = robot_service.reserve_behavior(
        behavior_id=behavior_id,
        request_id=request_id,
        session_id=str(session_id),
    )
    if not reservation.get('accepted'):
        logger.info(
            '排序规则提问暂缓: session=%s q=%s/%s active=%s retry=%s',
            session_id,
            (event_data or {}).get('questionId'),
            (event_data or {}).get('questionIndex'),
            reservation.get('activeBehaviorId'),
            _retry_count,
        )
        generation = (
            event_data.get('_askGeneration')
            if isinstance(event_data, dict)
            else None
        )
        if generation:
            if _retry_count == 0 or _retry_count % 3 == 0:
                _preempt_busy_behavior_for_item_question(
                    session_id, robot_service=robot_service
                )
            if (
                _retry_count < _INTERACTIVE_QUESTION_BUSY_RETRIES
                and _item_question_still_current(session_id, event_data)
            ):
                _schedule_pending_item_question_retry(
                    session_id,
                    generation,
                    _retry_count + 1,
                )
            return False

        if _retry_count == 0 or _retry_count % 3 == 0:
            if _preempt_busy_behavior_for_item_question(
                session_id, robot_service=robot_service
            ):
                return _play_atomic_ordering_question(
                    session_id,
                    audio_type,
                    category=category,
                    rule=rule,
                    text=text,
                    event_data=event_data,
                    robot_service=robot_service,
                    audio_service=audio_service,
                    runtime_session=runtime_session,
                    _retry_count=_retry_count + 1,
                )
        if (
            _retry_count < _INTERACTIVE_QUESTION_BUSY_RETRIES
            and _item_question_still_current(session_id, event_data)
        ):
            retry_timer = threading.Timer(
                _INTERACTIVE_QUESTION_BUSY_RETRY_SEC,
                _play_atomic_ordering_question,
                kwargs={
                    'session_id': session_id,
                    'audio_type': audio_type,
                    'category': category,
                    'rule': rule,
                    'text': text,
                    'event_data': event_data,
                    'robot_service': robot_service,
                    'audio_service': audio_service,
                    'runtime_session': runtime_session,
                    '_retry_count': _retry_count + 1,
                },
            )
            retry_timer.daemon = True
            retry_timer.start()
        return False
    behavior_id = str(reservation.get('behaviorId') or behavior_id)

    robot_payload = dict(source)
    robot_payload.update({
        'action': 'play',
        'sessionId': str(session_id),
        'courseType': 'ordering',
        'aux': {'question': True},
        'behaviorId': behavior_id,
        'behavior_id': behavior_id,
        'interactionId': behavior_id,
        'requestId': request_id,
        'request_id': request_id,
    })
    if runtime_session is not None:
        robot_payload.setdefault(
            'studentId',
            getattr(runtime_session, 'student_id', None),
        )
        robot_payload.setdefault(
            'courseId',
            getattr(runtime_session, 'course_id', None),
        )
        robot_payload.setdefault(
            'itemId',
            getattr(runtime_session, 'course_item_id', None),
        )
        robot_payload.setdefault(
            'trainingSessionId',
            getattr(runtime_session, 'training_session_id', None),
        )
    robot_result = robot_service.trigger_course_event(robot_payload)
    if not robot_result.get('success'):
        robot_service.abort_behavior(behavior_id)
        return False

    if audio_service is None:
        from app.audio import get_audio_service

        audio_service = get_audio_service()
    delay_ms = _remaining_behavior_start_delay_ms(robot_result)
    try:
        delay_ms += int(
            robot_service.resolve_audio_offset_ms(robot_payload) or 0
        )
    except Exception:
        pass
    delay_ms = min(
        max(0, int(delay_ms)),
        _INTERACTIVE_QUESTION_AUDIO_DELAY_CAP_MS,
    )
    emitted = audio_service.play_interactive_course_audio(
        session_id=str(session_id),
        course_type='ordering',
        audio_type=audio_type,
        delay_ms=delay_ms,
        category=category,
        rule=rule,
        text=text,
        behavior_id=behavior_id,
        request_id=request_id,
        question_id=(event_data or {}).get('questionId'),
    )
    if not emitted:
        robot_service.abort_behavior(behavior_id)
        return False
    if not robot_service.set_behavior_audio_expected(
        behavior_id,
        1,
        session_id=str(session_id),
    ):
        robot_service.abort_behavior(behavior_id)
        return False
    _consume_deferred_ordering_question(str(session_id), behavior_id)
    generation = None
    if isinstance(event_data, dict):
        generation = event_data.get('_askGeneration')
    _clear_pending_item_question(session_id, generation=generation)
    return True


def _store_interactive_page_context(session_id, data, *, course_type: str) -> None:
    """把互动页上报的 pageContext / 题面字段写入对话用快照。"""
    if not session_id or not isinstance(data, dict):
        return
    try:
        from app.dialogue.page_context_store import set_interactive_page_context

        ctx = {}
        raw = data.get('pageContext') or data.get('page_context')
        if isinstance(raw, dict):
            ctx.update(raw)
        for key in (
            'prompt', 'target', 'options', 'optionsLeftToRight',
            'wrongAttempts', 'rule', 'ruleText', 'category',
            'questionIndex', 'totalQuestions', 'correctPosition',
            'correctLabel', 'correctOptionPosition', 'correctOptionLabel',
            'questionId',
        ):
            if data.get(key) is not None and key not in ctx:
                ctx[key] = data.get(key)
        if course_type:
            ctx.setdefault('courseType', course_type)
        set_interactive_page_context(session_id, ctx)
    except Exception as e:
        logger.warning('保存互动页上下文失败: %s', e)


# 在线状态跟踪（供 server 控制台展示）
_presence_state = {
    'teacher': {},      # sid -> last_seen_ms
    'child': {},        # sid -> last_seen_ms
    'child_agent': {},  # sid -> {'lastSeenMs': int, 'online': bool}  Robot Agent
    'child_media_agent': {},  # sid -> {'lastSeenMs': int, 'online': bool}
    'robot_display': {},  # sid -> last_seen_ms
    'robot_control': {},  # sid -> last_seen_ms
}
_PRESENCE_STALE_MS = 30 * 1000
_presence_lock = threading.RLock()
_presence_details: Dict[str, Dict[str, Dict[str, Any]]] = {
    role: {} for role in _presence_state
}
_child_sid_bindings: Dict[str, Dict[str, Any]] = {}
_child_sid_capabilities: Dict[str, Optional[bool]] = {}
_child_sync_attempted_sids = set()
_child_session_owners: Dict[str, str] = {}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _touch_presence(
    role: str,
    sid: str,
    online: bool = True,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    if role not in _presence_state:
        return
    with _presence_lock:
        now = _now_ms()
        existing = dict(_presence_details[role].get(sid) or {})
        existing.setdefault('connectedAtMs', now)
        existing.update({
            key: value for key, value in (details or {}).items()
            if value not in (None, '')
        })
        existing.update({'lastSeenMs': now, 'online': bool(online)})
        _presence_details[role][sid] = existing
        if role in ('child_agent', 'child_media_agent'):
            _presence_state[role][sid] = {
                'lastSeenMs': now,
                'online': bool(online),
            }
            return
        _presence_state[role][sid] = now


def _remove_sid_presence(sid: str) -> None:
    with _presence_lock:
        for role in (
            'teacher', 'child', 'child_agent', 'child_media_agent',
            'robot_display', 'robot_control',
        ):
            _presence_state[role].pop(sid, None)
            _presence_details[role].pop(sid, None)
        _child_sid_bindings.pop(sid, None)
        _child_sid_capabilities.pop(sid, None)
        _child_sync_attempted_sids.discard(sid)
        for session_id, owner_sid in list(_child_session_owners.items()):
            if owner_sid == sid:
                _child_session_owners.pop(session_id, None)


def _normalize_student_id(value: Any) -> Optional[Any]:
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return str(value).lower()
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value).strip() or None


def _child_identity(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = data if isinstance(data, dict) else {}
    session_id = payload.get('sessionId') or payload.get('session_id')
    training_id = (
        payload.get('trainingSessionId')
        or payload.get('training_session_id')
    )
    student_id = payload.get('studentId')
    if student_id is None:
        student_id = payload.get('student_id')
    return {
        'studentId': _normalize_student_id(student_id),
        'trainingSessionId': (
            str(training_id).strip() if training_id not in (None, '') else None
        ),
        'sessionId': (
            str(session_id).strip() if session_id not in (None, '') else None
        ),
    }


def _identities_match(
    candidate: Dict[str, Any],
    requested: Dict[str, Any],
) -> bool:
    for key in ('studentId', 'trainingSessionId', 'sessionId'):
        expected = requested.get(key)
        if expected is None:
            continue
        actual = candidate.get(key)
        if actual is None or str(actual) != str(expected):
            return False
    return True


def _extract_resource_ready_capability(
    data: Optional[Dict[str, Any]],
) -> tuple:
    payload = data if isinstance(data, dict) else {}
    capabilities = payload.get('capabilities')
    capabilities = capabilities if isinstance(capabilities, dict) else {}
    found = 'resourceReady' in capabilities
    value = capabilities.get('resourceReady')
    if not found and 'resourceReadySupported' in payload:
        found = True
        value = payload.get('resourceReadySupported')
    if not found:
        return False, None
    if isinstance(value, bool):
        return True, value
    if isinstance(value, (int, float)) and value in (0, 1):
        return True, bool(value)
    normalized = str(value or '').strip().lower()
    if normalized in ('1', 'true', 'yes', 'supported'):
        return True, True
    if normalized in ('0', 'false', 'no', 'unsupported'):
        return True, False
    return True, None


def _remember_child_capability(
    sid: str,
    data: Optional[Dict[str, Any]],
) -> Optional[bool]:
    found, capability = _extract_resource_ready_capability(data)
    with _presence_lock:
        if found:
            _child_sid_capabilities[sid] = capability
        else:
            _child_sid_capabilities.setdefault(sid, None)
        binding = _child_sid_bindings.get(sid)
        if binding is not None:
            binding['resourceReadySupported'] = (
                _child_sid_capabilities.get(sid)
            )
        return _child_sid_capabilities.get(sid)


def _fresh_child_sids() -> list:
    now = _now_ms()
    with _presence_lock:
        return [
            sid
            for sid, last_seen in _presence_state['child'].items()
            if now - int(last_seen or 0) <= _PRESENCE_STALE_MS
        ]


def _unique_unbound_child_sid() -> Optional[str]:
    with _presence_lock:
        unbound = [
            sid
            for sid in _fresh_child_sids()
            if sid not in _child_sid_bindings
        ]
    return unbound[0] if len(unbound) == 1 else None


def _claim_child_session_owner(session_id: str, sid: str) -> bool:
    """Claim one runtime session for exactly one live child connection."""
    session_id = str(session_id or '').strip()
    sid = str(sid or '').strip()
    if not session_id or not sid:
        return False
    with _presence_lock:
        current = _child_session_owners.get(session_id)
        fresh = set(_fresh_child_sids())
        if current and current != sid and current in fresh:
            return False
        _child_session_owners[session_id] = sid
        return True


def _child_owner_for_session(session_id: Any) -> Optional[str]:
    session_id = str(session_id or '').strip()
    if not session_id:
        return None
    with _presence_lock:
        owner = _child_session_owners.get(session_id)
        if owner and owner in set(_fresh_child_sids()):
            return owner
        if owner:
            _child_session_owners.pop(session_id, None)
        return None


def _release_child_session_owner(session_id: Any, sid: Optional[str] = None) -> None:
    session_id = str(session_id or '').strip()
    if not session_id:
        return
    with _presence_lock:
        current = _child_session_owners.get(session_id)
        if sid is None or current == str(sid):
            _child_session_owners.pop(session_id, None)


def _select_child_sid_for_identity(
    identity: Dict[str, Any],
) -> tuple:
    """Choose a child only when its identity, or the online fallback, is unique."""
    fresh = set(_fresh_child_sids())
    with _presence_lock:
        matching = [
            sid
            for sid, binding in _child_sid_bindings.items()
            if sid in fresh and _identities_match(binding, identity)
        ]
        if len(matching) == 1:
            return matching[0], None
        if len(matching) > 1:
            return None, 'ambiguous_matching_children'

        student_id = identity.get('studentId')
        if student_id is not None:
            same_student = [
                sid
                for sid, binding in _child_sid_bindings.items()
                if sid in fresh
                and binding.get('studentId') is not None
                and str(binding.get('studentId')) == str(student_id)
            ]
            if len(same_student) == 1:
                return same_student[0], None
            if len(same_student) > 1:
                return None, 'ambiguous_student_children'

        unbound = [sid for sid in fresh if sid not in _child_sid_bindings]
        if len(unbound) == 1:
            return unbound[0], None
        if len(fresh) == 1:
            return next(iter(fresh)), None
        return (
            None,
            'child_offline' if not fresh else 'ambiguous_children',
        )


def _is_authorized_child_sender(
    sid: str,
    data: Optional[Dict[str, Any]],
    *,
    require_cached_request: bool = False,
) -> bool:
    payload = data if isinstance(data, dict) else {}
    session_id = payload.get('sessionId') or payload.get('session_id')
    if not session_id:
        return False
    session_id = str(session_id)
    owner = _child_owner_for_session(session_id)
    if owner != str(sid):
        return False
    with _presence_lock:
        binding = dict(_child_sid_bindings.get(str(sid)) or {})
    if str(binding.get('sessionId') or '') != session_id:
        return False
    if not require_cached_request:
        return True
    request_id = payload.get('requestId') or payload.get('request_id')
    if not request_id:
        return False
    with _play_request_lock:
        entry = _play_request_cache.get(str(request_id))
        content = entry.get('contentForwardData') if entry else None
    return bool(
        isinstance(content, dict)
        and str(
            content.get('sessionId') or content.get('session_id') or ''
        ) == session_id
    )


def _is_active_runtime_session(session_id: str) -> bool:
    try:
        from app.session import get_session_manager

        runtime = get_session_manager().get_session(str(session_id))
        return bool(runtime and runtime.is_active())
    except Exception:
        return False


def _latest_cached_content_candidates(
    requested_identity: Optional[Dict[str, Any]] = None,
) -> list:
    """Return the newest non-aux content for each matching runtime session."""
    requested = requested_identity or {}
    candidates = []
    seen_sessions = set()
    now = time.monotonic()
    with _play_request_lock:
        _prune_play_request_cache(now)
        entries = list(_play_request_cache.items())
        for request_id, entry in reversed(entries):
            if bool(entry.get('isAux')):
                continue
            payload = entry.get('contentForwardData')
            if not isinstance(payload, dict):
                continue
            identity = _child_identity(payload)
            session_id = identity.get('sessionId')
            if not session_id or session_id in seen_sessions:
                continue
            seen_sessions.add(session_id)
            if not _is_active_runtime_session(session_id):
                continue
            if not _identities_match(identity, requested):
                continue
            candidates.append({
                'requestId': str(request_id),
                'payload': dict(payload),
                'identity': identity,
            })
    return candidates


def _runtime_child_identity(
    requested: Dict[str, Any],
) -> tuple:
    """Validate/fill a persisted session identity from the runtime registry."""
    session_id = requested.get('sessionId')
    if not session_id:
        return requested, None
    try:
        from app.session import get_session_manager

        runtime = get_session_manager().get_session(str(session_id))
    except Exception:
        runtime = None
    if runtime is None:
        return requested, 'session_not_found'
    try:
        if not runtime.is_active():
            return requested, 'session_inactive'
    except Exception:
        return requested, 'session_inactive'
    runtime_identity = {
        'studentId': _normalize_student_id(
            getattr(runtime, 'student_id', None)
        ),
        'trainingSessionId': (
            str(getattr(runtime, 'training_session_id', '') or '').strip()
            or None
        ),
        'sessionId': str(session_id),
    }
    if not _identities_match(runtime_identity, requested):
        return requested, 'identity_mismatch'
    merged = dict(runtime_identity)
    for key, value in requested.items():
        if value is not None:
            merged[key] = value
    return merged, None


def _resolve_child_sync_target(
    sid: str,
    data: Optional[Dict[str, Any]],
) -> tuple:
    requested = _child_identity(data)
    supplied = any(value is not None for value in requested.values())
    with _presence_lock:
        existing = dict(_child_sid_bindings.get(sid) or {})

    if not supplied and existing.get('sessionId'):
        requested = _child_identity(existing)
        supplied = True

    if requested.get('sessionId'):
        candidates = _latest_cached_content_candidates(requested)
        identity, error = _runtime_child_identity(requested)
        if error:
            fallback_candidates = _latest_cached_content_candidates({})
            if (
                _unique_unbound_child_sid() == sid
                and len(fallback_candidates) == 1
            ):
                candidate = fallback_candidates[0]
                return (
                    dict(candidate['identity']),
                    candidate,
                    'stale_binding_recovered',
                    None,
                )
            return None, None, None, error
        if candidates:
            candidate = candidates[0]
            merged = dict(candidate['identity'])
            for key, value in identity.items():
                if value is not None:
                    merged[key] = value
            return merged, candidate, (
                'existing_binding'
                if existing.get('sessionId') == merged.get('sessionId')
                else 'persisted_session'
            ), None
        # A valid active runtime session must bind before the first course
        # content exists so its first room-scoped play cannot be missed.
        if _is_active_runtime_session(str(identity.get('sessionId'))):
            return identity, None, 'persisted_session', None
        return None, None, None, 'session_not_found'

    candidates = _latest_cached_content_candidates(requested)
    if supplied:
        if len(candidates) == 1:
            candidate = candidates[0]
            return (
                dict(candidate['identity']),
                candidate,
                'cached_content',
                None,
            )
        return (
            None,
            None,
            None,
            (
                'no_matching_content'
                if not candidates
                else 'ambiguous_content'
            ),
        )

    if _unique_unbound_child_sid() != sid:
        return None, None, None, 'ambiguous_child'
    if len(candidates) != 1:
        return (
            None,
            None,
            None,
            'no_active_content' if not candidates else 'ambiguous_content',
        )
    candidate = candidates[0]
    return (
        dict(candidate['identity']),
        candidate,
        'unique_unbound_child',
        None,
    )


def _move_sid_to_child_session(
    socketio,
    sid: str,
    session_id: str,
    previous_session_id: Optional[str] = None,
) -> bool:
    server = getattr(socketio, 'server', None)
    if server is None or not hasattr(server, 'enter_room'):
        return True
    try:
        if previous_session_id and str(previous_session_id) != str(session_id):
            server.leave_room(
                sid,
                str(previous_session_id),
                namespace='/',
            )
            server.leave_room(
                sid,
                f'session_{previous_session_id}_child',
                namespace='/',
            )
        server.enter_room(sid, str(session_id), namespace='/')
        server.enter_room(
            sid,
            f'session_{session_id}_child',
            namespace='/',
        )
        return True
    except Exception as exc:
        logger.warning(
            '儿童 SID 加入精确会话房间失败 sid=%s session=%s: %s',
            sid,
            session_id,
            exc,
        )
        return False


def _store_child_binding(
    sid: str,
    identity: Dict[str, Any],
    *,
    source: str,
) -> Dict[str, Any]:
    with _presence_lock:
        previous = _child_sid_bindings.get(sid) or {}
        same_session = (
            previous.get('sessionId')
            and previous.get('sessionId') == identity.get('sessionId')
        )
        binding = {
            **identity,
            'source': source,
            'lastSeenMs': _now_ms(),
            'resourceReadySupported': _child_sid_capabilities.get(sid),
        }
        if same_session and previous.get('lastContentRequestId'):
            binding['lastContentRequestId'] = previous.get(
                'lastContentRequestId'
            )
        _child_sid_bindings[sid] = binding
        return dict(binding)


def _assign_child_for_identity(
    socketio,
    identity: Dict[str, Any],
    *,
    source: str,
) -> tuple:
    """Bind one live child to a runtime identity without widening the room."""
    session_id = identity.get('sessionId')
    if not session_id:
        return None, 'session_id_missing'
    current_owner = _child_owner_for_session(session_id)
    if current_owner:
        with _presence_lock:
            current_binding = dict(
                _child_sid_bindings.get(current_owner) or {}
            )
        if _identities_match(current_binding, identity):
            return current_owner, None
        return None, 'session_owner_identity_mismatch'

    sid, error = _select_child_sid_for_identity(identity)
    if not sid:
        return None, error
    if _child_sid_capabilities.get(sid) is not True:
        return None, 'child_upgrade_required'
    with _presence_lock:
        previous_session_id = (
            (_child_sid_bindings.get(sid) or {}).get('sessionId')
        )
    if not _claim_child_session_owner(str(session_id), sid):
        return None, 'session_owned_by_another_child'
    if not _move_sid_to_child_session(
        socketio,
        sid,
        str(session_id),
        previous_session_id=previous_session_id,
    ):
        _release_child_session_owner(session_id, sid)
        return None, 'room_join_failed'
    _store_child_binding(sid, identity, source=source)
    return sid, None


def _emit_readiness_to_child(socketio, event: str, payload: Dict[str, Any]) -> tuple:
    """Bind the unique compatible child before a room-scoped readiness event.

    A child page may come online after ``prepare_training``.  In that case it
    has presence but has not joined the reserved media session room yet.  A
    bare room emit silently loses the capture barrier.  Reusing the same
    identity/ownership checks as prepare keeps the delivery targeted while
    making late join recoverable.
    """
    identity = _child_identity(payload)
    child_sid, error = _assign_child_for_identity(
        socketio,
        identity,
        source=f'readiness:{event}',
    )
    if not child_sid:
        return False, error or 'child_binding_unavailable'
    socketio.emit(event, payload, to=child_sid)
    return True, None


def _child_sync_payload(
    *,
    success: bool,
    identity: Optional[Dict[str, Any]] = None,
    reason: Optional[str] = None,
    source: Optional[str] = None,
    request_id: Optional[str] = None,
    content_available: bool = False,
    capability: Any = 'unknown',
) -> Dict[str, Any]:
    resolved = identity or {}
    return {
        'success': bool(success),
        'bound': bool(success and resolved.get('sessionId')),
        'reason': reason,
        'source': source,
        'studentId': resolved.get('studentId'),
        'trainingSessionId': resolved.get('trainingSessionId'),
        'sessionId': resolved.get('sessionId'),
        'requestId': request_id,
        'contentAvailable': bool(content_available),
        'resourceReadySupported': capability,
    }


def _resource_ready_support_for_identity(
    data: Optional[Dict[str, Any]],
    *,
    include_unique_unbound: bool = False,
) -> Any:
    requested = _child_identity(data)
    online = set(_fresh_child_sids())
    with _presence_lock:
        matching = []
        for sid, binding in _child_sid_bindings.items():
            if sid not in online or not _identities_match(binding, requested):
                continue
            matching.append(_child_sid_capabilities.get(sid))
        if not matching and include_unique_unbound:
            unbound_sid = _unique_unbound_child_sid()
            if unbound_sid:
                matching.append(_child_sid_capabilities.get(unbound_sid))
    if matching:
        if any(value is True for value in matching):
            return True
        # An online target that does not positively advertise readiness is an
        # old/unsupported child. Only a genuinely absent target is unknown.
        return False
    return 'unknown'


def _sync_child_sid(
    socketio,
    sid: str,
    data: Optional[Dict[str, Any]],
    *,
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    payload = data if isinstance(data, dict) else {}
    capability = _remember_child_capability(sid, payload)
    requested = _child_identity(payload)
    has_identity = any(value is not None for value in requested.values())
    with _presence_lock:
        existing = dict(_child_sid_bindings.get(sid) or {})
        already_attempted = sid in _child_sync_attempted_sids
        identity_changed = (
            has_identity
            and not _identities_match(existing, requested)
        )
        if (
            not force
            and already_attempted
            and existing
            and not identity_changed
        ):
            return None
        if not force and already_attempted and not has_identity:
            return None
        _child_sync_attempted_sids.add(sid)

    identity, candidate, source, error = _resolve_child_sync_target(
        sid,
        payload,
    )
    capability_value = (
        capability if capability is not None else 'unknown'
    )
    if capability is not True:
        if requested.get('studentId') is not None:
            _store_child_binding(
                sid,
                {
                    'studentId': requested.get('studentId'),
                    'trainingSessionId': None,
                    'sessionId': None,
                },
                source='unsupported_student_identity_hint',
            )
        response = _child_sync_payload(
            success=False,
            reason='child_upgrade_required',
            request_id=payload.get('requestId') or payload.get('request_id'),
            capability=capability_value,
        )
        socketio.emit('child_session_sync', response, to=sid)
        return response
    if error or not identity:
        if (
            requested.get('studentId') is not None
            and (not requested.get('sessionId') or error in (
                'session_not_found',
                'session_inactive',
                'no_matching_content',
                'no_active_content',
            ))
        ):
            _store_child_binding(
                sid,
                {
                    'studentId': requested.get('studentId'),
                    'trainingSessionId': None,
                    'sessionId': None,
                },
                source='student_identity_hint',
            )
        response = _child_sync_payload(
            success=False,
            reason=error or 'binding_unavailable',
            request_id=payload.get('requestId') or payload.get('request_id'),
            capability=capability_value,
        )
        socketio.emit('child_session_sync', response, to=sid)
        return response

    previous_session_id = existing.get('sessionId')
    if not _claim_child_session_owner(str(identity['sessionId']), sid):
        response = _child_sync_payload(
            success=False,
            identity=identity,
            reason='session_owned_by_another_child',
            source=source,
            capability=capability_value,
        )
        socketio.emit('child_session_sync', response, to=sid)
        return response
    if not _move_sid_to_child_session(
        socketio,
        sid,
        str(identity['sessionId']),
        previous_session_id=previous_session_id,
    ):
        _release_child_session_owner(identity['sessionId'], sid)
        response = _child_sync_payload(
            success=False,
            identity=identity,
            reason='room_join_failed',
            source=source,
            capability=capability_value,
        )
        socketio.emit('child_session_sync', response, to=sid)
        return response

    binding = _store_child_binding(sid, identity, source=str(source))
    candidate_request_id = (
        candidate.get('requestId') if candidate else None
    )
    response = _child_sync_payload(
        success=True,
        identity=identity,
        source=source,
        request_id=candidate_request_id,
        content_available=bool(candidate),
        capability=capability_value,
    )
    # Contract: announce the exact binding before re-delivering content.
    socketio.emit('child_session_sync', response, to=sid)
    if candidate:
        should_replay = (
            binding.get('lastContentRequestId') != candidate_request_id
        )
        if should_replay:
            socketio.emit(
                'play_resource',
                dict(candidate['payload']),
                to=sid,
            )
            with _presence_lock:
                current = _child_sid_bindings.get(sid)
                if current is not None:
                    current['lastContentRequestId'] = candidate_request_id
    return response


def _room_has_participants(socketio, room: str) -> Optional[bool]:
    try:
        participants = socketio.server.manager.get_participants('/', room)
        return next(iter(participants), None) is not None
    except Exception:
        return None


def _announce_content_to_unique_unbound_child(
    socketio,
    *,
    child_room: str,
    content: Dict[str, Any],
) -> Optional[str]:
    """Bootstrap one unbound child only when the intended room is empty."""
    if _room_has_participants(socketio, child_room) is not False:
        return None
    sid = _unique_unbound_child_sid()
    identity = _child_identity(content)
    if not sid or not identity.get('sessionId'):
        return None
    if _child_sid_capabilities.get(sid) is False:
        return None
    if not _claim_child_session_owner(str(identity['sessionId']), sid):
        return None
    if not _move_sid_to_child_session(
        socketio,
        sid,
        str(identity['sessionId']),
    ):
        _release_child_session_owner(identity['sessionId'], sid)
        return None
    capability = _child_sid_capabilities.get(sid)
    _store_child_binding(
        sid,
        identity,
        source='unique_unbound_play',
    )
    sync_payload = _child_sync_payload(
        success=True,
        identity=identity,
        source='unique_unbound_play',
        request_id=content.get('requestId') or content.get('request_id'),
        content_available=True,
        capability=(
            capability if capability is not None else 'unknown'
        ),
    )
    socketio.emit('child_session_sync', sync_payload, to=sid)
    socketio.emit('play_resource', dict(content), to=sid)
    with _presence_lock:
        binding = _child_sid_bindings.get(sid)
        if binding is not None:
            binding['lastContentRequestId'] = sync_payload.get('requestId')
    return sid


def get_online_presence_snapshot() -> dict:
    """返回在线状态快照（用于 /api/server/status）。"""
    stale_ms = _PRESENCE_STALE_MS
    now = _now_ms()

    with _presence_lock:
        teacher_online = sum(
            1
            for ts in _presence_state['teacher'].values()
            if now - ts <= stale_ms
        )
        child_online = sum(
            1
            for ts in _presence_state['child'].values()
            if now - ts <= stale_ms
        )
        child_agent_online = sum(
            1
            for item in _presence_state['child_agent'].values()
            if item.get('online')
            and (now - int(item.get('lastSeenMs', 0)) <= stale_ms)
        )
        child_media_agent_online = sum(
            1
            for item in _presence_state['child_media_agent'].values()
            if item.get('online')
            and (now - int(item.get('lastSeenMs', 0)) <= stale_ms)
        )
        robot_display_online = sum(
            1
            for ts in _presence_state['robot_display'].values()
            if now - int(ts) <= stale_ms
        )
        robot_control_online = sum(
            1
            for ts in _presence_state['robot_control'].values()
            if now - int(ts) <= stale_ms
        )
        # 当前持有控制权的教师连接（sid -> training_session_id）
        controller_sids = {}
        try:
            controller_sids = get_teacher_control_registry().controller_sids()
        except Exception:
            pass
        connections = {}
        for role in ('teacher', 'child', 'child_agent', 'child_media_agent', 'robot_display', 'robot_control'):
            role_items = []
            for sid, detail in _presence_details[role].items():
                age_ms = now - int(detail.get('lastSeenMs') or 0)
                if age_ms > stale_ms or not detail.get('online', True):
                    continue
                item = dict(detail)
                item.update({'sid': sid, 'ageMs': age_ms})
                if role == 'child':
                    item.update(dict(_child_sid_bindings.get(sid) or {}))
                elif role == 'teacher':
                    item['isController'] = sid in controller_sids
                role_items.append(item)
            connections[role] = role_items

    return {
        'teacherOnline': teacher_online,
        'childOnline': child_online,
        'childAgentOnline': child_agent_online,
        'childMediaAgentOnline': child_media_agent_online,
        'robotDisplayOnline': robot_display_online,
        'robotControlOnline': robot_control_online,
        'childMediaMode': Config.get_child_media_mode(),
        'connections': connections,
        'heartbeatStaleMs': stale_ms,
    }


def register_socket_events(socketio):
    """
    注册所有WebSocket事件处理函数
    
    Args:
        socketio: Flask-SocketIO实例
    """
    
    global _socketio_server
    _socketio_server = socketio

    # 注册机械臂相关事件
    register_robot_events(socketio)

    # 开课就绪门：向指定教师 emit，或广播（teacher_sid=None）
    readiness = get_readiness_service()

    def _readiness_emit(event: str, payload: dict, teacher_sid=None):
        if teacher_sid:
            socketio.emit(event, payload, to=teacher_sid)
        else:
            socketio.emit(event, payload)

    readiness.set_emitter(_readiness_emit, socketio)
    # Explicit strict-preflight sessions cross the readiness gate through
    # the legacy recorder adapter; default/legacy sessions are untouched.
    readiness.set_capture_start_callback(start_preflight_capture)

    def _readiness_child_emit(event: str, payload: dict):
        session_id = payload.get('sessionId') or payload.get('session_id')
        if not session_id:
            logger.warning('readiness child emit 缺少 sessionId，拒绝全局广播: %s', event)
            return
        delivered, binding_error = _emit_readiness_to_child(
            socketio,
            event,
            payload,
        )
        if not delivered:
            logger.warning(
                'readiness child emit 未找到可安全绑定的儿童端: event=%s session=%s error=%s',
                event,
                session_id,
                binding_error,
            )

    readiness.set_child_emitter(_readiness_child_emit)
    
    @socketio.on('connect')
    def handle_connect():
        """处理客户端连接"""
        logger.info("客户端连接: %s", request.sid)
        emit('connected', {'status': 'ok', 'sid': request.sid})

    @socketio.on('client_presence')
    def handle_client_presence(data):
        """
        教师端 / 儿童端页面主动登记在线（连接时 + 周期心跳）。
        不再依赖 join_session / teacher_enter_control 才更新 presence。

        {
            role: 'teacher' | 'child',
            ts?: number
        }
        """
        payload = data or {}
        role = str(payload.get('role') or '').strip().lower()
        if role in ('teacher', 'child', 'robot_display', 'robot_control'):
            if role == 'teacher' and not _authenticated_teacher():
                logger.warning(
                    "拒绝未认证教师 presence: sid=%s", request.sid
                )
                emit('teacher_auth_error', {
                    'error': 'teacher_auth_required',
                })
                return
            identity = _authenticated_teacher() if role == 'teacher' else {}
            _touch_presence(role, request.sid, details={
                'ip': request.remote_addr,
                'userAgent': request.headers.get('User-Agent'),
                **(identity or {}),
            })
            if role == 'teacher':
                # 心跳续租：教师页面只要还开着（10s 心跳），lease 就不因
                # 无操作而过期，避免 90s 无操作后被误判为崩溃而 lost。
                get_teacher_control_registry().touch(request.sid)
            if role == 'child':
                _remember_child_capability(request.sid, payload)
                _sync_child_sid(
                    socketio,
                    request.sid,
                    payload,
                    force=bool(
                        payload.get('requestSync')
                        or payload.get('request_sync')
                    ),
                )
            logger.debug("client_presence: sid=%s role=%s", request.sid, role)
        else:
            logger.warning("client_presence 无效 role: %s sid=%s", role, request.sid)

    @socketio.on('teacher_latency_probe')
    def handle_teacher_latency_probe(data):
        """Lightweight RTT probe; never participates in playback gating."""
        payload = dict(data or {})
        response = {
            'probeId': payload.get('probeId'),
            'clientAtMs': payload.get('clientAtMs'),
            'serverAtMs': int(time.time() * 1000),
        }
        if not _authenticated_teacher():
            response['error'] = 'teacher_auth_required'
        emit('teacher_latency_probe_ack', response)

    @socketio.on('child_sync_request')
    def handle_child_sync_request(data):
        """Cold-reload recovery: bind and replay only to the requesting child."""
        payload = dict(data or {})
        payload.setdefault('role', 'child')
        _touch_presence('child', request.sid)
        _sync_child_sid(
            socketio,
            request.sid,
            payload,
            force=True,
        )
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """处理客户端断开连接"""
        _remove_sid_presence(request.sid)
        get_teacher_control_registry().disconnect(request.sid)
        logger.info("客户端断开连接: %s", request.sid)
    
    @socketio.on('join_session')
    def handle_join_session(data):
        """
        加入会话房间
        
        事件数据格式：
        {
            sessionId: str,
            role: str (teacher/child)
        }
        
        根据角色加入不同的房间：
        - child: session_{id}_child
        - teacher: session_{id}_teacher
        - 同时也加入通用房间 session_{id}
        """
        payload = data if isinstance(data, dict) else {}
        session_id = payload.get('sessionId') or payload.get('session_id')
        role = payload.get('role', 'unknown')
        
        if session_id:
            if role == 'child':
                _touch_presence('child', request.sid)
                _remember_child_capability(request.sid, payload)
                identity, identity_error = _runtime_child_identity({
                    **_child_identity(payload),
                    'sessionId': str(session_id),
                })
                if identity_error or not _claim_child_session_owner(
                    str(session_id), request.sid
                ):
                    emit('joined_session', {
                        'sessionId': session_id,
                        'role': role,
                        'status': 'error',
                        'error': (
                            identity_error
                            or 'session_owned_by_another_child'
                        ),
                    })
                    return
                join_room(session_id)
                child_room = f"session_{session_id}_child"
                join_room(child_room)
                _store_child_binding(
                    request.sid,
                    identity,
                    source='join_session',
                )
                logger.info("儿童端加入房间: %s, %s", session_id, child_room)
            elif role == 'teacher':
                access = _teacher_control_access(payload, claim=True)
                if not access.get('ok'):
                    emit('joined_session', {
                        'sessionId': session_id,
                        'role': role,
                        'status': 'error',
                        **_control_rejection(access),
                    })
                    return
                _notify_replaced_teacher(access)
                join_room(session_id)
                teacher_room = f"session_{session_id}_teacher"
                join_room(teacher_room)
                _touch_presence('teacher', request.sid)
                logger.info("教师端加入房间: %s, %s", session_id, teacher_room)
            else:
                join_room(session_id)
            
            logger.info("客户端加入会话房间: sid=%s, session=%s, role=%s",
                       request.sid, session_id, role)
            emit('joined_session', {
                'sessionId': session_id,
                'role': role,
                'status': 'ok',
                'controlRole': (
                    (access.get('lease') or {}).get('controlRole')
                    if role == 'teacher'
                    else None
                ),
                'lease': access.get('lease') if role == 'teacher' else None,
            })
    
    @socketio.on('leave_session')
    def handle_leave_session(data):
        """
        离开会话房间
        
        事件数据格式：
        {
            sessionId: str
        }
        """
        payload = data if isinstance(data, dict) else {}
        session_id = payload.get('sessionId') or payload.get('session_id')
        
        if session_id:
            leave_room(session_id)
            leave_room(f"session_{session_id}_teacher")
            leave_room(f"session_{session_id}_child")
            with _presence_lock:
                binding = _child_sid_bindings.get(request.sid)
                if (
                    binding
                    and str(binding.get('sessionId')) == str(session_id)
                ):
                    _child_sid_bindings.pop(request.sid, None)
                    _child_sync_attempted_sids.discard(request.sid)
                if _child_session_owners.get(str(session_id)) == request.sid:
                    _child_session_owners.pop(str(session_id), None)
            logger.info("客户端离开会话房间: sid=%s, session=%s",
                       request.sid, session_id)

    def _forward_resource_transition(event_name: str, data, sender_sid: str):
        payload = dict(data or {})
        session_id = payload.get('sessionId') or payload.get('session_id')
        if not session_id:
            logger.warning('%s 缺少 sessionId: %s', event_name, payload)
            return
        if not _is_authorized_child_sender(
            sender_sid,
            payload,
            require_cached_request=True,
        ):
            logger.warning(
                '%s 拒绝非 owner/非关联请求: sid=%s payload=%s',
                event_name,
                sender_sid,
                payload,
            )
            return
        payload['sessionId'] = str(session_id)
        payload['session_id'] = str(session_id)
        if event_name == 'resource_ready':
            _record_latency_modality_callback(
                payload,
                phase='started',
                modality='display',
            )
        # The first child can decode before the teacher has processed its own
        # play_resource copy and joined the teacher room. Correlate the original
        # requester so that first-frame readiness cannot be lost in that race.
        request_id = payload.get('requestId') or payload.get('request_id')
        requester_sid = None
        if request_id:
            with _play_request_lock:
                entry = _play_request_cache.get(str(request_id))
                requester_sid = entry.get('requesterSid') if entry else None
        teacher_room = f'session_{session_id}_teacher'
        if requester_sid:
            socketio.emit(
                event_name,
                payload,
                room=teacher_room,
                skip_sid=requester_sid,
            )
            socketio.emit(event_name, payload, to=requester_sid)
        else:
            socketio.emit(event_name, payload, room=teacher_room)

    @socketio.on('resource_ready')
    def handle_resource_ready(data):
        """Child confirms that the correlated resource is decoded and visible."""
        _forward_resource_transition('resource_ready', data, request.sid)

    @socketio.on('resource_transition_failed')
    def handle_resource_transition_failed(data):
        """Child reports a correlated resource load/transition failure."""
        _forward_resource_transition(
            'resource_transition_failed', data, request.sid
        )

    @socketio.on('freeze_course_frame')
    def handle_freeze_course_frame(data):
        if not _teacher_write_allowed('freeze_course_frame', data):
            return
        """Freeze only the correlated child's current course frame for rating."""
        target = _build_child_session_forward(data)
        if not target:
            logger.warning('freeze_course_frame 缺少 sessionId: %s', data)
            return
        payload, _child_room = target
        child_sid = _child_owner_for_session(payload.get('sessionId'))
        if not child_sid:
            logger.warning('freeze_course_frame 无在线 owner: %s', payload)
            return
        socketio.emit('freeze_course_frame', payload, to=child_sid)

    @socketio.on('robot_motion_ack')
    def handle_robot_motion_ack(data):
        """
        机器人端网页对动作命令的执行确认。
        """
        logger.info(
            "robot_motion_ack: sid=%s, command=%s, ok=%s, error=%s",
            request.sid,
            data.get('commandId') if data else None,
            data.get('ok') if data else None,
            data.get('error') if data else None,
        )

    @socketio.on('teacher_enter_control')
    def handle_teacher_enter_control(data):
        """
        教师进入控制界面 -> 通知儿童端隐藏待机图

        事件数据格式：
        {
            status: "enter"
        }
        """
        access = _teacher_control_access(data, claim=True)
        if not access.get('ok') or not access.get('writable'):
            emit('teacher_control_state', _control_rejection(access))
            return
        _notify_replaced_teacher(access)
        emit('teacher_control_state', {
            'success': True,
            'controlRole': 'controller',
            'lease': access.get('lease'),
            'trainingSessionId': access.get('trainingSessionId'),
        })
        logger.info("教师进入控制界面: sid=%s, data=%s", request.sid, data)
        _touch_presence('teacher', request.sid)
        payload = dict(data or {})
        session_id = payload.get('sessionId') or payload.get('session_id')
        target_session_ids = (
            [str(session_id)]
            if session_id
            else _runtime_session_ids_for_training(
                access.get('trainingSessionId')
            )
        )
        for target_session_id in target_session_ids:
            emit(
                'teacher_enter_control',
                payload,
                room=f'session_{target_session_id}_child',
            )

    @socketio.on('child_agent_heartbeat')
    def handle_child_agent_heartbeat(data):
        """
        儿童端页面上报本机 Robot Agent 在线状态。
        同时刷新 child 页面 presence（能发心跳说明 /child 仍在线）。
        """
        payload = data or {}
        _touch_presence('child', request.sid)
        _touch_presence(
            'child_agent',
            request.sid,
            online=bool(payload.get('agentOnline', False)),
        )
        detail = payload.get('detail') if isinstance(payload.get('detail'), dict) else {}
        advertised_url = detail.get('advertisedUrl')
        if payload.get('agentOnline') and advertised_url:
            try:
                from app.robot.runtime_registry import prefer_runtime

                prefer_runtime(
                    advertised_url,
                    source=f'child_socket:{request.sid}',
                )
            except Exception as exc:
                logger.warning('绑定儿童端 Runtime 失败: %s', exc)

    @socketio.on('child_media_agent_heartbeat')
    def handle_child_media_agent_heartbeat(data):
        """儿童端页面上报本机 Media Agent 在线状态。"""
        payload = data or {}
        _touch_presence('child', request.sid)
        _touch_presence(
            'child_media_agent',
            request.sid,
            online=bool(payload.get('agentOnline', False)),
        )

    @socketio.on('teacher_leave_control')
    def handle_teacher_leave_control(data):
        """
        教师离开控制界面 -> 通知儿童端显示待机图

        事件数据格式：
        {
            status: "leave"
        }
        """
        access = _teacher_control_access(data)
        if not access.get('ok') or not access.get('writable'):
            emit('teacher_control_state', _control_rejection(access))
            return
        logger.info("教师离开控制界面: sid=%s, data=%s", request.sid, data)
        payload = dict(data or {})
        session_id = payload.get('sessionId') or payload.get('session_id')
        target_session_ids = (
            [str(session_id)]
            if session_id
            else _runtime_session_ids_for_training(
                access.get('trainingSessionId')
            )
        )
        for target_session_id in target_session_ids:
            emit(
                'teacher_leave_control',
                payload,
                room=f'session_{target_session_id}_child',
            )
        training_id = access.get('trainingSessionId')
        payload.setdefault('trainingSessionId', training_id)
        payload.setdefault('operationId', f"teacher-leave:{training_id}")
        payload.setdefault('requestId', payload['operationId'])
        try:
            result = FinalizeTrainingHandler.handle(payload)
            if result.get('success'):
                get_readiness_service().cancel(training_session_id=training_id)
            for stopped_session_id in result.get('stoppedRuntimeSessions') or []:
                emit('stop_recording', {
                    'sessionId': stopped_session_id,
                    'trainingSessionId': training_id,
                    'reason': 'teacher_leave_control',
                    'operationId': payload['operationId'],
                }, room=f'session_{stopped_session_id}_child')
            emit('teacher_leave_control_ack', {
                **result,
                'operationId': payload['operationId'],
            })
        except Exception as exc:
            logger.error("teacher_leave_control finalize failed: %s", exc, exc_info=True)
            emit('teacher_leave_control_ack', {
                'success': False,
                'error': str(exc),
                'trainingSessionId': training_id,
            })
        get_teacher_control_registry().release(
            training_id,
            teacher_id=access['teacher']['teacherId'],
            sid=request.sid,
        )
    
    @socketio.on('play_resource')
    def handle_play_resource(data):
        """
        处理播放资源事件

        事件数据格式：
        {
            action: "play",
            studentId: int (必需),
            courseId: int,
            itemId: int | null,
            aux: {
                question?: bool,
                praise?: bool,
                hint?: bool
            }
        }
        """

        def _aux_flags(payload):
            aux = (payload or {}).get('aux') if isinstance(payload, dict) else None
            if not isinstance(aux, dict):
                return {}
            return aux

        def _has_aux_intent(payload):
            """提问/表扬/提示/社交语音才算 aux；切课点（仅 targetImage 等）不算。"""
            aux = _aux_flags(payload)
            return bool(
                aux.get('question')
                or aux.get('praise')
                or aux.get('hint')
                or aux.get('attention')
                or aux.get('reward')
                or aux.get('socialGreetingIntro')
                or aux.get('socialGreetingPlay')
                or aux.get('socialFarewellBye')
                or aux.get('socialFarewellReply')
            )

        payload = dict(data or {})
        request_id = str(
            payload.get('requestId')
            or payload.get('request_id')
            or f'request-{uuid.uuid4().hex[:12]}'
        )
        payload['requestId'] = request_id
        payload['request_id'] = request_id
        received_at_ms = time.time() * 1000.0
        received_at_monotonic = time.monotonic()
        try:
            from app.behavior.audit_timeline import record_audit_event

            record_audit_event(
                'latency.play_resource_received',
                training_session_id=payload.get('trainingSessionId'),
                runtime_session_id=(
                    payload.get('sessionId') or payload.get('session_id')
                ),
                question_id=(
                    payload.get('questionId') or payload.get('question_id')
                ),
                request_id=request_id,
                behavior_id=(
                    payload.get('behaviorId') or payload.get('behavior_id')
                ),
                actor='server',
                source='socketio',
                category='latency',
                phase='received',
                status='observed',
                client_timestamp=payload.get('clientCommandAtMs'),
                details={
                    'teacherNetworkRttMs': payload.get('teacherNetworkRttMs'),
                    'clientTransport': payload.get('clientTransport'),
                    'serverReceivedAtMs': received_at_ms,
                    'request': {
                        'courseType': payload.get('courseType'),
                        'courseId': payload.get('courseId'),
                        'itemId': payload.get('itemId'),
                        'aux': payload.get('aux'),
                    },
                },
            )
        except Exception:
            logger.debug(
                'play_resource latency receive audit failed request=%s',
                request_id,
                exc_info=True,
            )
        access = _teacher_control_access(payload)
        if not access.get('ok') or not access.get('writable'):
            logger.warning(
                'play_resource 被拒 request=%s question=%s error=%s',
                request_id,
                payload.get('questionId') or payload.get('question_id'),
                access.get('error'),
            )
            _emit_play_resource_ack({
                **_control_rejection(access),
                'requestId': request_id,
                'request_id': request_id,
            })
            return
        wants_aux = _has_aux_intent(payload)
        logger.info(
            'play_resource 收到 request=%s question=%s aux=%s',
            request_id,
            payload.get('questionId') or payload.get('question_id'),
            wants_aux,
        )
        resource_ready_supported = _resource_ready_support_for_identity(
            payload,
            include_unique_unbound=True,
        )

        duplicate = _claim_play_request(
            request_id,
            requester_sid=request.sid,
        )
        if duplicate:
            cached_ack = duplicate.get('ack')
            if cached_ack:
                cached_ack = dict(cached_ack)
                cached_content = duplicate.get('contentForwardData')
                cached_ack['resourceReadySupported'] = (
                    _resource_ready_support_for_identity(
                        (
                            cached_content
                            if isinstance(cached_content, dict)
                            else payload
                        ),
                        include_unique_unbound=True,
                    )
                )
                replayed_content = False
                try:
                    replayed_content = _replay_cached_content(
                        socketio,
                        duplicate,
                    )
                except Exception as replay_error:
                    logger.warning(
                        '幂等内容重定向失败 request=%s: %s',
                        request_id,
                        replay_error,
                    )
                try:
                    from app.robot import get_robot_service

                    current_state = get_robot_service().get_behavior_busy_state()
                except Exception:
                    current_state = {}
                if current_state.get('eventId') == cached_ack.get('behaviorId'):
                    cached_ack['remainingMs'] = int(
                        current_state.get('remainingMs') or 0
                    )
                    cached_ack['activeBehaviorId'] = current_state.get('eventId')
                else:
                    cached_ack['remainingMs'] = 0
                    cached_ack['activeBehaviorId'] = None
                logger.info('幂等重放 play_resource_ack request=%s', request_id)
                if replayed_content:
                    cached_ack['contentReplayed'] = True
                _emit_play_resource_ack(cached_ack)
                return
            try:
                from app.robot import get_robot_service
                state = get_robot_service().get_behavior_busy_state()
            except Exception:
                state = {}
            active_id = duplicate.get('behaviorId') or state.get('eventId')
            _emit_play_resource_ack({
                'accepted': False,
                'busy': True,
                'reason': 'request_in_progress',
                'error': 'request_in_progress',
                'message': '同一请求仍在处理中，本次重放未重复执行',
                'requestId': request_id,
                'behaviorId': active_id,
                'interactionId': active_id,
                'activeBehaviorId': active_id,
                'remainingMs': int(state.get('remainingMs') or 0),
                'isAux': wants_aux,
                'resourceReadySupported': resource_ready_supported,
            })
            return

        if not wants_aux and resource_ready_supported is False:
            rejected_ack = {
                'accepted': False,
                'busy': False,
                'reason': 'child_upgrade_required',
                'error': 'child_upgrade_required',
                'message': '在线儿童端版本过旧，不支持资源首帧确认，请刷新儿童端后重试',
                'requestId': request_id,
                'behaviorId': None,
                'interactionId': None,
                'activeBehaviorId': None,
                'remainingMs': 0,
                'isAux': False,
                'resourceReadySupported': False,
            }
            _update_play_request(request_id, keep=False)
            _emit_play_resource_ack(rejected_ack)
            return

        robot_service = None
        behavior_id = None
        try:
            from app.robot import get_robot_service
            robot_service = get_robot_service()
            reservation = robot_service.reserve_behavior(
                behavior_id=(
                    payload.get('behaviorId')
                    or payload.get('behavior_id')
                    or payload.get('interactionId')
                ),
                request_id=request_id,
            )
        except Exception as e:
            logger.error('行为预占失败 request=%s: %s', request_id, e, exc_info=True)
            _update_play_request(request_id, keep=False)
            _emit_play_resource_ack({
                'accepted': False,
                'busy': False,
                'reason': 'behavior_reservation_failed',
                'error': str(e),
                'message': '无法预占行为播放槽位',
                'requestId': request_id,
                'behaviorId': None,
                'interactionId': None,
                'activeBehaviorId': None,
                'remainingMs': 0,
                'isAux': wants_aux,
                'resourceReadySupported': resource_ready_supported,
            })
            return

        if not reservation.get('accepted'):
            active_id = reservation.get('activeBehaviorId') or reservation.get('behaviorId')
            logger.warning(
                'play_resource 行为繁忙拒绝 request=%s question=%s active_behavior=%s remaining_ms=%s',
                request_id,
                payload.get('questionId') or payload.get('question_id'),
                active_id,
                reservation.get('remainingMs'),
            )
            rejected_ack = {
                'accepted': False,
                'busy': True,
                'reason': 'behavior_busy',
                'error': 'behavior_busy',
                'message': '当前行为尚未播放完成，本次请求未执行',
                'requestId': request_id,
                'behaviorId': active_id,
                'interactionId': active_id,
                'activeBehaviorId': active_id,
                'remainingMs': int(reservation.get('remainingMs') or 0),
                'trainingSessionId': payload.get('trainingSessionId'),
                'isAux': wants_aux,
                'resourceReadySupported': resource_ready_supported,
            }
            # A busy request may safely retry the same requestId after the
            # active behavior completes, so do not retain this rejection.
            _update_play_request(request_id, keep=False)
            _emit_play_resource_ack(rejected_ack)
            emit('behavior_trigger_rejected', rejected_ack)
            return

        behavior_id = str(reservation.get('behaviorId'))
        payload['behaviorId'] = behavior_id
        payload['behavior_id'] = behavior_id
        payload['interactionId'] = behavior_id
        _update_play_request(
            request_id,
            behavior_id=behavior_id,
            requester_sid=request.sid,
        )

        try:
            # All course/session mutations happen only after the atomic reserve.
            result = PlayResourceHandler.handle(payload)
            if not result or not result.get('session_id'):
                raise RuntimeError('play_resource_session_unavailable')

            session_id = str(result.get('session_id'))
            training_session_id = result.get('training_session_id')
            question_id = result.get('question_id')
            resolved_file = result.get('resolved_file')
            is_aux_op = bool(result.get('is_aux_operation', False))
            behavior_animation = result.get('behavior_animation')
            aux_flags = _aux_flags(payload)
            interaction_event_type = (
                'question_presented' if aux_flags.get('question')
                else 'praise' if aux_flags.get('praise')
                else 'attention_intervention' if aux_flags.get('attention')
                else 'attention_reward' if aux_flags.get('reward')
                else 'hint' if aux_flags.get('hint')
                else 'social_prompt' if any(
                    aux_flags.get(key) for key in (
                        'socialGreetingIntro', 'socialGreetingPlay',
                        'socialFarewellBye', 'socialFarewellReply',
                    )
                )
                else 'content_presented'
            )
            interaction_context = {
                'trainingSessionId': training_session_id,
                'sessionId': session_id,
                'questionId': question_id,
                'requestId': request_id,
                'behaviorId': behavior_id,
                'eventType': interaction_event_type,
                'isAux': is_aux_op,
            }
            _update_play_request(
                request_id,
                behavior_id=behavior_id,
                interaction_context=interaction_context,
            )
            resolved_target_identity = dict(payload)
            resolved_target_identity['sessionId'] = session_id
            if training_session_id:
                resolved_target_identity[
                    'trainingSessionId'
                ] = training_session_id
            child_sid, child_binding_error = _assign_child_for_identity(
                socketio,
                _child_identity(resolved_target_identity),
                source='play_resource',
            )
            if (
                not child_sid
                and child_binding_error not in ('child_offline', None)
            ):
                robot_service.abort_behavior(behavior_id)
                failure_ack = {
                    'accepted': False,
                    'busy': False,
                    'reason': 'child_binding_failed',
                    'error': child_binding_error,
                    'message': '无法唯一确定目标儿童端，本次行为未下发',
                    'requestId': request_id,
                    'behaviorId': behavior_id,
                    'interactionId': behavior_id,
                    'activeBehaviorId': None,
                    'remainingMs': 0,
                    'sessionId': session_id,
                    'trainingSessionId': training_session_id,
                    'questionId': question_id,
                    'isAux': is_aux_op,
                }
                _update_play_request(request_id, keep=False)
                _emit_play_resource_ack(failure_ack)
                emit('behavior_trigger_rejected', failure_ack)
                return
            resource_ready_supported = (
                _resource_ready_support_for_identity(
                    resolved_target_identity,
                    include_unique_unbound=True,
                )
            )
            if (
                not wants_aux
                and not is_aux_op
                and resource_ready_supported is False
            ):
                robot_service.abort_behavior(behavior_id)
                failure_ack = {
                    'accepted': False,
                    'busy': False,
                    'reason': 'child_upgrade_required',
                    'error': 'child_upgrade_required',
                    'message': '在线儿童端版本过旧，不支持资源首帧确认，请刷新儿童端后重试',
                    'requestId': request_id,
                    'behaviorId': behavior_id,
                    'interactionId': behavior_id,
                    'activeBehaviorId': None,
                    'remainingMs': 0,
                    'sessionId': session_id,
                    'trainingSessionId': training_session_id,
                    'questionId': question_id,
                    'isAux': False,
                    'resourceReadySupported': False,
                }
                _update_play_request(request_id, keep=False)
                _emit_play_resource_ack(failure_ack)
                emit('behavior_trigger_rejected', failure_ack)
                return

            robot_event_data = dict(payload)
            robot_event_data['sessionId'] = session_id
            robot_result = _start_or_defer_course_behavior(
                robot_service,
                robot_event_data,
            )
            if not robot_result.get('success'):
                robot_service.abort_behavior(behavior_id)
                failure_ack = {
                    'accepted': False,
                    'busy': bool(robot_result.get('busy')),
                    'reason': (
                        'behavior_busy'
                        if robot_result.get('busy')
                        else 'behavior_start_failed'
                    ),
                    'error': robot_result.get('message') or 'behavior_start_failed',
                    'message': robot_result.get('message') or '行为未能启动',
                    'requestId': request_id,
                    'behaviorId': (
                        robot_result.get('eventId') or behavior_id
                    ),
                    'interactionId': (
                        robot_result.get('eventId') or behavior_id
                    ),
                    'activeBehaviorId': robot_result.get('eventId'),
                    'remainingMs': int(robot_result.get('remainingMs') or 0),
                    'sessionId': session_id,
                    'trainingSessionId': training_session_id,
                    'questionId': question_id,
                    'isAux': is_aux_op,
                    'resourceReadySupported': (
                        resource_ready_supported
                    ),
                }
                _update_play_request(request_id, keep=False)
                _emit_play_resource_ack(failure_ack)
                return

            # Build one correlated payload, then target the child room. The
            # request sender receives its own copy so existing teacher logic can
            # still join the session without broadcasting to unrelated clients.
            forward_data = dict(payload)
            forward_data['sessionId'] = session_id
            forward_data['behaviorId'] = behavior_id
            forward_data['interactionId'] = behavior_id
            forward_data['protocolVersion'] = '1'
            forward_data['requestId'] = request_id
            forward_data['modality'] = 'childAnimation'
            if training_session_id:
                forward_data['trainingSessionId'] = training_session_id
            if question_id:
                forward_data['questionId'] = question_id
            if resolved_file:
                forward_data['resolvedFile'] = resolved_file
            if behavior_animation:
                forward_data['behaviorAnimation'] = behavior_animation
                # One-release compatibility alias for children cached before
                # encouragement animations moved into behavior bindings.
                forward_data['praiseVideo'] = behavior_animation
            if robot_result.get('startAtEpochMs') is not None:
                forward_data['behaviorStartAtMs'] = int(
                    robot_result.get('startAtEpochMs')
                )
                forward_data['startAtServerMs'] = int(
                    robot_result.get('startAtEpochMs')
                )
            if result.get('recording_mode'):
                forward_data['recordingMode'] = result.get('recording_mode')
            if result.get('human_dir_name'):
                forward_data['humanDirName'] = result.get('human_dir_name')
            if result.get('speech_target'):
                forward_data['speechTarget'] = result.get('speech_target')
            if result.get('item_name'):
                forward_data['itemName'] = result.get('item_name')
            if result.get('page_context'):
                forward_data['pageContext'] = result.get('page_context')
            if result.get('mode'):
                forward_data['mode'] = result.get('mode')
            forward_data['mediaMode'] = Config.get_child_media_mode()

            child_room = f'session_{session_id}_child'

            # Praise animation must be decoded before the shared behavior
            # anchor. Previously the child did not receive its media path until
            # after speech/expression/motion had already been committed.
            if behavior_animation and child_sid:
                forward_data['behaviorStartDelayMs'] = (
                    _remaining_behavior_start_delay_ms(robot_result)
                )
                socketio.emit(
                    'prepare_behavior_animation',
                    forward_data,
                    to=child_sid,
                )

            audio_details = {
                'triggered': False,
                'dispatchCount': 0,
                'deferred': False,
            }
            if bool(robot_result.get('speechConfigured')):
                audio_details = _dispatch_v2_speech_commands(
                    robot_result.get('speechCommands') or [],
                    session_id=str(session_id),
                    child_room=child_room,
                    behavior_id=str(behavior_id),
                    request_id=str(request_id),
                    base_delay_ms=_remaining_behavior_start_delay_ms(
                        robot_result
                    ),
                )
            elif should_process_play_audio(
                audio_pending=bool(result.get('audio_pending')),
                skip_robot_due_to_busy=False,
                wants_aux=wants_aux,
                is_aux_op=is_aux_op,
            ):
                audio_data = dict(payload)
                if result.get('item_name'):
                    audio_data['itemName'] = result.get('item_name')
                if result.get('speech_target'):
                    audio_data['speechTarget'] = result.get('speech_target')
                if result.get('page_context'):
                    audio_data['pageContext'] = result.get('page_context')
                try:
                    from app.audio import get_audio_service

                    audio_details = get_audio_service().process_play_resource(
                        session_id,
                        audio_data,
                        sequence_delay_ms=_remaining_behavior_start_delay_ms(
                            robot_result
                        ),
                        behavior_id=behavior_id,
                        request_id=request_id,
                        return_details=True,
                    )
                    if not isinstance(audio_details, dict):
                        audio_details = {
                            'triggered': bool(audio_details),
                            'dispatchCount': 1 if audio_details else 0,
                        }
                except Exception as audio_error:
                    logger.error(
                        '语音系统处理失败 behavior=%s: %s',
                        behavior_id,
                        audio_error,
                        exc_info=True,
                    )
                    audio_details = {
                        'triggered': False,
                        'dispatchCount': 0,
                        'deferred': False,
                    }

            if should_reject_atomic_audio(
                wants_aux=wants_aux,
                audio_details=audio_details,
            ):
                # The sequence worker is held behind the dispatch decision
                # barrier.  Abort now so expression/motion never become visible
                # when their required speech could not be delivered.
                robot_service.abort_behavior(behavior_id)
                failure_ack = {
                    'accepted': False,
                    'busy': False,
                    'reason': 'audio_dispatch_failed',
                    'error': 'audio_dispatch_failed',
                    'message': '语音未能下发，本次动作、表情和语音已整组取消',
                    'requestId': request_id,
                    'behaviorId': behavior_id,
                    'interactionId': behavior_id,
                    'activeBehaviorId': None,
                    'remainingMs': 0,
                    'sessionId': session_id,
                    'trainingSessionId': training_session_id,
                    'questionId': question_id,
                    'isAux': is_aux_op,
                    'audioDispatched': False,
                    'audioDispatchCount': 0,
                    'resourceReadySupported': (
                        resource_ready_supported
                    ),
                }
                # A transient audio failure may safely retry the same requestId.
                _update_play_request(request_id, keep=False)
                _emit_play_resource_ack(failure_ack)
                emit('behavior_trigger_rejected', failure_ack)
                return

            if bool((audio_details or {}).get('deferred')):
                _remember_deferred_ordering_question(
                    session_id,
                    payload=robot_event_data,
                    behavior_id=behavior_id,
                    request_id=request_id,
                )

            animation_commit_ok = robot_service.set_behavior_animation_expected(
                behavior_id,
                bool(behavior_animation),
                session_id=session_id,
            )
            if not animation_commit_ok:
                robot_service.abort_behavior(behavior_id)
                _update_play_request(request_id, keep=False)
                _emit_play_resource_ack({
                    'accepted': False,
                    'success': False,
                    'error': 'animation_barrier_commit_failed',
                    'requestId': request_id,
                    'behaviorId': behavior_id,
                    'sessionId': session_id,
                    'trainingSessionId': training_session_id,
                })
                return

            if robot_result.get('skipped'):
                # Default content load has no actual robot behavior. Release
                # before ACK so the ACK-driven question can reserve immediately.
                robot_service.abort_behavior(behavior_id)
            else:
                try:
                    commit_ok = robot_service.set_behavior_audio_expected(
                        behavior_id,
                        int(
                            (audio_details or {}).get('dispatchCount') or 0
                        ),
                        session_id=session_id,
                    )
                except Exception as commit_error:
                    logger.error(
                        '行为语音提交失败 behavior=%s: %s',
                        behavior_id,
                        commit_error,
                        exc_info=True,
                    )
                    commit_ok = False
                if not commit_ok:
                    robot_service.abort_behavior(behavior_id)
                    failure_ack = {
                        'accepted': False,
                        'busy': False,
                        'reason': 'behavior_commit_failed',
                        'error': 'behavior_commit_failed',
                        'message': '动作、表情与语音未能原子提交，本次行为已取消',
                        'requestId': request_id,
                        'behaviorId': behavior_id,
                        'interactionId': behavior_id,
                        'activeBehaviorId': None,
                        'remainingMs': 0,
                        'sessionId': session_id,
                        'trainingSessionId': training_session_id,
                        'questionId': question_id,
                        'isAux': is_aux_op,
                        'audioDispatched': bool(
                            (audio_details or {}).get('triggered')
                        ),
                        'audioDispatchCount': int(
                            (audio_details or {}).get(
                                'dispatchCount'
                            ) or 0
                        ),
                        'resourceReadySupported': (
                            resource_ready_supported
                        ),
                    }
                    _update_play_request(request_id, keep=False)
                    _emit_play_resource_ack(failure_ack)
                    emit('behavior_trigger_rejected', failure_ack)
                    return

            # Commit the child-facing resource only after required audio and
            # the behavior dispatch barrier have both succeeded.  Never widen
            # an empty room into a broadcast.
            # Use a fresh relative delay for child browsers; unlike wall-clock
            # timestamps this is safe when classroom machines have clock skew.
            forward_data['behaviorStartDelayMs'] = (
                _remaining_behavior_start_delay_ms(robot_result)
            )
            try:
                from app.behavior.audit_timeline import record_audit_event

                record_audit_event(
                    'latency.multimodal_dispatched',
                    training_session_id=training_session_id,
                    runtime_session_id=session_id,
                    question_id=question_id,
                    request_id=request_id,
                    behavior_id=behavior_id,
                    actor='server',
                    source='socketio',
                    category='latency',
                    phase='dispatched',
                    status='observed',
                    modality='multimodal',
                    details={
                        'serverElapsedMs': int(round(
                            (time.monotonic() - received_at_monotonic) * 1000
                        )),
                        'startAtServerMs': robot_result.get('startAtEpochMs'),
                        'remainingLeadMs': forward_data['behaviorStartDelayMs'],
                        'audioDispatched': bool(
                            (audio_details or {}).get('triggered')
                        ),
                        'audioDispatchCount': int(
                            (audio_details or {}).get('dispatchCount') or 0
                        ),
                        'childOnline': bool(child_sid),
                        'animationExpected': bool(behavior_animation),
                    },
                )
            except Exception:
                logger.debug(
                    'play_resource latency dispatch audit failed request=%s',
                    request_id,
                    exc_info=True,
                )
            if not wants_aux and not is_aux_op:
                # Publish the correlation before the child can return a very
                # fast first-frame ACK.
                _update_play_request(
                    request_id,
                    behavior_id=behavior_id,
                    content_forward_data=forward_data,
                    child_room=child_room,
                    child_sid=child_sid,
                    is_aux=False,
                )
            emit('play_resource', forward_data)
            if child_sid:
                socketio.emit('play_resource', forward_data, to=child_sid)
            else:
                logger.info(
                    '儿童端离线，内容已缓存等待安全同步: session=%s',
                    session_id,
                )

            busy_state = robot_service.get_behavior_busy_state()
            remaining_ms = (
                int(busy_state.get('remainingMs') or 0)
                if busy_state.get('eventId') == behavior_id
                else 0
            )
            success_ack = {
                'accepted': True,
                'busy': False,
                'requestId': request_id,
                'behaviorId': behavior_id,
                'interactionId': behavior_id,
                'activeBehaviorId': (
                    behavior_id if remaining_ms > 0 else None
                ),
                'remainingMs': remaining_ms,
                'sessionId': session_id,
                'trainingSessionId': training_session_id,
                'questionId': question_id,
                'isAux': is_aux_op,
                'audioDispatched': bool((audio_details or {}).get('triggered')),
                'audioDispatchCount': int(
                    (audio_details or {}).get('dispatchCount') or 0
                ),
                'animationExpected': bool(behavior_animation),
                'animationSkipped': not bool(behavior_animation),
                'audioDeferred': bool(
                    (audio_details or {}).get('deferred')
                ),
                'resourceReadySupported': resource_ready_supported,
            }
            if robot_result.get('shadowReport'):
                success_ack['shadowReport'] = robot_result.get('shadowReport')
            _update_play_request(
                request_id,
                behavior_id=behavior_id,
                ack=success_ack,
                content_forward_data=(
                    forward_data
                    if not wants_aux and not is_aux_op
                    else None
                ),
                child_room=child_room,
                child_sid=child_sid,
                is_aux=bool(wants_aux or is_aux_op),
            )
            if not child_sid and not wants_aux and not is_aux_op:
                _announce_content_to_unique_unbound_child(
                    socketio,
                    child_room=child_room,
                    content=forward_data,
                )
            _emit_play_resource_ack(success_ack)
            _record_interaction(
                interaction_event_type,
                interaction_context,
                actor='teacher',
                metadata={
                    'audioDispatched': success_ack['audioDispatched'],
                    'audioDispatchCount': success_ack['audioDispatchCount'],
                    'animationExpected': success_ack['animationExpected'],
                },
            )
            logger.info(
                'play_resource accepted request=%s behavior=%s session=%s remaining=%sms',
                request_id,
                behavior_id,
                session_id,
                remaining_ms,
            )
        except Exception as e:
            logger.error("处理play_resource事件时出错: %s", e, exc_info=True)
            if robot_service and behavior_id:
                robot_service.abort_behavior(behavior_id)
            _update_play_request(request_id, keep=False)
            _emit_play_resource_ack({
                'accepted': False,
                'busy': False,
                'reason': 'play_resource_failed',
                'error': str(e),
                'message': '播放资源处理失败，未下发部分行为',
                'requestId': request_id,
                'behaviorId': behavior_id,
                'interactionId': behavior_id,
                'activeBehaviorId': None,
                'remainingMs': 0,
                'isAux': wants_aux,
                'resourceReadySupported': (
                    resource_ready_supported
                ),
            })
    
    @socketio.on('video_frame')
    def handle_video_frame(data):
        """
        处理视频帧事件
        
        事件数据格式：
        {
            sessionId: str (必需),
            frame: str (base64编码的视频帧),
            timestamp: float (可选)
        }
        """
        try:
            if not _is_authorized_child_sender(request.sid, data):
                logger.warning('拒绝非 owner 视频帧: sid=%s', request.sid)
                return
            success = VideoFrameHandler.handle(data)
            if not success:
                logger.warning("视频帧处理失败: %s", data.get('sessionId'))
        except Exception as e:
            logger.error("处理video_frame事件时出错: %s", e, exc_info=True)
    
    @socketio.on('audio_chunk')
    def handle_audio_chunk(data):
        """
        处理音频块事件
        
        事件数据格式：
        {
            sessionId: str (必需),
            chunk: str (base64编码的音频块),
            timestamp: float (可选)
        }
        """
        try:
            if not _is_authorized_child_sender(request.sid, data):
                logger.warning('拒绝非 owner 音频块: sid=%s', request.sid)
                return
            success = AudioChunkHandler.handle(data)
            if not success:
                logger.warning("音频块处理失败: %s", data.get('sessionId'))
        except Exception as e:
            logger.error("处理audio_chunk事件时出错: %s", e, exc_info=True)

    @socketio.on('camera_analysis')
    def handle_camera_analysis(data):
        """浏览器端注意力/情绪描述符入库（不上传原图）。"""
        try:
            if not _is_authorized_child_sender(request.sid, data):
                logger.warning('拒绝非 owner 摄像头分析: sid=%s', request.sid)
                return
            from app.behavior import get_behavior_service
            from app.behavior.camera_config import load_camera_analysis_config
            if not load_camera_analysis_config().get("enabled", True):
                return
            ok = get_behavior_service().ingest_camera_analysis(data or {})
            if not ok:
                return
            session_id = (data or {}).get("sessionId")
            if not session_id:
                return
            visual = (data or {}).get("visualFeatures") or {}
            face_present = bool(visual.get("facePresent"))
            score100 = visual.get("attentionScore100")
            if score100 is None and visual.get("facingScore") is not None:
                score100 = float(visual["facingScore"]) * 100.0
            score100 = float(score100 or 0)
            # 无脸帧不推 0 分，避免教师端在正常高分后突然跳到几分
            if not face_present:
                return
            emit(
                "attention_update",
                {
                    "session_id": session_id,
                    "score": round(score100, 1),
                    "score_scale": "0-100",
                    "state": "high" if score100 >= 70 else ("medium" if score100 >= 40 else "low"),
                    "provider": "browser",
                    "face_present": True,
                    "emotion": (data or {}).get("emotionFeatures"),
                    "timestamp": (data or {}).get("capturedAt"),
                },
                room=session_id,
            )
        except Exception as e:
            logger.warning("处理 camera_analysis 失败: %s", e)
    
    @socketio.on('stop_recording')
    def handle_stop_recording(data):
        """
        处理停止录制事件
        
        事件数据格式：
        {
            sessionId: str (推荐) 或
            action: "stop",
            studentId: int,
            courseId: int,
            itemId: int
        }
        """
        try:
            access = _teacher_control_access(data)
            if not access.get('ok') or not access.get('writable'):
                emit('stop_recording_ack', _control_rejection(access))
                return
            success = StopRecordingHandler.handle(data)
            if success:
                payload = dict(data or {})
                session_id = payload.get('sessionId') or payload.get('session_id')
                if session_id:
                    payload['sessionId'] = str(session_id)
                    emit(
                        'stop_recording',
                        payload,
                        room=f'session_{session_id}_child',
                    )
                    _purge_runtime_delivery_state([str(session_id)])
                    logger.info("stop_recording事件已定向转发")
                else:
                    logger.warning(
                        'stop_recording 已完成但缺少可安全转发的 sessionId'
                    )
            else:
                logger.warning("停止录制处理失败: %s", data)
        except Exception as e:
            logger.error("处理stop_recording事件时出错: %s", e, exc_info=True)

    @socketio.on('prepare_training')
    def handle_prepare_training(data):
        """
        教师点击开始评估/开始训练：创建训练 + warmup 录制段，通知儿童端开录。

        {
            studentId: int,
            mode?: 'assessment' | 'training'
        }
        """
        payload = dict(data or {})
        request_id = payload.get('requestId') or payload.get('request_id')
        operation_id = payload.get('operationId') or payload.get('operation_id')
        teacher = _authenticated_teacher()
        if not teacher:
            emit('prepare_training_ack', {
                'success': False,
                'error': 'teacher_auth_required',
                'requestId': request_id,
                'operationId': operation_id,
            })
            return
        try:
            result = PrepareTrainingHandler.handle(payload)
            child_sid = None
            child_binding_error = None
            if result.get('success'):
                lease = get_teacher_control_registry().claim(
                    result.get('training_session_id'),
                    teacher_id=teacher['teacherId'],
                    teacher_username=teacher['username'],
                    sid=request.sid,
                    replace_existing_for_teacher=True,
                )
                if not lease.get('writable'):
                    CancelPrepareTrainingHandler.handle({
                        'studentId': payload.get('studentId'),
                        'trainingSessionId': result.get('training_session_id'),
                    })
                    result = {
                        **result,
                        'success': False,
                        'error': 'observer_read_only',
                    }
                else:
                    result['control_lease'] = lease.get('lease')
            if result.get('success'):
                superseded_sessions = result.get('superseded_session_ids') or []
                for superseded_session_id in superseded_sessions:
                    socketio.emit('stop_recording', {
                        'sessionId': superseded_session_id,
                        'reason': 'superseded_by_new_training',
                        'replacementSessionId': result.get('session_id'),
                        'requestId': request_id,
                    }, room=f'session_{superseded_session_id}_child')
                if superseded_sessions:
                    _purge_runtime_delivery_state(
                        superseded_sessions,
                        training_session_id=None,
                    )
                prepare_event = {
                    'sessionId': result.get('session_id'),
                    'trainingSessionId': result.get('training_session_id'),
                    'studentId': (
                        payload.get('studentId')
                        if payload.get('studentId') is not None
                        else payload.get('student_id')
                    ),
                    'questionId': result.get('question_id'),
                    'mode': result.get('mode'),
                    'mediaMode': Config.get_child_media_mode(),
                    'recordingMode': result.get('recording_mode') or 'continuous',
                    'preflightOnly': bool(result.get('preflight_only')),
                    'captureStarted': bool(result.get('capture_started', True)),
                    'preflightMode': result.get('preflight_mode') or 'legacy',
                    'humanDirName': result.get('human_dir_name'),
                    'requestId': request_id,
                    'operationId': operation_id,
                }
                child_sid, child_binding_error = _assign_child_for_identity(
                    socketio,
                    _child_identity(prepare_event),
                    source='prepare_training',
                )
                if child_sid:
                    socketio.emit('training_prepare', prepare_event, to=child_sid)
                else:
                    logger.warning(
                        'prepare_training 未定向儿童端，等待后续安全同步: %s',
                        child_binding_error,
                    )
                    if child_binding_error not in ('child_offline', None):
                        cleanup = CancelPrepareTrainingHandler.handle({
                            'studentId': prepare_event.get('studentId'),
                            'trainingSessionId': prepare_event.get(
                                'trainingSessionId'
                            ),
                            'operationId': (
                                f"{operation_id or request_id}:child-binding-cleanup"
                            ),
                        })
                        _purge_runtime_delivery_state(
                            cleanup.get('stoppedSessions') or [
                                prepare_event.get('sessionId')
                            ],
                            training_session_id=prepare_event.get(
                                'trainingSessionId'
                            ),
                        )
                        result = {
                            **result,
                            'success': False,
                            'error': child_binding_error,
                        }
            emit('prepare_training_ack', {
                'success': result.get('success'),
                'sessionId': result.get('session_id'),
                'trainingSessionId': result.get('training_session_id'),
                'questionId': result.get('question_id'),
                'mode': result.get('mode'),
                'recordingMode': result.get('recording_mode') or 'continuous',
                'preflightOnly': bool(result.get('preflight_only')),
                'captureStarted': bool(result.get('capture_started', True)),
                'preflightMode': result.get('preflight_mode') or 'legacy',
                'humanDirName': result.get('human_dir_name'),
                'supersededSessionIds': result.get('superseded_session_ids') or [],
                'supersededTrainingIds': result.get('superseded_training_ids') or [],
                'cleanupWarnings': result.get('cleanup_warnings') or [],
                'error': result.get('error'),
                'message': (
                    '儿童端版本过旧，请刷新儿童端后重试'
                    if child_binding_error == 'child_upgrade_required'
                    else (
                        '检测到多个儿童端，无法安全确定目标；请只保留对应儿童端在线'
                        if child_binding_error and 'ambiguous' in child_binding_error
                        else None
                    )
                ),
                'requestId': request_id,
                'operationId': operation_id,
                'childBound': bool(child_sid),
                'childBindingError': child_binding_error,
                'controlRole': (
                    (result.get('control_lease') or {}).get('controlRole')
                    if result.get('success')
                    else None
                ),
                'lease': result.get('control_lease'),
            })
            logger.info("prepare_training 完成: %s", result)
        except Exception as e:
            logger.error("处理prepare_training失败: %s", e, exc_info=True)
            emit('prepare_training_ack', {
                'success': False,
                'error': str(e),
                'requestId': request_id,
                'operationId': operation_id,
            })

    @socketio.on('cancel_prepare_training')
    def handle_cancel_prepare_training(data):
        """
        选课页返回：停止 warmup 录制。

        {
            studentId?: int,
            trainingSessionId?: str
        }
        """
        payload = dict(data or {})
        request_id = payload.get('requestId') or payload.get('request_id')
        operation_id = payload.get('operationId') or payload.get('operation_id')
        access = _teacher_control_access(payload)
        if not access.get('ok') or not access.get('writable'):
            emit('cancel_prepare_training_ack', {
                **_control_rejection(access),
                'requestId': request_id,
                'operationId': operation_id,
            })
            return
        try:
            result = CancelPrepareTrainingHandler.handle(payload)
            if result.get('success'):
                stopped_sessions = result.get('stoppedSessions') or []
                for stopped_session_id in stopped_sessions:
                    child_room = (
                        f'session_{stopped_session_id}_child'
                    )
                    emit('training_prepare_cancel', {
                        'sessionId': stopped_session_id,
                        'trainingSessionId': result.get('trainingSessionId'),
                        'stoppedSessions': (
                            result.get('stoppedSessions') or []
                        ),
                        'success': True,
                        'requestId': request_id,
                        'operationId': operation_id,
                    }, room=child_room)
                    emit('stop_recording', {
                        'sessionId': stopped_session_id,
                        'trainingSessionId': result.get('trainingSessionId'),
                        'reason': 'cancel_prepare_training',
                        'requestId': request_id,
                        'operationId': operation_id,
                    }, room=child_room)
                _purge_runtime_delivery_state(
                    stopped_sessions,
                    training_session_id=result.get('trainingSessionId'),
                )
            ack = dict(result)
            ack['requestId'] = request_id
            ack['operationId'] = operation_id
            emit('cancel_prepare_training_ack', ack)
            logger.info("cancel_prepare_training 完成: %s", result)
            if result.get('success'):
                get_teacher_control_registry().release(
                    access.get('trainingSessionId'),
                    teacher_id=access['teacher']['teacherId'],
                    sid=request.sid,
                )
        except Exception as e:
            logger.error("处理cancel_prepare_training失败: %s", e, exc_info=True)
            emit('cancel_prepare_training_ack', {
                'success': False,
                'error': str(e),
                'requestId': request_id,
                'operationId': operation_id,
            })

    @socketio.on('readiness_start')
    def handle_readiness_start(data):
        # This is a workflow boundary. Re-claiming lets the same authenticated
        # teacher recover after a Socket reconnect or backend lease reload;
        # another teacher remains read-only.
        access = _teacher_control_access(data, claim=True)
        if not access.get('ok') or not access.get('writable'):
            emit('readiness_start_ack', _control_rejection(access))
            return
        """
        教师选课确认后启动开课就绪门。

        {
            studentId: int,
            trainingSessionId: str,
            items: [{courseId, itemId, courseType, file?}],
            mediaMode?: str,
            moduleId?: str,  // 单模块重试
            timeoutMs?: number
        }
        """
        try:
            result = get_readiness_service().start(request.sid, data or {})
            emit('readiness_start_ack', {
                'success': result.get('success'),
                'error': result.get('error'),
                'snapshot': {
                    k: result.get(k)
                    for k in (
                        'trainingSessionId', 'studentId', 'ok', 'degraded',
                        'failed', 'modules', 'progress01', 'plan',
                        'status', 'sessionId', 'captureStarted',
                        'startedAtMs', 'elapsedMs', 'timeoutMs', 'deadlineAtMs',
                    )
                    if k in result
                } if result.get('success') else None,
            })
            logger.info(
                "readiness_start: success=%s training=%s",
                result.get('success'),
                (data or {}).get('trainingSessionId'),
            )
        except Exception as e:
            logger.error("处理 readiness_start 失败: %s", e, exc_info=True)
            emit('readiness_start_ack', {'success': False, 'error': str(e)})

    @socketio.on('readiness_cancel')
    def handle_readiness_cancel(data):
        access = _teacher_control_access(data, claim=True)
        if not access.get('ok') or not access.get('writable'):
            emit('readiness_cancel_ack', _control_rejection(access))
            return
        """取消本轮就绪门（不 cancel warmup）。"""
        try:
            payload = data or {}
            result = get_readiness_service().cancel(
                training_session_id=payload.get('trainingSessionId') or payload.get('training_session_id'),
                student_id=payload.get('studentId') or payload.get('student_id'),
            )
            emit('readiness_cancel_ack', result)
            logger.info("readiness_cancel: %s", result)
        except Exception as e:
            logger.error("处理 readiness_cancel 失败: %s", e, exc_info=True)
            emit('readiness_cancel_ack', {'success': False, 'error': str(e)})

    @socketio.on('readiness_force_enter')
    def handle_readiness_force_enter(data):
        payload = dict(data or {})
        request_id = payload.get('requestId') or payload.get('request_id')
        access = _teacher_control_access(payload, claim=True)
        if not access.get('ok') or not access.get('writable'):
            emit('readiness_force_enter_ack', {
                **_control_rejection(access),
                'requestId': request_id,
            })
            return
        try:
            result = get_readiness_service().force_enter(
                access.get('trainingSessionId'),
                teacher_sid=request.sid,
                reason=payload.get('reason') or 'teacher_override',
            )
            emit('readiness_force_enter_ack', {
                **result,
                'requestId': request_id,
                'trainingSessionId': access.get('trainingSessionId'),
                'lease': access.get('lease'),
            })
        except Exception as e:
            logger.error("处理 readiness_force_enter 失败: %s", e, exc_info=True)
            emit('readiness_force_enter_ack', {
                'success': False,
                'error': str(e),
                'requestId': request_id,
            })

    @socketio.on('readiness_child_report')
    def handle_readiness_child_report(data):
        """儿童端回报正式采集启动结果；服务端独立确认视频样本。"""
        try:
            result = get_readiness_service().handle_child_report(data or {})
            emit('readiness_child_report_ack', {
                'success': result.get('success'),
                'error': result.get('error'),
            })
        except Exception as e:
            logger.error("处理 readiness_child_report 失败: %s", e, exc_info=True)
            emit('readiness_child_report_ack', {'success': False, 'error': str(e)})

    @socketio.on('finalize_training')
    def handle_finalize_training(data):
        access = _teacher_control_access(data)
        if not access.get('ok') or not access.get('writable'):
            denied = _control_rejection(access)
            denied['requestId'] = (data or {}).get('requestId') or (data or {}).get('request_id')
            denied['operationId'] = (data or {}).get('operationId') or (data or {}).get('operation_id')
            emit('finalize_training_ack', denied)
            return
        """
        整次训练结束：收尾 runtime session + 聚合行为摘要

        {
            trainingSessionId?: str,
            studentId?: int
        }
        """
        payload = dict(data or {})
        request_id = payload.get('requestId') or payload.get('request_id')
        operation_id = payload.get('operationId') or payload.get('operation_id')
        try:
            from app.sockets.handlers import FinalizeTrainingHandler
            result = FinalizeTrainingHandler.handle(payload)
            # 通知儿童端停止录制
            if result.get('success'):
                stopped_sessions = result.get('stoppedRuntimeSessions') or []
                for stopped_session_id in stopped_sessions:
                    emit('stop_recording', {
                        'sessionId': stopped_session_id,
                        'trainingSessionId': result.get('trainingSessionId'),
                        'reason': 'finalize_training',
                        'requestId': request_id,
                        'operationId': operation_id,
                    }, room=f'session_{stopped_session_id}_child')
                _purge_runtime_delivery_state(
                    stopped_sessions,
                    training_session_id=result.get('trainingSessionId'),
                )
            ack = dict(result)
            ack['requestId'] = request_id
            ack['operationId'] = operation_id
            emit('finalize_training_ack', ack)
            if result.get('success'):
                get_readiness_service().cancel(
                    training_session_id=result.get('trainingSessionId')
                )
                get_teacher_control_registry().release(
                    access.get('trainingSessionId'),
                    teacher_id=access['teacher']['teacherId'],
                    sid=request.sid,
                )
            logger.info("finalize_training 完成: %s", result)
        except Exception as e:
            logger.error("处理finalize_training失败: %s", e, exc_info=True)
            emit('finalize_training_ack', {
                'success': False,
                'error': str(e),
                'requestId': request_id,
                'operationId': operation_id,
            })

    @socketio.on('teacher_rating_submit')
    def handle_teacher_rating_submit(data):
        # Rating is a workflow boundary. The same authenticated teacher may
        # have reconnected while the rating dialog was open, so reclaim the
        # existing training lease just like readiness/finalize do.
        access = _teacher_control_access(data, claim=True)
        if not access.get('ok') or not access.get('writable'):
            denied = _control_rejection(access)
            denied['requestId'] = (data or {}).get('requestId') or (data or {}).get('request_id')
            denied['questionId'] = (data or {}).get('questionId') or (data or {}).get('question_id')
            emit('teacher_rating_ack', denied)
            return
        """教师逐课点评分；成功 ACK 后前端才允许切换到下一课点。"""
        payload = data or {}
        result = _process_teacher_rating(payload)
        if not result.get('success'):
            logger.warning("保存教师评分失败: %s", result.get('error'))
        emit('teacher_rating_ack', result)
    
    # ==================== 配对游戏事件 ====================
    
    @socketio.on('matching_set_difficulty')
    def handle_matching_set_difficulty(data):
        if not _teacher_write_allowed('matching_set_difficulty', data):
            return
        """
        教师设置配对游戏难度 -> 转发给儿童端
        
        事件数据格式：
        {
            sessionId: str,
            difficulty: int (2, 3, 4, 5 对应几选一)
        }
        """
        session_id = data.get('sessionId')
        difficulty = data.get('difficulty', 3)
        logger.info("配对游戏难度设置: session=%s, difficulty=%s选1", session_id, difficulty)
        
        if session_id:
            # 转发给该会话房间的所有客户端（包括儿童端）
            emit('matching_set_difficulty', data, room=session_id)
        else:
            # 没有sessionId时广播
            logger.warning('drop matching_set_difficulty: session_id_missing')
    
    @socketio.on('matching_start')
    def handle_matching_start(data):
        if not _teacher_write_allowed('matching_start', data):
            return
        """
        教师启动配对游戏 -> 转发给儿童端
        
        事件数据格式：
        {
            sessionId: str
        }
        """
        session_id = data.get('sessionId')
        logger.info("配对游戏启动: session=%s", session_id)
        
        if not session_id:
            logger.warning('drop matching_start: session_id_missing')
            return
        emit('matching_start', data, room=session_id)
    
    @socketio.on('matching_next')
    def handle_matching_next(data):
        if not _teacher_write_allowed('matching_next', data):
            return
        """
        教师强制下一题 -> 转发给儿童端
        
        事件数据格式：
        {
            sessionId: str
        }
        """
        session_id = data.get('sessionId')
        _interrupt_interactive_prompt(session_id, data)
        _record_interaction(
            'next_question',
            _interaction_context_from_payload(data, 'next_question'),
            actor='teacher',
        )
        logger.info("配对游戏下一题: session=%s", session_id)
        
        if not session_id:
            logger.warning('drop matching_next: session_id_missing')
            return
        emit('matching_next', data, room=session_id)
    
    @socketio.on('matching_status_update')
    def handle_matching_status_update(data):
        """
        儿童端状态更新 -> 转发给教师端；同步写入部分进度 metrics（中途退出也可出分）
        """
        session_id = data.get('sessionId')
        if data.get('isCorrect') is not None or data.get('triggerPraise'):
            _interrupt_interactive_prompt(session_id, data)
        logger.debug("配对游戏状态更新: session=%s, data=%s", session_id, data)

        try:
            from app.behavior import get_behavior_service
            behavior = get_behavior_service()
            ctx = behavior.get_current_context_for_runtime(session_id) if session_id else {}
            ts_id = data.get('trainingSessionId') or ctx.get('training_session_id')
            qid = data.get('questionId') or ctx.get('question_id')
            answered = int(data.get('answered') or data.get('total') or data.get('questionIndex') or 0)
            if ts_id and answered > 0:
                avg_ms = data.get('avgResponseMs')
                behavior.record_task_metrics(ts_id, qid or '', {
                    'type': 'matching',
                    'accuracy': float(data.get('accuracy') or 0),
                    'correct': int(data.get('correct') or 0),
                    'total': answered,
                    'answered': answered,
                    'partial': True,
                    'avg_response_ms': float(avg_ms) if avg_ms is not None else None,
                    'last_response_ms': data.get('lastResponseMs'),
                })
        except Exception as e:
            logger.warning("记录配对进度指标失败: %s", e)

        _store_interactive_page_context(session_id, data, course_type='pairing')
        if data.get('isCorrect') is not None:
            selected_correct = data.get('selectedCorrect')
            _record_interaction(
                'child_response',
                _interaction_context_from_payload(data, 'child_response'),
                actor='child',
                client_timestamp=data.get('clientTimestamp'),
                metadata={
                    'courseType': 'pairing',
                    'isCorrect': bool(
                        data.get('isCorrect')
                        if selected_correct is None
                        else selected_correct
                    ),
                    'scoredCorrect': bool(data.get('isCorrect')),
                },
            )

        # 点对（含本题曾点错后最终点对）自动播表扬；点错播鼓励（每次错误尝试一次）
        if data.get('triggerPraise') or (
            'triggerPraise' not in data and data.get('isCorrect')
        ):
            _play_interactive_course_audio(session_id, 'pairing', 'praise')
        elif data.get('isCorrect') is False and not data.get('triggerPraise'):
            _play_interactive_course_audio(session_id, 'pairing', 'encourage')
        
        if not session_id:
            logger.warning('drop matching_status_update: session_id_missing')
            return
        emit('matching_status_update', data, room=session_id)
    
    @socketio.on('matching_game_end')
    def handle_matching_game_end(data):
        """
        儿童端游戏结束 -> 通知教师端
        """
        session_id = data.get('sessionId')
        logger.info("配对游戏结束: session=%s, accuracy=%.1f%%", 
                   session_id, data.get('accuracy', 0))

        try:
            from app.behavior import get_behavior_service
            behavior = get_behavior_service()
            ctx = behavior.get_current_context_for_runtime(session_id) if session_id else {}
            ts_id = data.get('trainingSessionId') or ctx.get('training_session_id')
            qid = data.get('questionId') or ctx.get('question_id')
            avg_ms = data.get('avgResponseMs')
            if ts_id:
                behavior.record_task_metrics(ts_id, qid or '', {
                    'type': 'matching',
                    'accuracy': float(data.get('accuracy') or 0),
                    'correct': int(data.get('correct') or 0),
                    'total': int(data.get('total') or data.get('answered') or 0),
                    'answered': int(data.get('answered') or data.get('total') or 0),
                    'partial': False,
                    'avg_response_ms': float(avg_ms) if avg_ms is not None else None,
                    'response_times_ms': data.get('responseTimesMs') or [],
                })
            else:
                logger.warning("配对 game_end 缺少 trainingSessionId: session=%s", session_id)
        except Exception as e:
            logger.warning("记录配对任务指标失败: %s", e)
        
        if not session_id:
            logger.warning('drop matching_game_end: session_id_missing')
            return
        emit('matching_game_end', data, room=session_id)
    
    # ==================== 排序游戏事件 ====================
    
    @socketio.on('sequencing_set_config')
    def handle_sequencing_set_config(data):
        if not _teacher_write_allowed('sequencing_set_config', data):
            return
        """
        教师设置排序游戏配置 -> 转发给儿童端
        
        事件数据格式：
        {
            sessionId: str,
            autoMode: bool,    # 是否自动模式
            category: str,     # 类别: size/length/height/count
            difficulty: int,   # 难度: 2/3/4（当前仅支持2）
            rule: str          # 规则: bigger/smaller/longer/shorter等
        }
        """
        session_id = data.get('sessionId')
        logger.info("排序游戏设置配置: session=%s, auto=%s, category=%s, rule=%s", 
                   session_id, data.get('autoMode'), data.get('category'), data.get('rule'))
        
        if not session_id:
            logger.warning('drop sequencing_set_config: session_id_missing')
            return
        emit('sequencing_set_config', data, room=session_id)
    
    @socketio.on('sequencing_start')
    def handle_sequencing_start(data):
        if not _teacher_write_allowed('sequencing_start', data):
            return
        """
        教师启动排序游戏 -> 转发给儿童端
        
        事件数据格式：
        {
            sessionId: str
        }
        """
        session_id = data.get('sessionId')
        logger.info("排序游戏启动: session=%s", session_id)
        
        if not session_id:
            logger.warning('drop sequencing_start: session_id_missing')
            return
        emit('sequencing_start', data, room=session_id)
    
    @socketio.on('sequencing_next')
    def handle_sequencing_next(data):
        if not _teacher_write_allowed('sequencing_next', data):
            return
        """
        教师触发下一题 -> 转发给儿童端
        
        事件数据格式：
        {
            sessionId: str
        }
        """
        session_id = data.get('sessionId')
        _interrupt_interactive_prompt(session_id, data)
        _record_interaction(
            'next_question',
            _interaction_context_from_payload(data, 'next_question'),
            actor='teacher',
        )
        logger.info("排序游戏下一题: session=%s", session_id)
        
        if not session_id:
            logger.warning('drop sequencing_next: session_id_missing')
            return
        emit('sequencing_next', data, room=session_id)
    
    @socketio.on('sequencing_hint')
    def handle_sequencing_hint(data):
        if not _teacher_write_allowed('sequencing_hint', data):
            return
        """
        教师触发提示 -> 转发给儿童端
        
        事件数据格式：
        {
            sessionId: str
        }
        """
        session_id = data.get('sessionId')
        _record_interaction(
            'hint',
            _interaction_context_from_payload(data, 'hint'),
            actor='teacher',
        )
        logger.info("排序游戏提示: session=%s", session_id)
        
        if not session_id:
            logger.warning('drop sequencing_hint: session_id_missing')
            return
        emit('sequencing_hint', data, room=session_id)
    
    @socketio.on('matching_hint')
    def handle_matching_hint(data):
        if not _teacher_write_allowed('matching_hint', data):
            return
        """
        教师触发配对游戏提示 -> 转发给儿童端
        
        事件数据格式：
        {
            sessionId: str
        }
        """
        session_id = data.get('sessionId')
        _record_interaction(
            'hint',
            _interaction_context_from_payload(data, 'hint'),
            actor='teacher',
        )
        logger.info("配对游戏提示: session=%s", session_id)
        
        if not session_id:
            logger.warning('drop matching_hint: session_id_missing')
            return
        emit('matching_hint', data, room=session_id)
    
    @socketio.on('behavior_modality_ready')
    def handle_behavior_modality_ready(data):
        payload = dict(data or {})
        if not _is_authorized_child_sender(request.sid, payload):
            logger.warning('拒绝非 owner 模态 ready 事件 sid=%s', request.sid)
            return
        _record_latency_modality_callback(payload, phase='ready')
        from app.robot import get_robot_service

        result = get_robot_service().mark_behavior_modality_ready(
            behavior_id=payload.get('behaviorId'),
            request_id=payload.get('requestId'),
            session_id=payload.get('sessionId'),
            modality=payload.get('modality'),
            readiness_key=(
                payload.get('speechId')
                or payload.get('readinessKey')
                or payload.get('entryId')
            ),
        )
        if result is None:
            logger.warning('拒绝不匹配的模态 ready 事件: %s', payload)

    @socketio.on('behavior_modality_started')
    def handle_behavior_modality_started(data):
        payload = dict(data or {})
        if not _is_authorized_child_sender(request.sid, payload):
            logger.warning('拒绝非 owner 模态 started 事件 sid=%s', request.sid)
            return
        _record_latency_modality_callback(payload, phase='started')
        from app.robot import get_robot_service

        result = get_robot_service().mark_behavior_modality_started(
            behavior_id=payload.get('behaviorId'),
            request_id=payload.get('requestId'),
            session_id=payload.get('sessionId'),
            modality=payload.get('modality'),
            actual_at_ms=payload.get('actualAtClientMs'),
        )
        if result is None:
            logger.warning('拒绝不匹配的模态 started 事件: %s', payload)

    def _forward_behavior_animation_ended(data):
        payload = dict(data or {})
        session_id = payload.get('sessionId') or payload.get('session_id')
        request_id = payload.get('requestId') or payload.get('request_id')
        behavior_id = (
            payload.get('behaviorId')
            or payload.get('behavior_id')
            or payload.get('interactionId')
        )
        if not _is_authorized_child_sender(request.sid, payload):
            logger.warning(
                '拒绝非 owner 动画完成事件 sid=%s session=%s',
                request.sid,
                session_id,
            )
            return
        if not request_id or not behavior_id:
            logger.warning('拒绝未关联动画完成事件: %s', payload)
            return
        with _play_request_lock:
            entry = _play_request_cache.get(str(request_id))
            cached_behavior = entry.get('behaviorId') if entry else None
        if str(cached_behavior or '') != str(behavior_id):
            logger.warning(
                '拒绝行为标识不匹配的动画完成事件 request=%s behavior=%s',
                request_id,
                behavior_id,
            )
            return
        from app.robot import get_robot_service

        terminal = get_robot_service().mark_behavior_animation_complete(
            behavior_id=str(behavior_id),
            request_id=str(request_id),
            session_id=str(session_id),
            status=str(payload.get('status') or ''),
            modality=payload.get('modality'),
        )
        if not terminal:
            logger.warning('拒绝非活动行为的动画完成事件: %s', payload)
            return
        payload['sessionId'] = str(session_id)
        payload['requestId'] = str(request_id)
        payload['behaviorId'] = str(behavior_id)
        payload['degraded'] = bool(terminal.get('degraded'))
        _record_interaction(
            'modality_failed' if terminal.get('degraded') else 'modality_ended',
            _interaction_context_for_behavior(behavior_id),
            actor='child',
            degraded=bool(terminal.get('degraded')),
            error=(str(payload.get('status')) if terminal.get('degraded') else None),
            metadata={
                'modality': 'animation',
                'status': payload.get('status'),
            },
        )
        teacher_room = f'session_{session_id}_teacher'
        if terminal.get('degraded'):
            socketio.emit(
                'behavior_animation_failed',
                payload,
                room=teacher_room,
            )
            return
        socketio.emit('behavior_animation_ended', payload, room=teacher_room)
        socketio.emit('praise_video_ended', payload, room=teacher_room)

    @socketio.on('behavior_animation_ended')
    def handle_behavior_animation_ended(data):
        """Forward child animation completion to new and legacy teachers."""
        _forward_behavior_animation_ended(data)

    @socketio.on('praise_video_ended')
    def handle_legacy_praise_video_ended(data):
        """Deprecated input alias for child pages cached before this release."""
        _forward_behavior_animation_ended(data)
    
    @socketio.on('sequencing_status_update')
    def handle_sequencing_status_update(data):
        """儿童端状态更新 -> 转发教师端，并写入部分进度 metrics。"""
        session_id = data.get('sessionId')
        if data.get('isCorrect') is not None or data.get('triggerPraise'):
            _interrupt_interactive_prompt(session_id, data)
        logger.debug("排序游戏状态更新: session=%s q=%s", session_id, data.get('questionIndex'))

        try:
            from app.behavior import get_behavior_service
            behavior = get_behavior_service()
            ctx = behavior.get_current_context_for_runtime(session_id) if session_id else {}
            ts_id = data.get('trainingSessionId') or ctx.get('training_session_id')
            qid = data.get('questionId') or ctx.get('question_id')
            stats = data.get('categoryStats') or data.get('stats') or {}
            correct = int(data.get('correct') or 0)
            wrong = int(data.get('wrong') or 0)
            if isinstance(stats, dict) and (correct + wrong) == 0:
                for v in stats.values():
                    if isinstance(v, dict):
                        correct += int(v.get('correct') or 0)
                        wrong += int(v.get('wrong') or 0)
            answered = int(data.get('answered') or data.get('total') or (correct + wrong) or 0)
            accuracy = float(data.get('accuracy') or 0)
            if answered > 0 and not data.get('accuracy'):
                accuracy = correct / answered * 100.0
            avg_ms = data.get('avgResponseMs')
            if ts_id and answered > 0:
                behavior.record_task_metrics(ts_id, qid or '', {
                    'type': 'sequencing',
                    'accuracy': accuracy,
                    'correct': correct,
                    'wrong': wrong,
                    'total': answered,
                    'answered': answered,
                    'partial': True,
                    'stats': stats,
                    'avg_response_ms': float(avg_ms) if avg_ms is not None else None,
                    'last_response_ms': data.get('lastResponseMs'),
                })
        except Exception as e:
            logger.warning("记录排序进度指标失败: %s", e)

        _store_interactive_page_context(session_id, data, course_type='ordering')
        if data.get('isCorrect') is not None:
            _record_interaction(
                'child_response',
                _interaction_context_from_payload(data, 'child_response'),
                actor='child',
                client_timestamp=data.get('clientTimestamp'),
                metadata={
                    'courseType': 'ordering',
                    'isCorrect': bool(data.get('isCorrect')),
                },
            )

        if data.get('isCorrect'):
            _play_interactive_course_audio(session_id, 'ordering', 'praise')
        elif data.get('isCorrect') is False:
            _play_interactive_course_audio(session_id, 'ordering', 'encourage')
        
        if not session_id:
            logger.warning('drop sequencing_status_update: session_id_missing')
            return
        emit('sequencing_status_update', data, room=session_id)

    @socketio.on('matching_question_ready')
    def handle_matching_question_ready(data):
        """配对新题展示后播「选和上面一样的」（教师端不再自动发裸 aux.question）。

        Hard rule: every item switch asks immediately. Child input may abort a
        still-playing prompt, but must never permanently skip the new ask.
        """
        session_id = data.get('sessionId')
        _store_interactive_page_context(session_id, data, course_type='pairing')
        logger.info('配对新题提问语音: session=%s', session_id)
        # Always schedule; input-recent must not drop item-switch asks.
        _schedule_pairing_item_question(session_id, data)
        try:
            from app.dialogue.phrases import pick_phrase

            spoken = pick_phrase('question', 'pairing')
            enrich = dict(data) if isinstance(data, dict) else {}
            page_ctx = enrich.get('pageContext') if isinstance(enrich.get('pageContext'), dict) else {}
            page_ctx = {**page_ctx, 'prompt': spoken, 'courseType': 'pairing'}
            enrich['pageContext'] = page_ctx
            enrich['prompt'] = spoken
            _store_interactive_page_context(session_id, enrich, course_type='pairing')
        except Exception as e:
            logger.debug('写入配对提问话术到页上下文失败: %s', e)
        if session_id:
            emit('matching_question_ready', data, room=session_id)

    @socketio.on('sequencing_question_ready')
    def handle_sequencing_question_ready(data):
        """排序新题展示后，按 category+rule 播对应提问语音。

        Hard rule: every item switch asks immediately and cannot be dropped by
        greetings/praise/dialogue busy-reservation races.
        """
        session_id = data.get('sessionId')
        category = data.get('category') or ''
        rule = data.get('rule') or ''
        page_ctx_in = data.get('pageContext') if isinstance(data.get('pageContext'), dict) else {}
        # 优先用 iframe 已算好的规则提问句（getSpeakPrompt），避免落到「按规则选一选」
        spoken = (
            (page_ctx_in.get('prompt') or '')
            or (data.get('prompt') or '')
        ).strip()
        _store_interactive_page_context(session_id, data, course_type='ordering')
        try:
            from app.audio.manifest_io import ordering_audio_type
            audio_type = ordering_audio_type(category, rule)
        except Exception:
            audio_type = 'question'
        try:
            from app.dialogue.phrases import ordering_phrase_key, pick_phrase

            variant = ordering_phrase_key(category, rule)
            if not spoken or '按规则' in spoken:
                spoken = pick_phrase('question', 'ordering', variant=variant)
            if not spoken or '按规则' in spoken:
                # 最后兜底：按 category/rule 拼一句，仍避免「按规则选一选」
                speak_map = {
                    ('size', 'bigger'): '选出更大的那张。',
                    ('size', 'smaller'): '选出更小的那张。',
                    ('length', 'longer'): '选出更长的那张。',
                    ('length', 'shorter'): '选出更短的那张。',
                    ('height', 'taller'): '选出更高的那张。',
                    ('height', 'shorter'): '选出更矮的那张。',
                    ('count', 'more'): '选出更多的那张。',
                    ('count', 'less'): '选出更少的那张。',
                }
                spoken = speak_map.get(
                    (str(category).lower(), str(rule).lower()),
                    '选出对的那张。',
                )
        except Exception as e:
            logger.debug('解析排序提问话术失败: %s', e)
            if not spoken:
                spoken = '选出对的那张。'
        logger.info(
            '排序新题提问语音: session=%s cat=%s rule=%s audio=%s spoken=%s',
            session_id, category, rule, audio_type, spoken,
        )
        _schedule_ordering_item_question(
            session_id,
            audio_type=audio_type,
            category=category,
            rule=rule,
            text=spoken,
            event_data=data,
        )
        # 写入孩子实际听到的规则提问句，供 LLM pageContext 使用
        try:
            enrich = dict(data) if isinstance(data, dict) else {}
            enrich['prompt'] = spoken
            page_ctx = enrich.get('pageContext') if isinstance(enrich.get('pageContext'), dict) else {}
            page_ctx = {
                **page_ctx,
                'prompt': spoken,
                'courseType': 'ordering',
                'category': category,
                'rule': rule,
                'target': None,
            }
            enrich['pageContext'] = page_ctx
            _store_interactive_page_context(session_id, enrich, course_type='ordering')
        except Exception as e:
            logger.debug('写入排序提问话术到页上下文失败: %s', e)
        if session_id:
            emit('sequencing_question_ready', data, room=session_id)

    @socketio.on('interactive_page_context')
    def handle_interactive_page_context(data):
        """互动 iframe 上报当前题面，供对话 LLM 使用。"""
        data = data or {}
        session_id = data.get('sessionId') or data.get('session_id')
        course_type = (
            data.get('courseType')
            or data.get('course_type')
            or ((data.get('pageContext') or {}).get('courseType') if isinstance(data.get('pageContext'), dict) else None)
            or 'pairing'
        )
        _store_interactive_page_context(session_id, data, course_type=str(course_type))
        if session_id:
            emit('interactive_page_context', data, room=session_id)

    @socketio.on('robot_speak_ended')
    def handle_robot_speak_ended(data):
        """儿童端 browser TTS 结束 → 转发给同会话（含互动 iframe）。"""
        data = dict(data or {})
        session_id = data.get('sessionId') or data.get('session_id')
        behavior_id = (
            data.get('behaviorId')
            or data.get('behavior_id')
            or data.get('interactionId')
            or data.get('sequenceId')
        )
        try:
            from app.robot import get_robot_service

            resolved_behavior_id = None
            if behavior_id:
                resolved_behavior_id = (
                    get_robot_service().mark_behavior_audio_complete(
                        behavior_id=behavior_id,
                        request_id=data.get('requestId') or data.get('request_id'),
                        session_id=session_id,
                        modality=data.get('modality'),
                        status=data.get('status'),
                        completion_key=(
                            f"browser:{data.get('intent') or ''}:"
                            f"{data.get('text') or ''}"
                        ),
                    )
                )
            if resolved_behavior_id:
                data['behaviorId'] = resolved_behavior_id
                data['behavior_id'] = resolved_behavior_id
                data['interactionId'] = resolved_behavior_id
        except Exception as coordination_error:
            logger.warning(
                'browser TTS 完成释放行为失败 session=%s: %s',
                session_id,
                coordination_error,
            )
        # After other speech frees the mutex, land any latest item-switch ask.
        try:
            if session_id:
                _flush_pending_item_question(session_id)
        except Exception as flush_error:
            logger.debug(
                '补发题切换提问失败 session=%s: %s',
                session_id,
                flush_error,
            )
        intent = str(data.get('intent') or '').strip().lower()
        # browser TTS ↔ 连续 ASR 门控（对齐预录 audio_status）
        if session_id and intent:
            gate_entry = {
                'question': 'question',
                'praise': 'praise',
                'hint': 'hint',
                'encourage': 'praise',
            }.get(intent)
            if gate_entry:
                try:
                    from app.services import get_analysis_service

                    get_analysis_service().update_system_audio_state(
                        str(session_id),
                        gate_entry,
                        data.get('status') or 'ended',
                    )
                except Exception as gate_error:
                    logger.debug(
                        'browser TTS ASR 门控结束失败 session=%s: %s',
                        session_id,
                        gate_error,
                    )
        # 命名/拟声：提问/提示播完后恢复关键词监听（不经对话唤醒）
        if session_id and intent in ('question', 'hint'):
            try:
                from app.services.keyword_listen import get_keyword_listen_service

                item_id = data.get('itemId') or data.get('item_id')
                if item_id is None:
                    try:
                        from app.dialogue.page_context_store import (
                            get_interactive_page_context,
                        )

                        page_ctx = get_interactive_page_context(str(session_id)) or {}
                        item_id = page_ctx.get('itemId') or page_ctx.get('item_id')
                    except Exception:
                        item_id = None
                get_keyword_listen_service().arm_after_question(
                    str(session_id),
                    intent=intent,
                    item_id=item_id,
                )
            except Exception as kw_err:
                logger.warning(
                    'keyword_listen arm failed session=%s: %s',
                    session_id,
                    kw_err,
                )
        logger.debug(
            'robot_speak_ended session=%s behavior=%s intent=%s',
            session_id, data.get('behaviorId'), data.get('intent'),
        )
        if session_id:
            emit('robot_speak_ended', data, room=session_id)
            child_room = f'session_{session_id}_child'
            emit('robot_speak_ended', data, room=child_room)
        else:
            logger.warning('drop robot_speak_ended: session_id_missing')
    
    @socketio.on('sequencing_game_end')
    def handle_sequencing_game_end(data):
        """儿童端游戏结束 -> 通知教师端并写入最终 metrics。"""
        session_id = data.get('sessionId')
        logger.info("排序游戏结束: session=%s, total=%d", 
                   session_id, data.get('totalQuestions', 0))

        try:
            from app.behavior import get_behavior_service
            behavior = get_behavior_service()
            ctx = behavior.get_current_context_for_runtime(session_id) if session_id else {}
            ts_id = data.get('trainingSessionId') or ctx.get('training_session_id')
            qid = data.get('questionId') or ctx.get('question_id')
            stats = data.get('totalStats') or data.get('stats') or {}
            correct = int(data.get('correct') or 0)
            wrong = int(data.get('wrong') or 0)
            if isinstance(stats, dict) and (correct + wrong) == 0:
                for v in stats.values():
                    if isinstance(v, dict):
                        correct += int(v.get('correct') or 0)
                        wrong += int(v.get('wrong') or 0)
            total = correct + wrong
            accuracy = float(data.get('accuracy') or 0)
            if total > 0 and not data.get('accuracy'):
                accuracy = correct / total * 100.0
            avg_ms = data.get('avgResponseMs')
            if ts_id:
                behavior.record_task_metrics(ts_id, qid or '', {
                    'type': 'sequencing',
                    'accuracy': accuracy,
                    'correct': correct,
                    'wrong': wrong,
                    'total': total or int(data.get('totalQuestions') or 0),
                    'answered': total or int(data.get('answered') or 0),
                    'partial': False,
                    'stats': stats,
                    'avg_response_ms': float(avg_ms) if avg_ms is not None else None,
                    'response_times_ms': data.get('responseTimesMs') or [],
                })
            else:
                logger.warning("排序 game_end 缺少 trainingSessionId: session=%s", session_id)
        except Exception as e:
            logger.warning("记录排序任务指标失败: %s", e)
        
        if not session_id:
            logger.warning('drop sequencing_game_end: session_id_missing')
            return
        emit('sequencing_game_end', data, room=session_id)
    
    # ==================== 分析结果事件（由后端发送） ====================
    # 以下事件由FeedbackService发送，不需要在这里注册处理器
    # 
    # match_result: 匹配结果
    # {
    #     session_id: str,
    #     matcher_type: str,
    #     score: float,
    #     passed: bool,
    #     threshold: float,
    #     timestamp: float,
    #     details: dict
    # }
    #
    # attention_update: 注意力更新
    # {
    #     session_id: str,
    #     score: float,
    #     state: str (high/medium/low),
    #     trend: str (increasing/stable/decreasing),
    #     timestamp: float
    # }
    #
    # session_summary: 会话总结
    # {
    #     session_id: str,
    #     summary: dict,
    #     timestamp: float
    # }
    #
    # trigger_action: 触发动作
    # {
    #     session_id: str,
    #     action_type: str,
    #     target: str (child/teacher),
    #     data: dict,
    #     timestamp: float
    # }
    #
    # analysis_result: 分析结果
    # {
    #     session_id: str,
    #     analyzer_type: str,
    #     data: dict,
    #     confidence: float,
    #     timestamp: float
    # }
    
    logger.info("WebSocket事件处理器已注册（包含分析反馈事件支持）")
