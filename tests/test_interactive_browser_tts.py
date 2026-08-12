"""配对/排序交互课：browser TTS 走 robot_speak_text，不走预录 MP3。"""
import os

from app.dialogue.phrases import (
    get_phrase_bank,
    ordering_phrase_key,
    pick_phrase,
)


def test_pairing_ordering_praise_pools_match_demorobot_style():
    bank = get_phrase_bank(force_reload=True)
    pairing = bank["praise"]["pairing"]
    ordering = bank["praise"]["ordering"]
    assert "回答正确，真棒！" in pairing
    assert "找对了，很好！" in pairing
    assert "这题做对了！" in ordering
    assert "你答对了，真棒！" in ordering
    # matching / sequencing 与 pairing / ordering 对齐
    assert bank["praise"]["matching"] == pairing
    assert bank["praise"]["sequencing"] == ordering


def test_ordering_rule_aware_question_phrases():
    bank = get_phrase_bank(force_reload=True)
    expected = {
        ("size", "bigger"): "选出更大的那张。",
        ("size", "smaller"): "选出更小的那张。",
        ("length", "longer"): "选出更长的那张。",
        ("length", "shorter"): "选出更短的那张。",
        ("height", "taller"): "选出更高的那张。",
        ("height", "shorter"): "选出更矮的那张。",
        ("count", "more"): "选出更多的那张。",
        ("count", "less"): "选出更少的那张。",
    }
    for (cat, rule), phrase in expected.items():
        key = ordering_phrase_key(cat, rule)
        assert key is not None
        assert bank["question"][key] == [phrase]
        assert pick_phrase("question", "ordering", variant=key) == phrase
    # 新题提问不得落进鼓励/重试句
    fallback = bank["question"]["ordering"]
    assert all("再选" not in line and "再试" not in line for line in fallback)


def test_pick_phrase_pairing_praise_from_course_pool(monkeypatch):
    get_phrase_bank(force_reload=True)
    # 多次抽取应落在 pairing 池内
    pool = set(get_phrase_bank()["praise"]["pairing"])
    for _ in range(20):
        assert pick_phrase("praise", "pairing") in pool


def test_selected_question_ask_pools():
    """用户选定的提问话术池：命名/拟声/模仿/配对。"""
    bank = get_phrase_bank(force_reload=True)
    q = bank["question"]

    naming = [
        "你知道这是什么吗？",
        "告诉麦麦，这是什么？",
        "这个是什么呀？",
        "你会叫它的名字吗？",
        "这张图里是什么呀？",
    ]
    assert q["naming"] == naming
    assert q["speech"] == naming

    onomatopoeia = [
        "{name}会怎么叫呀？",
        "学一学{name}的叫声。",
        "{name}的声音是怎样的？",
    ]
    assert q["onomatopoeia"] == onomatopoeia

    mimic = [
        "看麦麦，做一样的动作。",
        "跟着麦麦，学这个动作。",
        "手臂和身体，跟麦麦一样。",
        "学一学这个动作吧。",
    ]
    assert q["mimic"] == mimic
    assert q["imitation"] == mimic
    assert q["pose"] == mimic

    pairing = [
        "找出和上面一样的。",
        "下面哪张和上面一样？",
        "选一张最像上面的。",
        "找一找，哪张是一样的？",
        "点和上面相同的那一张。",
        "哪一张和上面完全一样？",
        "先看上面，再找一样的。",
    ]
    assert q["pairing"] == pairing
    assert q["matching"] == pairing

    # 抽取应落在池内；排序提问未改；社交走独立 intent 非 question
    for _ in range(15):
        assert pick_phrase("question", "naming") in naming
        assert pick_phrase("question", "pairing") in pairing
        assert pick_phrase("question", "mimic") in mimic
    assert "social" not in q
    assert q["ordering"] == ["选出对的那张。"]


def test_social_phrase_pools():
    """社交打招呼/再见话术池（browser TTS）。"""
    bank = get_phrase_bank(force_reload=True)
    intro = bank["social_greeting_intro"]["social"]
    play = bank["social_greeting_play"]["social"]
    bye = bank["social_farewell_bye"]["social"]
    reply = bank["social_farewell_reply"]["social"]
    assert intro == ["你好，我是麦麦。"]
    assert "我们一起玩吧。" in play
    assert "再见啦。" in bye
    assert "再见，下次见。" in reply
    assert pick_phrase("social_greeting_intro", "social") in intro
    assert pick_phrase("social_farewell_bye", "social") in bye


def test_play_interactive_browser_emits_robot_speak_text(monkeypatch):
    monkeypatch.setenv("DIALOGUE_TTS_MODE", "browser")
    get_phrase_bank(force_reload=True)

    from app.audio.service import AudioService

    emitted = []

    class FakeSocketio:
        def emit(self, event, payload, room=None, broadcast=False):
            emitted.append({"event": event, "payload": payload, "room": room})

    class FakeEmitter:
        socketio = FakeSocketio()

        def emit_for_course(self, **kwargs):
            raise AssertionError("browser 模式不应调用 emit_for_course")

    svc = AudioService()
    svc._emitter = FakeEmitter()

    ok = svc.play_interactive_course_audio("sess1", "pairing", "praise")
    assert ok is True
    # 精确房间单发；不得 room + broadcast 让同一儿童收到两遍。
    assert len(emitted) == 1
    assert emitted[0]["event"] == "robot_speak_text"
    assert emitted[0]["room"] == "session_sess1_child"
    payload = emitted[0]["payload"]
    assert payload["intent"] == "praise"
    assert payload["courseType"] == "pairing"
    assert payload["ttsMode"] == "browser"
    assert payload["text"] in get_phrase_bank()["praise"]["pairing"]


def test_browser_tts_empty_room_is_rejected_without_broadcast(monkeypatch):
    monkeypatch.setenv("DIALOGUE_TTS_MODE", "browser")

    from app.audio.service import AudioService

    emitted = []

    class EmptyManager:
        @staticmethod
        def get_participants(namespace, room):
            return iter(())

    class FakeSocketio:
        server = type("Server", (), {"manager": EmptyManager()})()

        def emit(self, event, payload, room=None, broadcast=False):
            emitted.append({"event": event, "payload": payload, "room": room})

    class FakeEmitter:
        socketio = FakeSocketio()

    svc = AudioService()
    svc._emitter = FakeEmitter()
    assert not svc.play_interactive_course_audio(
        "not-joined-yet",
        "pairing",
        "question",
    )

    assert emitted == []


def test_play_interactive_ordering_question_maps_to_rule_phrase(monkeypatch):
    monkeypatch.setenv("DIALOGUE_TTS_MODE", "browser")
    get_phrase_bank(force_reload=True)

    from app.audio.service import AudioService

    emitted = []

    class FakeSocketio:
        def emit(self, event, payload, room=None, broadcast=False):
            emitted.append(payload)

    class FakeEmitter:
        socketio = FakeSocketio()

        def emit_for_course(self, **kwargs):
            raise AssertionError("browser 模式不应调用 emit_for_course")

    svc = AudioService()
    svc._emitter = FakeEmitter()

    ok = svc.play_interactive_course_audio(
        "s2", "ordering", "question_size_bigger", category="size", rule="bigger"
    )
    assert ok is True
    assert emitted[0]["intent"] == "question"
    assert emitted[0]["courseType"] == "ordering"
    assert emitted[0]["variant"] == "size_bigger"
    assert emitted[0]["text"] == "选出更大的那张。"

    emitted.clear()
    ok2 = svc.play_interactive_course_audio("s2", "ordering", "size_bigger")
    assert ok2 is True
    assert emitted[0]["text"] == "选出更大的那张。"

    emitted.clear()
    ok3 = svc.play_interactive_course_audio(
        "s2", "ordering", "question_height_taller", category="height", rule="taller"
    )
    assert ok3 is True
    assert emitted[0]["text"] == "选出更高的那张。"


def test_legacy_file_env_cannot_disable_realtime_tts(monkeypatch):
    monkeypatch.setenv("DIALOGUE_TTS_MODE", "file")

    from app.audio.service import AudioService

    calls = []

    class FakeSocketio:
        def emit(self, event, payload, room=None, broadcast=False):
            calls.append((event, payload, room))

    class FakeEmitter:
        socketio = FakeSocketio()

        def emit_for_course(self, **kwargs):
            raise AssertionError("旧 file 环境值不应再播放预录音频")

    svc = AudioService()
    svc._emitter = FakeEmitter()
    ok = svc.play_interactive_course_audio("s3", "ordering", "praise")
    assert ok is True
    assert len(calls) == 1
    assert calls[0][0] == "robot_speak_text"
    assert calls[0][1]["intent"] == "praise"


def test_social_browser_aux_emits_robot_speak_text(monkeypatch):
    """社交 aux 在 browser 模式走 robot_speak_text，不播预录 MP3。"""
    monkeypatch.setenv("DIALOGUE_TTS_MODE", "browser")
    get_phrase_bank(force_reload=True)

    from app.audio.service import AudioService

    cases = [
        ("socialGreetingIntro", "social_greeting_intro", "你好，我是麦麦。"),
        ("socialGreetingPlay", "social_greeting_play", "我们一起玩吧。"),
        ("socialFarewellBye", "social_farewell_bye", "再见啦。"),
        ("socialFarewellReply", "social_farewell_reply", "再见，下次见。"),
    ]

    for aux_key, intent, sample in cases:
        emitted = []

        class FakeSocketio:
            def emit(self, event, payload, room=None, broadcast=False):
                emitted.append({"event": event, "payload": payload, "room": room})

        class FakeEmitter:
            socketio = FakeSocketio()

            def emit_for_course(self, **kwargs):
                raise AssertionError("browser 模式不应调用 emit_for_course")

        svc = AudioService()
        svc._emitter = FakeEmitter()
        ok = svc.process_play_resource(
            "sess_social",
            {"courseType": "social", "aux": {aux_key: True}},
        )
        assert ok is True, aux_key
        assert len(emitted) == 1, aux_key
        assert emitted[0]["event"] == "robot_speak_text"
        assert emitted[0]["room"] == "session_sess_social_child"
        payload = emitted[0]["payload"]
        assert payload["intent"] == intent
        assert payload["courseType"] == "social"
        assert payload["ttsMode"] == "browser"
        pool = get_phrase_bank()[intent]["social"]
        assert payload["text"] in pool
        assert sample in pool


def test_social_legacy_file_env_still_uses_realtime_tts(monkeypatch):
    monkeypatch.setenv("DIALOGUE_TTS_MODE", "file")

    from app.audio.service import AudioService

    calls = []

    class FakeSocketio:
        def emit(self, event, payload, room=None, broadcast=False):
            calls.append((event, payload, room))

    class FakeEmitter:
        socketio = FakeSocketio()

        def emit_for_course(self, **kwargs):
            raise AssertionError("社交课不应再播放预录音频")

    svc = AudioService()
    svc._emitter = FakeEmitter()
    ok = svc.process_play_resource(
        "s_file",
        {"courseType": "social", "aux": {"socialGreetingIntro": True}},
    )
    assert ok is True
    assert len(calls) == 1
    assert calls[0][0] == "robot_speak_text"
    assert calls[0][1]["intent"] == "social_greeting_intro"


def test_legacy_both_env_reports_one_realtime_utterance(monkeypatch):
    """A stale both setting cannot re-enable duplicate file playback."""
    monkeypatch.setenv("DIALOGUE_TTS_MODE", "both")

    from app.audio.service import AudioService

    emitted = []

    class FakeSocketio:
        def emit(self, event, payload, room=None, broadcast=False):
            emitted.append((event, payload, room))

    class FakeEmitter:
        socketio = FakeSocketio()

        def emit_for_course(self, **kwargs):
            raise AssertionError("both 已废弃，不应再播放预录音频")

    svc = AudioService()
    svc._emitter = FakeEmitter()
    details = svc.process_play_resource(
        "s_both",
        {"courseType": "pairing", "aux": {"praise": True}},
        behavior_id="behavior-both",
        request_id="request-both",
        return_details=True,
    )

    assert details["triggered"] is True
    assert details["transportDispatchCount"] == 1
    assert details["dispatchCount"] == 1
    assert details["behaviorId"] == "behavior-both"
    assert [event for event, _payload, _room in emitted] == ["robot_speak_text"]


def test_social_aux_reuses_session_without_resolved_file():
    """社交再见/打招呼无 media_file 时，aux 仍应复用当前课点会话。"""
    from app.session import get_session_manager
    from app.sockets.handlers import _close_runtime_session

    sm = get_session_manager()
    sid_student = 9017
    for sess in list(sm.get_sessions_by_student(sid_student)):
        try:
            _close_runtime_session(sess.session_id, send_summary=False)
        except Exception:
            pass

    sess = sm.create_session(
        student_id=sid_student,
        course_id=10,
        course_item_id=80,
        training_session_id="ts-social-farewell",
        question_id="10_80_0",
        question_index=0,
        metadata={"course_type": "social", "continuous_recording": True},
    )
    sess.start()
    assert not sess.resolved_file_path
    sm.update_session(sess)

    resolved_course_type = "social"
    item_id = 80
    course_id = 10
    is_aux = False
    for s in sm.list_all_sessions():
        if not s.is_active() or s.course_id != course_id:
            continue
        if s.course_item_id != item_id:
            continue
        if not s.resolved_file_path:
            sess_type = (s.metadata or {}).get("course_type") or resolved_course_type
            if sess_type != "social" and resolved_course_type != "social":
                continue
        is_aux = True
        break

    assert is_aux is True
    try:
        _close_runtime_session(sess.session_id, send_summary=False)
    except Exception:
        pass
