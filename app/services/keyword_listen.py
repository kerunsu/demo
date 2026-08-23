"""
命名 / 拟声 / speech：提问 TTS 结束后的关键词监听。

命中正确答案 → 走与教师「表扬」相同的 multimodal 通路；不打开对话。
独立于麦麦唤醒 / child_dialogue_text。
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import yaml

from app.utils.logger import setup_logger

logger = setup_logger('keyword_listen')

# 与 handlers._SPEECH_COURSE_TYPES 对齐（不含 mimic：偏动作）
KEYWORD_LISTEN_COURSE_TYPES = frozenset({'naming', 'speech', 'onomatopoeia'})

_DEFAULT_TIMEOUT_SEC = 75.0
_MIN_KEYWORD_LEN = 1
# 连续 ASR 块可能重复同一句；与 child_dialogue.js 短窗去重对齐
_CHILD_SPEECH_DEDUPE_SEC = 2.5
_PUNCT_RE = re.compile(
    r'[\s\u3000，。！？、；：,.!?;:\'\"“”‘’（）()\[\]【】<>《》…—～~·]+'
)
_TRAILING_PARTICLES = ('呀', '啊', '呢', '哦', '喔', '哟', '啦', '吧', '嘛')

_ALIASES_PATH = Path(__file__).resolve().parents[2] / 'config' / 'onomatopoeia_aliases.yaml'
_alias_cache: Optional[Dict[str, List[str]]] = None
_alias_mtime: Optional[float] = None
_alias_lock = threading.RLock()


def normalize_speech_text(text: Optional[str]) -> str:
    """去空白/标点，并剥常见语气词尾缀。"""
    raw = str(text or '').strip()
    if not raw:
        return ''
    cleaned = _PUNCT_RE.sub('', raw)
    changed = True
    while changed and cleaned:
        changed = False
        for particle in _TRAILING_PARTICLES:
            if cleaned.endswith(particle) and len(cleaned) > len(particle):
                cleaned = cleaned[: -len(particle)]
                changed = True
                break
    return cleaned


def _load_onomatopoeia_aliases(force: bool = False) -> Dict[str, List[str]]:
    global _alias_cache, _alias_mtime
    with _alias_lock:
        mtime: Optional[float] = None
        if _ALIASES_PATH.exists():
            try:
                mtime = _ALIASES_PATH.stat().st_mtime
            except OSError:
                mtime = None
        if (
            not force
            and _alias_cache is not None
            and mtime is not None
            and mtime == _alias_mtime
        ):
            return _alias_cache
        mapping: Dict[str, List[str]] = {}
        if _ALIASES_PATH.exists():
            try:
                with open(_ALIASES_PATH, 'r', encoding='utf-8') as fh:
                    data = yaml.safe_load(fh) or {}
                raw = data.get('aliases') if isinstance(data, dict) else {}
                if isinstance(raw, dict):
                    for key, vals in raw.items():
                        nk = normalize_speech_text(str(key))
                        if not nk:
                            continue
                        items: List[str] = []
                        if isinstance(vals, str):
                            vals = re.split(r'[|,/、，]+', vals)
                        if isinstance(vals, (list, tuple)):
                            for v in vals:
                                nv = normalize_speech_text(str(v))
                                if nv and nv not in items:
                                    items.append(nv)
                        if items:
                            mapping[nk] = items
            except Exception as exc:  # noqa: BLE001
                logger.warning('加载拟声别名失败: %s', exc)
        _alias_cache = mapping
        _alias_mtime = mtime
        return mapping


def _split_multi_target(text: Optional[str]) -> List[str]:
    """speech_target 可写「喵|喵喵」或多分隔符。"""
    raw = str(text or '').strip()
    if not raw:
        return []
    parts = re.split(r'[|,/、，;；]+', raw)
    out: List[str] = []
    for part in parts:
        n = normalize_speech_text(part)
        if n and n not in out:
            out.append(n)
    return out


def _alias_hits_for_label(label: str, aliases: Dict[str, List[str]]) -> List[str]:
    """按完整标签或去「叫」后缀后的动物名取别名。"""
    hits: List[str] = []
    candidates = [label]
    for suffix in ('的叫声', '叫声', '叫'):
        if label.endswith(suffix) and len(label) > len(suffix):
            candidates.append(label[: -len(suffix)].strip())
            break
    # 「小猫叫」→ 候选含「小猫」；也试去掉「小」
    expanded = list(candidates)
    for c in candidates:
        if c.startswith('小') and len(c) > 1:
            expanded.append(c[1:])
    for c in expanded:
        nc = normalize_speech_text(c)
        if not nc:
            continue
        for alias in aliases.get(nc) or []:
            if alias not in hits:
                hits.append(alias)
    return hits


def resolve_answer_keywords(
    *,
    course_type: str,
    speech_target: Optional[str] = None,
    name: Optional[str] = None,
) -> List[str]:
    """
    解析本题答案关键词。
    优先 speech_target，否则 name；拟声追加别名表。
    """
    ct = str(course_type or '').strip().lower()
    keywords: List[str] = []
    for source in (speech_target, name):
        for part in _split_multi_target(source):
            if part not in keywords:
                keywords.append(part)
        if keywords:
            break
    if not keywords and name:
        n = normalize_speech_text(name)
        if n:
            keywords.append(n)

    if ct == 'onomatopoeia':
        aliases = _load_onomatopoeia_aliases()
        seed_labels = list(keywords)
        for label in (speech_target, name):
            for part in _split_multi_target(label) or (
                [normalize_speech_text(label)] if label else []
            ):
                if part and part not in seed_labels:
                    seed_labels.append(part)
        for label in seed_labels:
            for alias in _alias_hits_for_label(label, aliases):
                if alias not in keywords:
                    keywords.append(alias)

    return [k for k in keywords if len(k) >= _MIN_KEYWORD_LEN]


def find_keyword_hit(recognized: Optional[str], keywords: Sequence[str]) -> Optional[str]:
    """规范化后包含匹配；更长短语优先，降低短词误伤。"""
    text = normalize_speech_text(recognized)
    if not text:
        return None
    ordered = sorted(
        (normalize_speech_text(k) for k in keywords),
        key=lambda k: (-len(k), k),
    )
    for kw in ordered:
        if kw and kw in text:
            return kw
    return None


@dataclass
class KeywordListenState:
    session_id: str
    course_type: str = ''
    item_id: Any = None
    keywords: List[str] = field(default_factory=list)
    armed: bool = False
    praised: bool = False
    armed_at: float = 0.0
    timeout_sec: float = _DEFAULT_TIMEOUT_SEC
    primary_target: str = ''


class KeywordListenService:
    """Session-level keyword listen arm/disarm + hit → auto praise."""

    def __init__(self) -> None:
        self._states: Dict[str, KeywordListenState] = {}
        self._lock = threading.RLock()
        # session_id -> (normalized_text, emitted_at)
        self._last_child_speech: Dict[str, Tuple[str, float]] = {}

    def supports_course(self, course_type: Optional[str]) -> bool:
        return str(course_type or '').strip().lower() in KEYWORD_LISTEN_COURSE_TYPES

    def prepare(
        self,
        session_id: str,
        *,
        course_type: str,
        item_id: Any = None,
        speech_target: Optional[str] = None,
        name: Optional[str] = None,
        timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
    ) -> KeywordListenState:
        """切题时准备关键词；默认未武装。"""
        sid = str(session_id)
        ct = str(course_type or '').strip().lower()
        with self._lock:
            if not self.supports_course(ct):
                self._states.pop(sid, None)
                state = KeywordListenState(session_id=sid, course_type=ct)
                return state
            keywords = resolve_answer_keywords(
                course_type=ct,
                speech_target=speech_target,
                name=name,
            )
            state = KeywordListenState(
                session_id=sid,
                course_type=ct,
                item_id=item_id,
                keywords=keywords,
                armed=False,
                praised=False,
                armed_at=0.0,
                timeout_sec=float(timeout_sec or _DEFAULT_TIMEOUT_SEC),
                primary_target=keywords[0] if keywords else '',
            )
            self._states[sid] = state
            logger.info(
                'keyword_listen prepared session=%s course=%s item=%s keywords=%s',
                sid,
                ct,
                item_id,
                keywords,
            )
            return state

    def arm_after_question(
        self,
        session_id: str,
        *,
        intent: Optional[str] = None,
        item_id: Any = None,
    ) -> bool:
        """提问或提示 TTS 结束后武装；已表扬的课点不再武装。"""
        sid = str(session_id)
        intent_l = str(intent or '').strip().lower()
        if intent_l and intent_l not in ('question', 'hint'):
            return False
        with self._lock:
            state = self._states.get(sid)
            if not state or not self.supports_course(state.course_type):
                return False
            if not state.keywords:
                logger.info(
                    'keyword_listen skip arm (no keywords) session=%s course=%s item=%s',
                    sid,
                    state.course_type,
                    state.item_id,
                )
                return False
            if state.praised:
                logger.info(
                    'keyword_listen skip arm (already praised) session=%s item=%s',
                    sid,
                    state.item_id,
                )
                return False
            if item_id is not None and state.item_id is not None:
                if str(item_id) != str(state.item_id):
                    logger.info(
                        'keyword_listen skip arm (item mismatch) session=%s want=%s have=%s',
                        sid,
                        item_id,
                        state.item_id,
                    )
                    return False
            state.armed = True
            state.armed_at = time.time()
            logger.info(
                'keyword_listen armed session=%s course=%s item=%s keywords=%s',
                sid,
                state.course_type,
                state.item_id,
                state.keywords,
            )
            return True

    def should_consume_dialogue_turn(self, session_id: str) -> bool:
        """当前识别属于课程作答窗口时，不允许回落到普通闲聊。

        ``praised`` 也视为课程窗口，避免连续 ASR 的重复尾音又触发一次
        长对话并占用机器人行为锁。
        """
        sid = str(session_id)
        with self._lock:
            state = self._states.get(sid)
            if not state or not self.supports_course(state.course_type):
                return False
            if self._expire_if_needed(state):
                return False
            return bool(state.keywords and (state.armed or state.praised))

    def disarm(self, session_id: str, *, reason: str = '') -> None:
        sid = str(session_id)
        with self._lock:
            state = self._states.get(sid)
            if not state:
                return
            if state.armed or reason:
                logger.info(
                    'keyword_listen disarm session=%s reason=%s was_armed=%s',
                    sid,
                    reason or 'unspecified',
                    state.armed,
                )
            state.armed = False

    def note_teacher_praise(self, session_id: str) -> None:
        """教师点表扬：本课点不再自动表扬。"""
        sid = str(session_id)
        with self._lock:
            state = self._states.get(sid)
            if not state:
                return
            state.praised = True
            state.armed = False
            logger.info(
                'keyword_listen teacher_praise session=%s item=%s',
                sid,
                state.item_id,
            )

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._states.pop(str(session_id), None)

    def get_state(self, session_id: str) -> Optional[KeywordListenState]:
        with self._lock:
            state = self._states.get(str(session_id))
            if not state:
                return None
            # 返回浅拷贝，避免外部改写
            return KeywordListenState(
                session_id=state.session_id,
                course_type=state.course_type,
                item_id=state.item_id,
                keywords=list(state.keywords),
                armed=state.armed,
                praised=state.praised,
                armed_at=state.armed_at,
                timeout_sec=state.timeout_sec,
                primary_target=state.primary_target,
            )

    def _expire_if_needed(self, state: KeywordListenState) -> bool:
        if not state.armed:
            return False
        if state.timeout_sec <= 0:
            return False
        if state.armed_at and (time.time() - state.armed_at) >= state.timeout_sec:
            state.armed = False
            logger.info(
                'keyword_listen timeout session=%s item=%s after=%.1fs',
                state.session_id,
                state.item_id,
                state.timeout_sec,
            )
            return True
        return False

    def evaluate_transcript(
        self,
        session_id: str,
        transcript: Optional[str],
    ) -> Tuple[str, Optional[str]]:
        """
        评估识别文本。

        Returns:
            (status, matched_keyword)
            status: idle | not_armed | suppressed_echo | praised | timeout | miss | hit
        """
        sid = str(session_id)
        text = normalize_speech_text(transcript)
        with self._lock:
            state = self._states.get(sid)
            if not state or not self.supports_course(state.course_type):
                return 'idle', None
            if self._expire_if_needed(state):
                return 'timeout', None
            hit = find_keyword_hit(text, state.keywords) if text else None
            if not hit:
                return 'miss' if text else 'miss', None
            if state.praised:
                logger.info(
                    'keyword_listen suppressed_echo session=%s reason=already_praised kw=%s text=%s',
                    sid,
                    hit,
                    text,
                )
                return 'praised', hit
            if not state.armed:
                logger.info(
                    'keyword_listen suppressed_echo session=%s reason=not_armed kw=%s text=%s',
                    sid,
                    hit,
                    text,
                )
                return 'suppressed_echo', hit
            return 'hit', hit

    def consume_hit(self, session_id: str, matched_keyword: str) -> Optional[KeywordListenState]:
        """命中后标记 praised 并解除武装；返回快照供播放。"""
        sid = str(session_id)
        with self._lock:
            state = self._states.get(sid)
            if not state or not state.armed or state.praised:
                return None
            state.praised = True
            state.armed = False
            snap = KeywordListenState(
                session_id=state.session_id,
                course_type=state.course_type,
                item_id=state.item_id,
                keywords=list(state.keywords),
                armed=False,
                praised=True,
                armed_at=state.armed_at,
                timeout_sec=state.timeout_sec,
                primary_target=state.primary_target,
            )
            logger.info(
                'keyword_listen keyword_hit session=%s course=%s item=%s kw=%s',
                sid,
                snap.course_type,
                snap.item_id,
                matched_keyword,
            )
            return snap

    def try_auto_praise_from_transcript(
        self,
        session_id: str,
        transcript: Optional[str],
    ) -> bool:
        """
        若武装且命中关键词 → 教师同路表扬。
        返回是否已发起表扬。

        evaluate + consume 在同一把锁内完成，避免连续 ASR 与对话 STT
        并发双命中各发一次 keyword_auto_praise。
        """
        sid = str(session_id)
        text = normalize_speech_text(transcript)
        matched: Optional[str] = None
        snap: Optional[KeywordListenState] = None
        status = 'idle'
        with self._lock:
            state = self._states.get(sid)
            if not state or not self.supports_course(state.course_type):
                status = 'idle'
            elif self._expire_if_needed(state):
                status = 'timeout'
            else:
                hit = find_keyword_hit(text, state.keywords) if text else None
                if not hit:
                    status = 'miss'
                elif state.praised:
                    status = 'praised'
                    matched = hit
                elif not state.armed:
                    status = 'suppressed_echo'
                    matched = hit
                else:
                    status = 'hit'
                    matched = hit
                    state.praised = True
                    state.armed = False
                    snap = KeywordListenState(
                        session_id=state.session_id,
                        course_type=state.course_type,
                        item_id=state.item_id,
                        keywords=list(state.keywords),
                        armed=False,
                        praised=True,
                        armed_at=state.armed_at,
                        timeout_sec=state.timeout_sec,
                        primary_target=state.primary_target,
                    )
                    logger.info(
                        'keyword_listen keyword_hit session=%s course=%s item=%s kw=%s',
                        sid,
                        snap.course_type,
                        snap.item_id,
                        matched,
                    )

        # Surface every meaningful transcript in the child dialogue UI
        # (wrong answers / partials / wake / misses), not only keyword hits.
        # Dialogue STT also appends via child_dialogue_result; client+server
        # short-window dedupe prevents double bubbles.
        raw_display = (transcript or '').strip()
        if raw_display:
            self._emit_child_speech_recognized(
                sid,
                raw_display,
                keyword_hit=(status == 'hit'),
                keyword=matched,
                status=status or 'recognized',
            )

        if status != 'hit' or not matched or not snap:
            if text and status in (
                'miss',
                'suppressed_echo',
                'not_armed',
                'praised',
                'timeout',
            ):
                logger.info(
                    'keyword_listen eval session=%s status=%s text=%s matched=%s',
                    session_id,
                    status,
                    text,
                    matched,
                )
            return False
        try:
            from app.monitor.events import append_monitor_event
            from app.behavior import get_behavior_service

            ctx = get_behavior_service().get_current_context_for_runtime(session_id) or {}
            append_monitor_event(
                'keyword_hit',
                f'关键词命中 {matched} → 自动表扬',
                training_session_id=ctx.get('training_session_id'),
                question_id=ctx.get('question_id'),
                level='info',
            )
        except Exception:  # noqa: BLE001
            pass

        # 教师同路：只通知教师端执行 playCurrentItem({praise:true}) /
        # play_resource。勿在此直接 _play_interactive_course_audio，否则会
        # 缺 play_resource_ack / 动画结束关联，教师无法打分切题，且可能双播。
        request_id = f'keyword-praise-{uuid.uuid4().hex[:12]}'
        payload = {
            'sessionId': str(session_id),
            'session_id': str(session_id),
            'requestId': request_id,
            'courseType': snap.course_type,
            'itemId': snap.item_id,
            'keyword': matched,
            'source': 'keyword_listen',
            'action': 'praise',
        }
        ok = self._emit_teacher_auto_praise(str(session_id), payload)

        if ok:
            logger.info(
                'keyword_listen auto_praise session=%s course=%s item=%s kw=%s',
                session_id,
                snap.course_type,
                snap.item_id,
                matched,
            )
            try:
                from app.monitor.events import append_monitor_event
                from app.behavior import get_behavior_service

                ctx = get_behavior_service().get_current_context_for_runtime(session_id) or {}
                append_monitor_event(
                    'auto_praise',
                    f'关键词自动表扬 kw={matched}',
                    training_session_id=ctx.get('training_session_id'),
                    question_id=ctx.get('question_id'),
                    level='info',
                )
            except Exception:  # noqa: BLE001
                pass
        else:
            # 通知失败：允许本课点再次武装（教师可再点提问或再次命中）
            with self._lock:
                state = self._states.get(str(session_id))
                if state and state.item_id == snap.item_id:
                    state.praised = False
            logger.warning(
                'keyword_listen auto_praise suppressed session=%s (teacher notify failed)',
                session_id,
            )
        return ok

    @staticmethod
    def _resolve_socketio():
        """Locate the live SocketIO instance used by the running server."""
        # 1) Robot module global (wired in app.py via set_socketio)
        try:
            import app.robot.robot_service as robot_mod

            sio = getattr(robot_mod, '_socketio', None)
            if sio is not None:
                return sio
        except Exception:  # noqa: BLE001
            pass
        # 2) Feedback service (also wired in app.py)
        try:
            from app.services import get_feedback_service

            sio = getattr(get_feedback_service(), '_socketio', None)
            if sio is not None:
                return sio
        except Exception:  # noqa: BLE001
            pass
        # 3) Flask app extensions / package globals
        try:
            from flask import current_app, has_app_context

            if has_app_context():
                sio = current_app.extensions.get('socketio')
                if sio is not None:
                    return sio
        except Exception:  # noqa: BLE001
            pass
        try:
            from app import get_socketio

            return get_socketio()
        except Exception:  # noqa: BLE001
            return None

    def _should_emit_child_speech(self, session_id: str, transcript: str) -> bool:
        """Drop near-identical repeats within a short window (ASR chunk spam)."""
        sid = str(session_id)
        norm = normalize_speech_text(transcript) or (transcript or '').strip()
        if not norm:
            return False
        now = time.time()
        with self._lock:
            prev = self._last_child_speech.get(sid)
            if prev:
                prev_norm, prev_at = prev
                if (
                    prev_norm == norm
                    and (now - float(prev_at)) < _CHILD_SPEECH_DEDUPE_SEC
                ):
                    return False
                # Growing / shrinking near-duplicates from overlapping chunks
                if (now - float(prev_at)) < _CHILD_SPEECH_DEDUPE_SEC and (
                    norm in prev_norm or prev_norm in norm
                ):
                    # Prefer the longer form; skip if not longer than last
                    if len(norm) <= len(prev_norm):
                        return False
            self._last_child_speech[sid] = (norm, now)
        return True

    def _emit_child_speech_recognized(
        self,
        session_id: str,
        transcript: str,
        *,
        keyword_hit: bool = False,
        keyword: Optional[str] = None,
        status: str = '',
    ) -> None:
        """Push recognized child text into the child dialogue chat UI."""
        text = (transcript or '').strip()
        if not text:
            return
        if not self._should_emit_child_speech(session_id, text):
            return
        try:
            sio = KeywordListenService._resolve_socketio()
            if sio is None:
                return
            child_room = f'session_{session_id}_child'
            payload: Dict[str, Any] = {
                'sessionId': str(session_id),
                'session_id': str(session_id),
                'transcript': text,
                'keywordHit': bool(keyword_hit),
                'source': 'continuous_asr',
            }
            if keyword:
                payload['keyword'] = keyword
            if status:
                payload['status'] = status
            sio.emit('child_speech_recognized', payload, room=child_room)
        except Exception as emit_err:  # noqa: BLE001
            logger.debug(
                'keyword_listen child transcript emit failed session=%s: %s',
                session_id,
                emit_err,
            )

    @staticmethod
    def _emit_teacher_auto_praise(session_id: str, payload: Dict[str, Any]) -> bool:
        """Notify teacher room to run the same praise path as the 表扬 button."""
        try:
            sio = KeywordListenService._resolve_socketio()
            if sio is None:
                logger.warning(
                    'keyword_listen auto_praise no socketio session=%s',
                    session_id,
                )
                return False

            # Teacher joins both session_{id} and session_{id}_teacher.
            # Emit only to the teacher room so ControlPage does not handle
            # the same keyword_auto_praise twice (double praise multimodal).
            teacher_room = f'session_{session_id}_teacher'
            sio.emit('keyword_auto_praise', payload, room=teacher_room)
            return True
        except Exception as emit_err:  # noqa: BLE001
            logger.error(
                'keyword_listen teacher notify failed session=%s: %s',
                session_id,
                emit_err,
                exc_info=True,
            )
            return False


_keyword_listen_service: Optional[KeywordListenService] = None
_service_lock = threading.Lock()


def get_keyword_listen_service() -> KeywordListenService:
    global _keyword_listen_service
    with _service_lock:
        if _keyword_listen_service is None:
            _keyword_listen_service = KeywordListenService()
        return _keyword_listen_service
