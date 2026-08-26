"""Mimic-course pose match to the existing teacher praise/rating workflow."""
from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from app.core.models import MatchResult
from app.utils.logger import setup_logger

logger = setup_logger('pose_auto_praise')

POSE_COURSE_TYPES = frozenset({'mimic', 'imitation', 'pose'})
_RETRY_INTERVAL_SECONDS = 1.0


def _canonical_pose_course_type(value: Any) -> str:
    course_type = str(value or '').strip().lower()
    return 'mimic' if course_type in POSE_COURSE_TYPES else course_type


@dataclass
class _PosePraiseState:
    question_key: Tuple[str, str, str]
    in_flight: bool = False
    completed: bool = False
    response_recorded: bool = False
    last_attempt_at: float = 0.0


class PoseAutoPraiseService:
    """Deduplicate a stable pose hit and launch the full praise package."""

    def __init__(self) -> None:
        self._states: Dict[str, _PosePraiseState] = {}
        self._lock = threading.RLock()

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._states.pop(str(session_id), None)

    @staticmethod
    def _runtime_context(session_id: str) -> Optional[Dict[str, Any]]:
        try:
            from app.session import get_session_manager

            session = get_session_manager().get_session(session_id)
            if session is None or not session.is_active():
                return None
            metadata = dict(getattr(session, 'metadata', None) or {})
            raw_course_type = metadata.get('course_type')
            course_type = _canonical_pose_course_type(raw_course_type)
            if course_type != 'mimic':
                return None
            training_id = getattr(session, 'training_session_id', None)
            question_id = getattr(session, 'question_id', None)
            item_id = getattr(session, 'course_item_id', None)
            if not training_id or not question_id:
                return None
            return {
                'session': session,
                'course_type': str(raw_course_type or course_type).lower(),
                'training_session_id': str(training_id),
                'question_id': str(question_id),
                'item_id': item_id,
                'course_id': getattr(session, 'course_id', None),
                'student_id': getattr(session, 'student_id', None),
            }
        except Exception as exc:  # noqa: BLE001
            logger.debug('resolve mimic runtime context failed: %s', exc)
            return None

    def try_auto_praise(self, session_id: str, result: MatchResult) -> bool:
        """Return True only when this call notified the current teacher flow."""
        sid = str(session_id or '').strip()
        if (
            not sid
            or result is None
            or not bool(getattr(result, 'passed', False))
            or str(getattr(result, 'matcher_type', '')) != 'pose_matcher'
            or str(getattr(result, 'session_id', sid)) != sid
        ):
            return False

        context = self._runtime_context(sid)
        if not context:
            return False
        question_key = (
            context['training_session_id'],
            context['question_id'],
            str(context.get('item_id') or ''),
        )
        now = time.monotonic()
        with self._lock:
            state = self._states.get(sid)
            if state is None or state.question_key != question_key:
                state = _PosePraiseState(question_key=question_key)
                self._states[sid] = state
            if state.completed or state.in_flight:
                return False
            if now - state.last_attempt_at < _RETRY_INTERVAL_SECONDS:
                return False
            state.in_flight = True
            state.last_attempt_at = now
            should_record_response = not state.response_recorded
            if should_record_response:
                state.response_recorded = True

        request_id = f'pose-praise-{uuid.uuid4().hex[:12]}'
        if should_record_response:
            self._record_child_response(
                sid,
                context,
                request_id=request_id,
                result=result,
            )

        payload: Dict[str, Any] = {
            'sessionId': sid,
            'session_id': sid,
            'requestId': request_id,
            'courseType': context['course_type'],
            'courseId': context.get('course_id'),
            'itemId': context.get('item_id'),
            'studentId': context.get('student_id'),
            'trainingSessionId': context['training_session_id'],
            'questionId': context['question_id'],
            'source': 'pose_match',
            'action': 'praise',
            'serverPlayed': False,
            'score': round(float(result.score), 4),
            'threshold': float(result.threshold),
        }
        teacher_notified = {'ok': False}

        def notify_before_child_play(info: Dict[str, Any]) -> None:
            payload.update({
                'serverPlayed': True,
                'behaviorId': info.get('behaviorId'),
                'behaviorAnimation': info.get('behaviorAnimation'),
                'hasAnimation': bool(info.get('hasAnimation')),
            })
            teacher_notified['ok'] = self._emit_teacher(sid, payload)

        try:
            from app.sockets.events import trigger_keyword_parity_praise

            played = trigger_keyword_parity_praise(
                sid,
                request_id=request_id,
                course_type=context['course_type'],
                item_id=context.get('item_id'),
                on_before_child_play=notify_before_child_play,
                source='pose_match',
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning('pose praise package failed session=%s: %s', sid, exc)
            played = {'ok': False, 'reason': str(exc)}

        if played.get('ok') and played.get('serverPlayed'):
            if teacher_notified['ok']:
                notified = True
            else:
                payload.update({
                    'serverPlayed': True,
                    'behaviorId': played.get('behaviorId'),
                    'behaviorAnimation': played.get('behaviorAnimation'),
                    'hasAnimation': bool(played.get('hasAnimation')),
                })
                notified = self._emit_teacher(sid, payload)
        else:
            # Preserve the existing teacher-side fallback: when the robot is
            # busy, the same event invokes playCurrentItem({praise:true}).
            payload['serverPlayed'] = False
            notified = self._emit_teacher(sid, payload)

        with self._lock:
            current = self._states.get(sid)
            if current and current.question_key == question_key:
                current.in_flight = False
                current.completed = bool(notified)

        if notified:
            self._record_monitor_event(context, result, payload)
            logger.info(
                'pose auto praise session=%s question=%s score=%.3f serverPlayed=%s',
                sid,
                context['question_id'],
                float(result.score),
                bool(payload.get('serverPlayed')),
            )
        else:
            logger.warning(
                'pose auto praise teacher notify failed session=%s question=%s',
                sid,
                context['question_id'],
            )
        return bool(notified)

    @staticmethod
    def _emit_teacher(session_id: str, payload: Dict[str, Any]) -> bool:
        from app.services.keyword_listen import KeywordListenService

        return KeywordListenService._emit_teacher_auto_praise(session_id, payload)

    @staticmethod
    def _record_child_response(
        session_id: str,
        context: Dict[str, Any],
        *,
        request_id: str,
        result: MatchResult,
    ) -> None:
        try:
            from app.behavior import get_behavior_service

            details = dict(result.details or {})
            get_behavior_service().record_interaction(
                'child_response',
                context['training_session_id'],
                question_id=context['question_id'],
                runtime_session_id=session_id,
                request_id=request_id,
                actor='child',
                metadata={
                    'courseType': 'mimic',
                    'modality': 'pose',
                    'isCorrect': True,
                    'score': float(result.score),
                    'threshold': float(result.threshold),
                    'algorithmVersion': details.get('algorithm_version'),
                    'stableFrames': details.get('stable_frames'),
                    'holdMs': details.get('hold_ms'),
                    'coverage': details.get('coverage'),
                    'mirrored': details.get('mirrored'),
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning('record pose child response failed: %s', exc)

    @staticmethod
    def _record_monitor_event(
        context: Dict[str, Any],
        result: MatchResult,
        payload: Dict[str, Any],
    ) -> None:
        try:
            from app.monitor.events import append_monitor_event

            append_monitor_event(
                'auto_praise',
                (
                    f'模仿动作识别正确 score={float(result.score):.3f} '
                    f'serverPlayed={bool(payload.get("serverPlayed"))}'
                ),
                training_session_id=context['training_session_id'],
                question_id=context['question_id'],
                level='info',
            )
        except Exception:  # noqa: BLE001
            pass


_service: Optional[PoseAutoPraiseService] = None
_service_lock = threading.Lock()


def get_pose_auto_praise_service() -> PoseAutoPraiseService:
    global _service
    with _service_lock:
        if _service is None:
            _service = PoseAutoPraiseService()
        return _service


__all__ = ['PoseAutoPraiseService', 'get_pose_auto_praise_service']
