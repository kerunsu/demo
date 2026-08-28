"""对话 LLM 回复应下发 robot_speak_text（浏览器 TTS）。"""
from unittest.mock import patch

from app.dialogue.sockets import _emit_speak, _handle_dialogue_utterance
from app.dialogue.service import WAKE_ACK_REPLY


class _Robot:
    def __init__(self, accepted=True, commit=True):
        self.accepted = accepted
        self.commit = commit
        self.reservations = []
        self.expression_starts = []
        self.expected = []
        self.aborted = []

    def reserve_audio_only_behavior(self, **kwargs):
        self.reservations.append(kwargs)
        if not self.accepted:
            return {
                "accepted": False,
                "activeBehaviorId": "formal-active",
            }
        return {
            "accepted": True,
            "behaviorId": kwargs["behavior_id"],
        }

    def reserve_behavior(self, **kwargs):
        return self.reserve_audio_only_behavior(**kwargs)

    def start_dialogue_reply_behavior(self, **kwargs):
        self.expression_starts.append(kwargs)
        return {
            "behaviorId": kwargs["behavior_id"],
            "emotion": kwargs["emotion"],
            "motion": None,
            "scheduledDelayMs": 700,
        }

    def set_behavior_audio_expected(self, *args, **kwargs):
        self.expected.append((args, kwargs))
        return self.commit

    def abort_behavior(self, behavior_id):
        self.aborted.append(behavior_id)
        return True


def _install_robot(monkeypatch, robot=None):
    import app.robot

    robot = robot or _Robot()
    monkeypatch.setattr(app.robot, "get_robot_service", lambda: robot)
    return robot


def test_emit_speak_skips_empty_text():
    with patch("app.dialogue.sockets.emit") as emit:
        _emit_speak(room="session_x_child", text="  ", intent="dialogue")
        emit.assert_not_called()


def test_emit_speak_reserves_audio_only_and_sends_exactly_once(monkeypatch):
    robot = _install_robot(monkeypatch)
    monkeypatch.setattr("app.dialogue.sockets.Config.BROWSER_SPEECH_RATE", 1.15)
    with patch("app.dialogue.sockets.emit") as emit:
        assert _emit_speak(
            room="session_abc_child",
            text="dialogue reply",
            intent="dialogue",
            source="dialogue",
        )
        assert emit.call_count == 1
        payload = emit.call_args.args[1]
        assert payload["text"] == "dialogue reply"
        assert payload["intent"] == "dialogue"
        assert payload["source"] == "dialogue"
        assert payload["ttsMode"] == "browser"
        assert payload["sessionId"] == "abc"
        assert payload["behaviorId"].startswith("dialogue-")
        assert payload["requestId"].startswith("dialogue-request-")
        assert payload["speechRate"] == 1.15
        assert emit.call_args.kwargs.get("room") == "session_abc_child"
        assert robot.reservations[0]["session_id"] == "abc"
        assert robot.expected[0][0][0] == payload["behaviorId"]


def test_emit_speak_uses_screen_expression_without_motion(monkeypatch):
    robot = _install_robot(monkeypatch)
    robot.select_dialogue_reply_emotion = lambda text: {
        "emotion": "happy.mp4",
        "charCount": len(text),
        "maxChars": 20,
    }
    with patch("app.dialogue.sockets.emit") as emit:
        assert _emit_speak(
            room="session_expr_child",
            session_id="expr",
            text="匹配到表情",
            intent="dialogue",
            source="dialogue",
        )
    payload = emit.call_args.args[1]
    assert payload["expression"] == "happy.mp4"
    assert "expressionMatch" not in payload
    assert payload["delayMs"] == 700
    assert len(robot.reservations) == 1
    assert robot.expression_starts[0]["motion"] is None


def test_emit_speak_busy_queues_dialogue_without_emitting(monkeypatch):
    from app.dialogue.sockets import (
        flush_pending_dialogue_speak,
        pending_dialogue_speak_queued,
        _pending_dialogue_speak,
        _pending_dialogue_speak_lock,
    )

    robot = _install_robot(monkeypatch, _Robot(accepted=False))
    with _pending_dialogue_speak_lock:
        _pending_dialogue_speak.pop("abc", None)
    with patch("app.dialogue.sockets.emit") as emit:
        accepted = _emit_speak(
            room="session_abc_child",
            session_id="abc",
            text="busy dialogue",
            intent="dialogue",
        )

    assert accepted is False
    emit.assert_not_called()
    assert len(robot.reservations) == 1
    assert pending_dialogue_speak_queued("abc") is True

    robot.accepted = True
    with patch("app.dialogue.sockets.emit") as emit:
        assert flush_pending_dialogue_speak("abc") is True
        emit.assert_called_once()
    assert pending_dialogue_speak_queued("abc") is False


def test_emit_speak_commit_failure_aborts_before_emitting(monkeypatch):
    robot = _install_robot(
        monkeypatch,
        _Robot(accepted=True, commit=False),
    )
    with patch("app.dialogue.sockets.emit") as emit:
        accepted = _emit_speak(
            room="session_abc_child",
            session_id="abc",
            text="must not leak",
            intent="dialogue",
        )

    assert accepted is False
    emit.assert_not_called()
    assert len(robot.aborted) == 1


def test_handle_utterance_awake_emits_dialogue_speak(monkeypatch):
    _install_robot(monkeypatch)

    class FakeSvc:
        def is_session_awake(self, *_a, **_k):
            return True

        def _sync_history_for_context(self, *_a, **_k):
            return None

        def generate_reply(self, text, session_id=None, page_context=None):
            return {
                "reply": "真棒。我们先看屏幕吧。",
                "strategy": "llm",
                "provider": "asd",
            }

    monkeypatch.setattr(
        "app.dialogue.sockets.get_dialogue_service", lambda: FakeSvc()
    )
    with patch("app.dialogue.sockets.emit") as emit:
        _handle_dialogue_utterance(
            session_id="sid1",
            child_text="这是什么",
            page_context={"courseType": "pairing", "prompt": "找出和这个一样的。"},
            room="session_sid1_child",
        )
        speak_calls = [
            c for c in emit.call_args_list if c.args and c.args[0] == "robot_speak_text"
        ]
        assert speak_calls, "LLM 回复必须下发 robot_speak_text"
        assert speak_calls[0].args[1]["text"] == "真棒。我们先看屏幕吧。"
        assert speak_calls[0].args[1]["intent"] == "dialogue"
        result_calls = [
            c
            for c in emit.call_args_list
            if c.args and c.args[0] == "child_dialogue_result"
        ]
        assert result_calls
        assert result_calls[0].args[1]["ok"] is True


def test_awake_course_miss_falls_through_to_dialogue(monkeypatch):
    """已唤醒时，命名/拟声错答不能吞掉孩子随后发起的普通对话。"""
    _install_robot(monkeypatch)

    class FakeSvc:
        def is_session_awake(self, *_args, **_kwargs):
            return True

        def _sync_history_for_context(self, *_args, **_kwargs):
            return None

        def generate_reply(self, text, **_kwargs):
            assert text == "我想出去玩"
            return {"reply": "可以先和老师说一声。", "strategy": "llm", "provider": "test"}

    class FakeKw:
        def try_auto_praise_from_transcript(self, *_args):
            return False

        def should_consume_dialogue_turn(self, *_args):
            raise AssertionError("awake course miss must not consume the dialogue turn")

    monkeypatch.setattr("app.dialogue.sockets.get_dialogue_service", lambda: FakeSvc())
    monkeypatch.setattr(
        "app.services.keyword_listen.get_keyword_listen_service",
        lambda: FakeKw(),
    )
    with patch("app.dialogue.sockets.emit") as emit:
        _handle_dialogue_utterance(
            session_id="awake-naming",
            child_text="我想出去玩",
            page_context={"courseType": "naming", "target": "狗"},
            room="session_awake-naming_child",
        )

    spoken = [
        call.args[1]
        for call in emit.call_args_list
        if call.args and call.args[0] == "robot_speak_text"
    ]
    assert spoken[-1]["text"] == "可以先和老师说一声。"


def test_sleeping_course_miss_is_still_consumed_before_wake_gate(monkeypatch):
    """未唤醒的课程作答窗口仍消费错答，不把每个错答都送给 LLM。"""

    class FakeSvc:
        def is_session_awake(self, *_args, **_kwargs):
            return False

        def _sync_history_for_context(self, *_args, **_kwargs):
            return None

        def generate_reply(self, *_args, **_kwargs):
            raise AssertionError("sleeping course miss must not reach LLM")

    class FakeKw:
        def try_auto_praise_from_transcript(self, *_args):
            return False

        def should_consume_dialogue_turn(self, *_args):
            return True

    monkeypatch.setattr("app.dialogue.sockets.get_dialogue_service", lambda: FakeSvc())
    monkeypatch.setattr(
        "app.services.keyword_listen.get_keyword_listen_service",
        lambda: FakeKw(),
    )
    with patch("app.dialogue.sockets.emit") as emit:
        _handle_dialogue_utterance(
            session_id="sleeping-naming",
            child_text="我不知道",
            page_context={"courseType": "naming", "target": "狗"},
            room="session_sleeping-naming_child",
        )

    results = [
        call.args[1]
        for call in emit.call_args_list
        if call.args and call.args[0] == "child_dialogue_result"
    ]
    assert results[-1]["courseAnswer"] is True
    assert results[-1]["keywordHit"] is False


def test_handle_utterance_wake_ack_emits_speak(monkeypatch):
    _install_robot(monkeypatch)
    monkeypatch.setattr("app.config.Config.DIALOGUE_WAKE_WORD_ENABLED", True)

    class FakeSvc:
        def is_session_awake(self, *_a, **_k):
            return False

        def set_awake(self, *_a, **_k):
            return None

        def _sync_history_for_context(self, *_a, **_k):
            return None

    monkeypatch.setattr(
        "app.dialogue.sockets.get_dialogue_service", lambda: FakeSvc()
    )
    monkeypatch.setattr(
        "app.dialogue.sockets.parse_wake_utterance",
        lambda _t: (True, ""),
    )
    with patch("app.dialogue.sockets.emit") as emit:
        _handle_dialogue_utterance(
            session_id="sid1",
            child_text="麦麦，麦麦",
            page_context={"courseType": "naming"},
            room="session_sid1_child",
        )
        speak_calls = [
            c for c in emit.call_args_list if c.args and c.args[0] == "robot_speak_text"
        ]
        assert speak_calls
        assert speak_calls[0].args[1]["text"] == WAKE_ACK_REPLY
        assert speak_calls[0].args[1]["intent"] == "wake_ack"


def test_wake_with_question_course_miss_falls_through_to_dialogue(monkeypatch):
    _install_robot(monkeypatch)
    monkeypatch.setattr("app.config.Config.DIALOGUE_WAKE_WORD_ENABLED", True)

    class FakeSvc:
        def is_session_awake(self, *_a, **_k):
            return False

        def set_awake(self, *_a, **_k):
            return None

        def _sync_history_for_context(self, *_a, **_k):
            return None

        def generate_reply(self, text, **_kwargs):
            assert text == "小狗怎么叫啊"
            return {"reply": "小狗会汪汪叫。", "strategy": "llm", "provider": "test"}

    class FakeKw:
        def try_auto_praise_from_transcript(self, *_args):
            return False

        def should_consume_dialogue_turn(self, *_args):
            raise AssertionError("explicit wake remainder must not be swallowed as a course miss")

    monkeypatch.setattr("app.dialogue.sockets.get_dialogue_service", lambda: FakeSvc())
    monkeypatch.setattr(
        "app.dialogue.sockets.parse_wake_utterance",
        lambda _text: (True, "小狗怎么叫啊"),
    )
    monkeypatch.setattr(
        "app.services.keyword_listen.get_keyword_listen_service", lambda: FakeKw()
    )
    with patch("app.dialogue.sockets.emit") as emit:
        _handle_dialogue_utterance(
            session_id="wake-question",
            child_text="麦麦麦麦小狗怎么叫啊",
            page_context={"courseType": "onomatopoeia", "target": "猫"},
            room="session_wake-question_child",
        )

    spoken = [
        call.args[1] for call in emit.call_args_list
        if call.args and call.args[0] == "robot_speak_text"
    ]
    assert spoken[-1]["text"] == "小狗会汪汪叫。"
    assert spoken[-1]["intent"] == "dialogue"


def test_handle_utterance_keyword_hit_skips_llm(monkeypatch):
    """对话 STT 命中武装关键词 → 表扬且不走 LLM。"""
    _install_robot(monkeypatch)

    class FakeSvc:
        def is_session_awake(self, *_a, **_k):
            return True

        def _sync_history_for_context(self, *_a, **_k):
            return None

        def generate_reply(self, *_a, **_k):
            raise AssertionError("keyword hit must not call LLM")

    class FakeKw:
        def try_auto_praise_from_transcript(self, session_id, transcript):
            assert session_id == "sid-kw"
            assert "老虎" in transcript
            return True

    monkeypatch.setattr(
        "app.dialogue.sockets.get_dialogue_service", lambda: FakeSvc()
    )
    monkeypatch.setattr(
        "app.services.keyword_listen.get_keyword_listen_service",
        lambda: FakeKw(),
    )
    with patch("app.dialogue.sockets.emit") as emit:
        _handle_dialogue_utterance(
            session_id="sid-kw",
            child_text="这是老虎呀",
            page_context={"courseType": "naming", "target": "老虎"},
            room="session_sid-kw_child",
        )
        result_calls = [
            c
            for c in emit.call_args_list
            if c.args and c.args[0] == "child_dialogue_result"
        ]
        assert result_calls
        payload = result_calls[0].args[1]
        assert payload["ok"] is True
        assert payload["keywordHit"] is True
        assert payload["transcript"] == "这是老虎呀"
        assert payload.get("reply") is None
        speak_calls = [
            c for c in emit.call_args_list if c.args and c.args[0] == "robot_speak_text"
        ]
        assert not speak_calls
