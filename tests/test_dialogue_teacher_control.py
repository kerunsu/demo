from unittest.mock import patch
from pathlib import Path

from flask import Flask
from flask_socketio import SocketIO

from app.config import Config
from app.dialogue.voice_config import FIXED_BROWSER_TTS_VOICE_NAME
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

        def set_awake(self, *_args, **_kwargs):
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
            "childRoom": "child:runtime-1",
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
    assert "_resolve_dialogue_target" in wake_handler
    assert "allow_standby=True" in wake_handler
    assert "_resolve_dialogue_target" in sleep_handler
    assert "allow_standby=True" in sleep_handler
    assert "_resolve_manual_wake_target" in visibility_handler
    assert '"requestId": request_id' in wake_handler
    assert "teacher_dialogue_sleep" in teacher
    assert "{dialogueAwake ? '停止智能体' : '唤醒智能体'}" in teacher
    assert "teacher_dialogue_runtime_state" in teacher
    assert "}, 4000);" in teacher
    assert "child_not_connected" in teacher
    assert "dialogueTargetSessionRef" in teacher
    assert "currentSessionIdRef.current || (" in teacher
    assert "dialogueAwake ? dialogueTargetSessionRef.current : null" in teacher
    assert "disabled={dialogueControlBusy || !socketConnected || (!currentSessionId && !dialogueAwake)}" in teacher


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


def test_dialogue_turn_dedupe_rejects_request_replay_and_browser_double_final():
    from app.dialogue.sockets import (
        _claim_dialogue_turn,
        _dialogue_recent_transcripts,
        _dialogue_turn_requests,
    )

    _dialogue_turn_requests.clear()
    _dialogue_recent_transcripts.clear()
    context = {"courseType": "pairing", "courseId": 9, "questionId": "q-1"}
    assert _claim_dialogue_turn(
        "dedupe-session",
        "request-1",
        "答案在哪里",
        context,
        recognition_provider="browser-speech-recognition",
    ) is None
    assert _claim_dialogue_turn(
        "dedupe-session",
        "request-1",
        "答案在哪里",
        context,
        recognition_provider="browser-speech-recognition",
    ) == "duplicate_request"
    assert _claim_dialogue_turn(
        "dedupe-session",
        "request-2",
        "答案在哪里！",
        context,
        recognition_provider="browser-speech-recognition",
    ) == "duplicate_transcript"


def test_teacher_stop_invalidates_queued_and_active_dialogue_reply(monkeypatch):
    from app.dialogue import sockets

    session_id = "stop-reply-session"
    aborted = []

    class Robot:
        def abort_behavior(self, behavior_id):
            aborted.append(behavior_id)
            return True

    monkeypatch.setattr("app.robot.get_robot_service", lambda: Robot())
    sockets._dialogue_reply_generations[session_id] = 3
    sockets._active_dialogue_reply_behaviors[session_id] = "dialogue-active-1"
    sockets._pending_dialogue_speak[session_id] = {
        "text": "稍后播放的旧回复",
        "dialogue_request_id": "turn-pending-1",
        "queued_at": 0,
    }

    result = sockets._cancel_dialogue_replies(
        session_id,
        reason="teacher_manual_stop",
    )

    assert result == {
        "generation": 4,
        "pendingCancelled": True,
        "activeCancelled": True,
    }
    assert aborted == ["dialogue-active-1"]
    assert session_id not in sockets._pending_dialogue_speak
    assert session_id not in sockets._active_dialogue_reply_behaviors


def test_server_dialogue_watch_and_runtime_control_are_exact_session_scoped(monkeypatch):
    app = Flask("server-dialogue-control")
    app.config.update(SECRET_KEY="test", TESTING=True)
    socketio = SocketIO(app, async_mode="threading")
    register_dialogue_events(socketio)
    monitor = socketio.test_client(app)
    child = socketio.test_client(app)
    unrelated = socketio.test_client(app)
    child_sid = socketio.server.manager.sid_from_eio_sid(child.eio_sid, "/")
    unrelated_sid = socketio.server.manager.sid_from_eio_sid(unrelated.eio_sid, "/")
    socketio.server.enter_room(child_sid, "session_runtime-1_child", namespace="/")
    socketio.server.enter_room(unrelated_sid, "session_other-child_child", namespace="/")

    monkeypatch.setattr(
        "app.dialogue.sockets._resolve_dialogue_target",
        lambda _data, **_kwargs: {
            "ok": True,
            "sessionId": "runtime-1",
            "trainingSessionId": "training-1",
            "childSid": child_sid,
            "childRoom": "session_runtime-1_child",
            "standby": False,
        },
    )
    monkeypatch.setattr(
        "app.sockets.events.get_connected_child_sid",
        lambda _session_id: child_sid,
    )

    class Service:
        @staticmethod
        def is_session_awake(*_args):
            return False

        @staticmethod
        def bind_pending_awake_context(*_args):
            return False

    monkeypatch.setattr("app.dialogue.sockets.get_dialogue_service", lambda: Service())
    from app.dialogue.sockets import _dialogue_visible_messages

    _dialogue_visible_messages["runtime-1"] = [{
        "type": "message",
        "sessionId": "runtime-1",
        "role": "child",
        "text": "监控页打开前说的话",
        "requestId": "before-watch",
        "serverTimestamp": 1,
    }]

    monitor.emit("server_dialogue_watch", {
        "sessionId": "runtime-1",
        "trainingSessionId": "training-1",
        "requestId": "watch-1",
    })
    watch = _events(monitor, "server_dialogue_control_ack")[-1]
    assert watch["success"] is True
    assert watch["messages"][0]["text"] == "监控页打开前说的话"
    state_request = _events(child, "child_dialogue_runtime_control")[-1]
    assert state_request["action"] == "state_request"
    assert state_request["requestId"] == "watch-1"

    monitor.emit("server_dialogue_runtime_control", {
        "sessionId": "runtime-1",
        "trainingSessionId": "training-1",
        "requestId": "listen-1",
        "action": "listen_start",
    })
    child_control = _events(child, "child_dialogue_runtime_control")[-1]
    assert child_control["action"] == "listen_start"
    assert child_control["requestId"] == "listen-1"
    assert _events(unrelated, "child_dialogue_runtime_control") == []

    child.emit("child_dialogue_runtime_state", {
        "sessionId": "runtime-1",
        "awake": False,
        "listening": True,
        "recognitionActive": True,
        "microphoneBlocked": False,
        "voices": [
            {"name": "other-voice", "lang": "zh-CN", "label": "其他音色"},
            {
                "name": FIXED_BROWSER_TTS_VOICE_NAME,
                "lang": "zh-CN",
                "label": FIXED_BROWSER_TTS_VOICE_NAME,
            },
        ],
        "selectedVoice": FIXED_BROWSER_TTS_VOICE_NAME,
        "voiceAvailable": True,
    })
    mirrored = _events(monitor, "server_dialogue_event")[-1]
    assert mirrored["type"] == "runtime"
    assert mirrored["voices"] == [{
        "name": FIXED_BROWSER_TTS_VOICE_NAME,
        "lang": "zh-CN",
        "label": FIXED_BROWSER_TTS_VOICE_NAME,
    }]
    assert mirrored["voiceAvailable"] is True
    assert _events(unrelated, "server_dialogue_event") == []

    monitor.disconnect()
    child.disconnect()
    unrelated.disconnect()
    _dialogue_visible_messages.pop("runtime-1", None)


def test_server_dialogue_standby_supports_voice_and_text_without_course(monkeypatch):
    app = Flask("server-dialogue-standby")
    app.config.update(SECRET_KEY="test", TESTING=True)
    socketio = SocketIO(app, async_mode="threading")
    register_dialogue_events(socketio)
    monitor = socketio.test_client(app)
    child = socketio.test_client(app)
    unrelated = socketio.test_client(app)
    child_sid = socketio.server.manager.sid_from_eio_sid(child.eio_sid, "/")

    from app.sockets import events as socket_events

    with socket_events._presence_lock:
        socket_events._presence_state["child"].clear()
        socket_events._presence_details["child"].clear()
        socket_events._child_sid_bindings.clear()
        socket_events._child_session_owners.clear()
    socket_events._touch_presence("child", child_sid, details={"ip": "127.0.0.1"})

    turns = []
    monkeypatch.setattr(
        "app.dialogue.sockets._handle_dialogue_utterance",
        lambda **kwargs: turns.append(kwargs),
    )

    monitor.emit("server_dialogue_watch", {"requestId": "standby-watch"})
    watch = _events(monitor, "server_dialogue_control_ack")[-1]
    assert watch["success"] is True
    assert watch["standby"] is True
    standby_session = watch["sessionId"]
    assert standby_session.startswith("dialogue-standby-")
    assert socket_events.get_connected_child_sid(standby_session) == child_sid
    state_request = _events(child, "child_dialogue_runtime_control")[-1]
    assert state_request["action"] == "state_request"
    assert _events(unrelated, "child_dialogue_runtime_control") == []

    monitor.emit("server_dialogue_runtime_control", {
        "sessionId": standby_session,
        "requestId": "voice-change-rejected",
        "action": "set_voice",
        "voiceName": "Microsoft Xiaoxiao Online (Natural) - Chinese (Mainland)",
    })
    rejected = _events(monitor, "server_dialogue_control_ack")[-1]
    assert rejected["success"] is False
    assert rejected["error"] == "voice_locked"
    assert rejected["fixedVoiceName"] == FIXED_BROWSER_TTS_VOICE_NAME
    assert _events(child, "child_dialogue_runtime_control") == []

    monitor.emit("server_dialogue_text", {
        "sessionId": standby_session,
        "requestId": "standby-text",
        "text": "你好",
    })
    text_ack = _events(monitor, "server_dialogue_control_ack")[-1]
    assert text_ack["success"] is True
    assert text_ack["action"] == "text"
    assert turns[-1]["session_id"] == standby_session
    assert turns[-1]["room"] == f"session_{standby_session}_child"

    monitor.disconnect()
    child.disconnect()
    unrelated.disconnect()
    with socket_events._presence_lock:
        socket_events._presence_state["child"].clear()
        socket_events._presence_details["child"].clear()
        socket_events._child_sid_bindings.clear()
        socket_events._child_session_owners.clear()


def test_server_dialogue_standby_refuses_ambiguous_children():
    app = Flask("server-dialogue-standby-ambiguous")
    app.config.update(SECRET_KEY="test", TESTING=True)
    socketio = SocketIO(app, async_mode="threading")
    register_dialogue_events(socketio)
    monitor = socketio.test_client(app)
    first_child = socketio.test_client(app)
    second_child = socketio.test_client(app)
    first_sid = socketio.server.manager.sid_from_eio_sid(first_child.eio_sid, "/")
    second_sid = socketio.server.manager.sid_from_eio_sid(second_child.eio_sid, "/")

    from app.sockets import events as socket_events

    with socket_events._presence_lock:
        socket_events._presence_state["child"].clear()
        socket_events._presence_details["child"].clear()
        socket_events._child_sid_bindings.clear()
        socket_events._child_session_owners.clear()
    socket_events._touch_presence("child", first_sid)
    socket_events._touch_presence("child", second_sid)

    monitor.emit("server_dialogue_watch", {"requestId": "ambiguous-watch"})
    watch = _events(monitor, "server_dialogue_control_ack")[-1]
    assert watch["success"] is False
    assert watch["error"] == "ambiguous_children"
    assert _events(first_child, "child_dialogue_runtime_control") == []
    assert _events(second_child, "child_dialogue_runtime_control") == []

    monitor.disconnect()
    first_child.disconnect()
    second_child.disconnect()
    with socket_events._presence_lock:
        socket_events._presence_state["child"].clear()
        socket_events._presence_details["child"].clear()
        socket_events._child_sid_bindings.clear()
        socket_events._child_session_owners.clear()
