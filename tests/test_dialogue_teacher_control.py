from unittest.mock import patch
from pathlib import Path

from flask import Flask
from flask_socketio import SocketIO

from app.config import Config
import pytest

from app.dialogue.sockets import (
    _handle_dialogue_utterance,
    _resolve_manual_wake_target,
    register_dialogue_events,
)
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

        def clear_awake(self, *_args):
            self.awake = False

        def is_session_awake(self, *_args):
            return self.awake

    service = Service()
    monkeypatch.setattr("app.dialogue.sockets.get_dialogue_service", lambda: service)
    monkeypatch.setattr(
        "app.dialogue.sockets._resolve_manual_wake_target",
        lambda _data: {
            "ok": True,
            "sessionId": "runtime-1",
            "trainingSessionId": "training-1",
            "childSid": "child-1",
        },
    )
    identity = {"trainingSessionId": "training-1", "sessionId": "runtime-1"}
    teacher.emit("teacher_dialogue_wake", {**identity, "requestId": "wake-1"})
    wake = _events(teacher, "teacher_dialogue_control_ack")[-1]
    assert wake["success"] is True
    assert wake["awake"] is True
    assert wake["requestId"] == "wake-1"
    assert service.awake is True
    assert _events(teacher, "robot_speak_text") == []

    teacher.emit("teacher_dialogue_sleep", {**identity, "requestId": "sleep-1"})
    sleep = _events(teacher, "teacher_dialogue_control_ack")[-1]
    assert sleep["success"] is True
    assert sleep["action"] == "sleep"
    assert sleep["awake"] is False
    assert sleep["requestId"] == "sleep-1"
    assert service.awake is False

    teacher.emit(
        "teacher_dialogue_visibility",
        {**identity, "visible": False, "requestId": "visibility-1"},
    )
    hidden = _events(teacher, "teacher_dialogue_control_ack")[-1]
    assert hidden["success"] is True
    assert hidden["visible"] is False
    assert hidden["requestId"] == "visibility-1"
    teacher.disconnect()
    registry.clear()


def test_runtime_modes_default_wake_word_is_disabled(tmp_path, monkeypatch):
    import app.runtime_modes as modes
    monkeypatch.setattr(modes, "_RUNTIME_PATH", tmp_path / "runtime_modes.yaml")
    monkeypatch.delenv("DIALOGUE_WAKE_WORD_ENABLED", raising=False)
    assert modes.load_runtime_modes()["dialogue_wake_word_enabled"] is False
    assert modes.load_runtime_modes()["browser_speech_rate"] == 0.88
    saved = modes.save_runtime_modes(dialogue_wake_word_enabled=True)
    assert saved["dialogue_wake_word_enabled"] is True
    saved = modes.save_runtime_modes(browser_speech_rate=1.15)
    assert saved["browser_speech_rate"] == 1.15
    assert modes.load_runtime_modes()["browser_speech_rate"] == 1.15
    with pytest.raises(ValueError, match="0.5 到 2.0"):
        modes.save_runtime_modes(browser_speech_rate=2.5)


def test_manual_wake_target_requires_active_exact_course_and_child(monkeypatch):
    class Runtime:
        training_session_id = "training-1"
        course_id = 7
        metadata = {"course_type": "naming"}

        @staticmethod
        def is_active():
            return True

    class Manager:
        @staticmethod
        def get_session(session_id):
            return Runtime() if session_id == "runtime-1" else None

    monkeypatch.setattr("app.session.get_session_manager", lambda: Manager())
    monkeypatch.setattr(
        "app.sockets.events.get_connected_child_sid",
        lambda session_id: "child-sid" if session_id == "runtime-1" else None,
    )

    resolved = _resolve_manual_wake_target({
        "sessionId": "runtime-1",
        "trainingSessionId": "training-1",
    })
    assert resolved["ok"] is True
    assert resolved["childSid"] == "child-sid"
    mismatch = _resolve_manual_wake_target({
        "sessionId": "runtime-1",
        "trainingSessionId": "some-other-training",
    })
    assert mismatch == {"ok": False, "error": "session_mismatch"}


def test_manual_wake_target_reports_child_offline(monkeypatch):
    class Runtime:
        training_session_id = "training-1"
        course_id = 7
        metadata = {"course_type": "naming"}

        @staticmethod
        def is_active():
            return True

    monkeypatch.setattr(
        "app.session.get_session_manager",
        lambda: type("Manager", (), {"get_session": staticmethod(lambda _sid: Runtime())})(),
    )
    monkeypatch.setattr("app.sockets.events.get_connected_child_sid", lambda _sid: None)
    assert _resolve_manual_wake_target({"sessionId": "runtime-1"}) == {
        "ok": False,
        "error": "child_not_connected",
    }


def test_child_dialogue_surface_is_server_only_without_legacy_panel():
    root = Path(__file__).resolve().parents[1]
    script = (root / "static/js/child_dialogue.js").read_text(encoding="utf-8")
    template = (root / "templates/child.html").read_text(encoding="utf-8")

    assert 'document.getElementById("dialoguePanel")' not in script
    assert 'id="dialoguePanel"' not in template
    assert "可见对话日志已经迁移到 Server 房间" in script


def test_teacher_agent_toggle_and_visibility_are_not_lease_gated_and_have_watchdogs():
    root = Path(__file__).resolve().parents[1]
    teacher = (root / "teacher_frontend/components/ControlPage.tsx").read_text(encoding="utf-8")
    sockets = (root / "app/dialogue/sockets.py").read_text(encoding="utf-8")
    wake_handler = sockets.split('@socketio.on("teacher_dialogue_wake")', 1)[1].split(
        '@socketio.on("teacher_dialogue_sleep")', 1
    )[0]
    sleep_handler = sockets.split('@socketio.on("teacher_dialogue_sleep")', 1)[1].split(
        '@socketio.on("teacher_dialogue_visibility")', 1
    )[0]
    visibility_handler = sockets.split('@socketio.on("teacher_dialogue_visibility")', 1)[1].split(
        '@socketio.on("child_dialogue_control_state_request")', 1
    )[0]

    assert "_authorize_teacher_control" not in wake_handler
    assert "_authorize_teacher_control" not in sleep_handler
    assert "_authorize_teacher_control" not in visibility_handler
    assert "_resolve_manual_wake_target" in wake_handler
    assert "_resolve_manual_wake_target" in sleep_handler
    assert "_resolve_manual_wake_target" in visibility_handler
    assert '"requestId": request_id' in wake_handler
    assert "teacher_dialogue_sleep" in teacher
    assert "{dialogueAwake ? '关闭智能体' : '唤醒智能体'}" in teacher
    assert "teacher_dialogue_runtime_state" in teacher
    assert "}, 4000);" in teacher
    assert "child_not_connected" in teacher
    assert "disabled={dialogueControlBusy || !socketConnected || !currentSessionId}" in teacher


def test_child_wake_restarts_listening_and_reports_runtime_state():
    root = Path(__file__).resolve().parents[1]
    child = (root / "static/js/child_dialogue.js").read_text(encoding="utf-8")

    wake_handler = child.split('socket.on("child_dialogue_wake_state"', 1)[1].split(
        'socket.on("child_dialogue_visibility"', 1
    )[0]
    assert "ensureListeningAfterTeacherWake" in wake_handler
    assert 'socket.emit("child_dialogue_runtime_state"' in child
    assert "microphoneBlocked" in child
    assert "lastPageFingerprint = pageContextFingerprint(buildPageContext())" in child


def test_child_dialogue_carries_the_committed_question_identity_after_teacher_wake():
    root = Path(__file__).resolve().parents[1]
    child = (root / "static/js/child_dialogue.js").read_text(encoding="utf-8")
    parent = (root / "static/js/child.js").read_text(encoding="utf-8")

    assert "questionId: global.currentQuestionId || null" in child
    assert "window.currentQuestionId = currentQuestionId" in parent


def test_awake_state_persists_across_multiple_dialogue_turns_on_same_question():
    from app.dialogue.service import DialogueService

    svc = DialogueService.__new__(DialogueService)
    svc._history = {}
    svc._context_fp = {}
    svc._awake_fp = {}
    svc.provider = "rule"
    svc.api_key = ""
    context = {
        "courseType": "naming",
        "courseId": 2,
        "itemId": 201,
        "questionId": "question-2-201",
        "target": "小猫",
    }

    svc.set_awake("manual-wake-session", context)
    first = svc.generate_reply("你好", session_id="manual-wake-session", page_context=context)
    second = svc.generate_reply("你是谁", session_id="manual-wake-session", page_context=context)

    assert first["reply"]
    assert second["reply"]
    assert svc.is_session_awake("manual-wake-session", context) is True
