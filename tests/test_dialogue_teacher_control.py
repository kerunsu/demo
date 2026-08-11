from unittest.mock import patch

from flask import Flask
from flask_socketio import SocketIO

from app.config import Config
from app.dialogue.sockets import _handle_dialogue_utterance, register_dialogue_events
from app.services.teacher_control import get_teacher_control_registry


def _http_teacher(app, teacher_id=42):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["teacher_id"] = teacher_id
        sess["teacher_username"] = "teacher"
    return client


def _events(client, name):
    return [
        item.get("args", [{}])[0]
        for item in client.get_received()
        if item.get("name") == name
    ]


def test_wake_word_disabled_rejects_without_playing_sound(monkeypatch):
    monkeypatch.setattr(Config, "DIALOGUE_WAKE_WORD_ENABLED", False)

    class Service:
        def _sync_history_for_context(self, *_args):
            return None

        def is_session_awake(self, *_args):
            return False

    monkeypatch.setattr("app.dialogue.sockets.get_dialogue_service", lambda: Service())
    with patch("app.dialogue.sockets.emit") as emit:
        _handle_dialogue_utterance(
            session_id="runtime-1",
            child_text="麦麦，麦麦",
            page_context={},
            room="session_runtime-1_child",
        )
    assert not [call for call in emit.call_args_list if call.args[0] == "robot_speak_text"]
    result = [call.args[1] for call in emit.call_args_list if call.args[0] == "child_dialogue_result"][-1]
    assert result["error"] == "not_awake"
    assert "教师端" in result["hint"]


def test_teacher_can_wake_without_sound_and_toggle_child_panel(monkeypatch):
    app = Flask("dialogue-control")
    app.config.update(SECRET_KEY="test", TESTING=True)
    socketio = SocketIO(app, async_mode="threading")
    register_dialogue_events(socketio)
    registry = get_teacher_control_registry()
    registry.clear()
    teacher = socketio.test_client(app, flask_test_client=_http_teacher(app))
    monkeypatch.setattr(
        registry,
        "authorize",
        lambda *_args, **_kwargs: {"ok": True, "writable": True},
    )

    class Service:
        awake = False

        def set_awake(self, *_args):
            self.awake = True

    service = Service()
    monkeypatch.setattr("app.dialogue.sockets.get_dialogue_service", lambda: service)
    identity = {"trainingSessionId": "training-1", "sessionId": "runtime-1"}
    teacher.emit("teacher_dialogue_wake", identity)
    wake = _events(teacher, "teacher_dialogue_control_ack")[-1]
    assert wake["success"] is True
    assert wake["awake"] is True
    assert service.awake is True
    assert _events(teacher, "robot_speak_text") == []

    teacher.emit("teacher_dialogue_visibility", {**identity, "visible": False})
    hidden = _events(teacher, "teacher_dialogue_control_ack")[-1]
    assert hidden["success"] is True
    assert hidden["visible"] is False
    teacher.disconnect()
    registry.clear()


def test_runtime_modes_default_wake_word_is_disabled(tmp_path, monkeypatch):
    import app.runtime_modes as modes
    monkeypatch.setattr(modes, "_RUNTIME_PATH", tmp_path / "runtime_modes.yaml")
    monkeypatch.delenv("DIALOGUE_WAKE_WORD_ENABLED", raising=False)
    assert modes.load_runtime_modes()["dialogue_wake_word_enabled"] is False
    saved = modes.save_runtime_modes(dialogue_wake_word_enabled=True)
    assert saved["dialogue_wake_word_enabled"] is True
