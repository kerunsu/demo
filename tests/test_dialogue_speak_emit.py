"""对话 LLM 回复应下发 robot_speak_text（浏览器 TTS）。"""
from unittest.mock import patch

from app.dialogue.sockets import _emit_speak, _handle_dialogue_utterance
from app.dialogue.service import WAKE_ACK_REPLY


class _Robot:
    def __init__(self, accepted=True, commit=True):
        self.accepted = accepted
        self.commit = commit
        self.reservations = []
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
        assert emit.call_args.kwargs.get("room") == "session_abc_child"
        assert robot.reservations[0]["session_id"] == "abc"
        assert robot.expected[0][0][0] == payload["behaviorId"]


def test_emit_speak_busy_rejects_dialogue_without_emitting(monkeypatch):
    robot = _install_robot(monkeypatch, _Robot(accepted=False))
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
            page_context={"courseType": "pairing", "prompt": "选和上面一样的。"},
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
