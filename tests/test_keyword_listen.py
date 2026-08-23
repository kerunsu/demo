"""keyword_listen：规范化匹配、拟声别名、武装门控。"""
from __future__ import annotations

import time

from app.services.keyword_listen import (
    KeywordListenService,
    find_keyword_hit,
    normalize_speech_text,
    resolve_answer_keywords,
)


def test_normalize_strips_punct_and_particles():
    assert normalize_speech_text(' 老 虎！') == '老虎'
    assert normalize_speech_text('老虎呀') == '老虎'
    assert normalize_speech_text('喵喵啊') == '喵喵'


def test_resolve_naming_prefers_speech_target():
    kws = resolve_answer_keywords(
        course_type='naming',
        speech_target='老虎',
        name='大老虎图片',
    )
    assert kws[0] == '老虎'
    assert '大老虎图片' not in kws


def test_resolve_naming_falls_back_to_name():
    kws = resolve_answer_keywords(
        course_type='naming',
        speech_target=None,
        name='苹果',
    )
    assert kws == ['苹果']


def test_resolve_onomatopoeia_aliases_for_cat():
    kws = resolve_answer_keywords(
        course_type='onomatopoeia',
        speech_target=None,
        name='小猫叫',
    )
    assert '小猫叫' in kws
    assert '喵' in kws or '喵喵' in kws


def test_resolve_speech_target_pipe_aliases():
    kws = resolve_answer_keywords(
        course_type='onomatopoeia',
        speech_target='喵|喵喵',
        name='小猫叫',
    )
    assert '喵' in kws
    assert '喵喵' in kws


def test_find_keyword_hit_prefer_longer():
    assert find_keyword_hit('这是老虎呀', ['虎', '老虎']) == '老虎'
    assert find_keyword_hit('喵喵叫', ['喵', '喵喵']) == '喵喵'
    assert find_keyword_hit('狮子', ['老虎']) is None


def test_arm_hit_praise_gate():
    svc = KeywordListenService()
    sid = 'sess-kw-1'
    svc.prepare(
        sid,
        course_type='naming',
        item_id=42,
        speech_target='老虎',
        name='老虎',
    )
    status, hit = svc.evaluate_transcript(sid, '老虎')
    assert status == 'suppressed_echo'
    assert hit == '老虎'

    assert svc.arm_after_question(sid, intent='question', item_id=42)
    status, hit = svc.evaluate_transcript(sid, '这是老虎')
    assert status == 'hit'
    assert hit == '老虎'

    snap = svc.consume_hit(sid, hit)
    assert snap is not None and snap.praised
    status2, _ = svc.evaluate_transcript(sid, '老虎')
    assert status2 == 'praised'


def test_teacher_praise_disarms():
    svc = KeywordListenService()
    sid = 'sess-kw-2'
    svc.prepare(sid, course_type='speech', item_id=1, name='香蕉')
    svc.arm_after_question(sid, intent='question')
    svc.note_teacher_praise(sid)
    status, hit = svc.evaluate_transcript(sid, '香蕉')
    assert status == 'praised'
    assert hit == '香蕉'


def test_hint_end_rearms_same_course_answer_window():
    svc = KeywordListenService()
    sid = 'sess-kw-hint'
    svc.prepare(sid, course_type='onomatopoeia', item_id=5, speech_target='汪')
    assert svc.arm_after_question(sid, intent='question', item_id=5)
    svc.disarm(sid, reason='system_speak:hint')
    assert svc.evaluate_transcript(sid, '汪')[0] == 'suppressed_echo'
    assert svc.arm_after_question(sid, intent='hint', item_id=5)
    assert svc.evaluate_transcript(sid, '汪') == ('hit', '汪')


def test_active_course_answer_window_consumes_miss_and_duplicate_tail():
    svc = KeywordListenService()
    sid = 'sess-kw-route'
    svc.prepare(sid, course_type='naming', item_id=8, name='小狗')
    assert svc.should_consume_dialogue_turn(sid) is False
    assert svc.arm_after_question(sid, intent='question', item_id=8)
    assert svc.evaluate_transcript(sid, '我不知道')[0] == 'miss'
    assert svc.should_consume_dialogue_turn(sid) is True
    svc.note_teacher_praise(sid)
    assert svc.should_consume_dialogue_turn(sid) is True


def test_timeout_disarms(monkeypatch):
    svc = KeywordListenService()
    sid = 'sess-kw-3'
    svc.prepare(
        sid,
        course_type='naming',
        item_id=3,
        name='苹果',
        timeout_sec=1.0,
    )
    svc.arm_after_question(sid, intent='question')
    state = svc.get_state(sid)
    assert state and state.armed
    # rewind armed_at
    with svc._lock:
        svc._states[sid].armed_at = time.time() - 5
    status, _ = svc.evaluate_transcript(sid, '苹果')
    assert status == 'timeout'


def test_emit_teacher_auto_praise_only_teacher_room(monkeypatch):
    """Teacher joins session + teacher rooms; emit once to teacher room only."""
    svc = KeywordListenService()
    calls = []

    class FakeSio:
        def emit(self, event, payload, room=None):
            calls.append((event, payload, room))

    monkeypatch.setattr(
        KeywordListenService,
        '_resolve_socketio',
        staticmethod(lambda: FakeSio()),
    )
    ok = KeywordListenService._emit_teacher_auto_praise(
        'sess-room',
        {'sessionId': 'sess-room', 'requestId': 'keyword-praise-abc'},
    )
    assert ok is True
    assert len(calls) == 1
    assert calls[0][0] == 'keyword_auto_praise'
    assert calls[0][2] == 'session_sess-room_teacher'


def test_try_auto_praise_emits_child_speech_recognized(monkeypatch):
    """Keyword hit must push transcript to child dialogue UI."""
    svc = KeywordListenService()
    sid = 'sess-kw-ui'
    svc.prepare(sid, course_type='naming', item_id=9, name='苹果')
    assert svc.arm_after_question(sid, intent='question', item_id=9)

    calls = []

    class FakeSio:
        def emit(self, event, payload, room=None):
            calls.append((event, payload, room))

    monkeypatch.setattr(
        KeywordListenService,
        '_resolve_socketio',
        staticmethod(lambda: FakeSio()),
    )
    monkeypatch.setattr(
        KeywordListenService,
        '_emit_teacher_auto_praise',
        staticmethod(lambda session_id, payload: True),
    )

    assert svc.try_auto_praise_from_transcript(sid, '这是苹果') is True
    child_emits = [c for c in calls if c[0] == 'child_speech_recognized']
    assert len(child_emits) == 1
    assert child_emits[0][1]['transcript'] == '这是苹果'
    assert child_emits[0][1]['keywordHit'] is True
    assert child_emits[0][2] == 'session_sess-kw-ui_child'


def test_try_auto_praise_once_under_concurrent_calls(monkeypatch):
    """ASR + dialogue must not both emit praise for one hit."""
    svc = KeywordListenService()
    sid = 'sess-kw-race'
    svc.prepare(sid, course_type='naming', item_id=7, name='老虎')
    assert svc.arm_after_question(sid, intent='question', item_id=7)

    emits = []

    def fake_emit(session_id, payload):
        emits.append((session_id, payload))
        return True

    monkeypatch.setattr(svc, '_emit_teacher_auto_praise', fake_emit)
    monkeypatch.setattr(
        KeywordListenService,
        '_emit_child_speech_recognized',
        staticmethod(lambda *args, **kwargs: None),
    )

    assert svc.try_auto_praise_from_transcript(sid, '老虎') is True
    assert svc.try_auto_praise_from_transcript(sid, '老虎') is False
    assert len(emits) == 1
