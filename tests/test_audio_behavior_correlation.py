from app.audio.controller import AudioController
from app.audio.events import AudioEventEmitter
from app.audio.models import AudioStatus


class _Socket:
    def __init__(self):
        self.emitted = []

    def emit(self, event, payload, room=None, broadcast=False):
        self.emitted.append({
            "event": event,
            "payload": payload,
            "room": room,
            "broadcast": broadcast,
        })


class _Selector:
    def select(self, entry_id, context=None, file_type="files"):
        return "resources/audio/praise.mp3"


def test_file_audio_payload_carries_request_and_behavior_ids():
    socket = _Socket()
    emitter = AudioEventEmitter(socket, _Selector())

    assert emitter.emit_audio(
        room="session_s1_child",
        entry_id="praise",
        behavior_id="behavior-1",
        request_id="request-1",
    )

    payload = socket.emitted[0]["payload"]
    assert payload["behaviorId"] == "behavior-1"
    assert payload["behavior_id"] == "behavior-1"
    assert payload["interactionId"] == "behavior-1"
    assert payload["requestId"] == "request-1"
    assert payload["request_id"] == "request-1"
    assert payload["sessionId"] == "s1"
    assert payload["session_id"] == "s1"


def test_file_audio_empty_room_is_rejected_without_broadcast():
    class _EmptyManager:
        @staticmethod
        def get_participants(namespace, room):
            return iter(())

    socket = _Socket()
    socket.server = type("Server", (), {"manager": _EmptyManager()})()
    emitter = AudioEventEmitter(socket, _Selector())

    assert not emitter.emit_audio(
        room="session_not_joined_child",
        entry_id="praise",
        behavior_id="behavior-fallback",
    )
    assert socket.emitted == []


def test_audio_controller_accepts_snake_case_status_aliases(monkeypatch):
    socket = _Socket()
    controller = AudioController(socket)
    completed = []

    class _Robot:
        def mark_behavior_audio_complete(self, **kwargs):
            completed.append(kwargs)
            return "behavior-current"

    import app.robot

    monkeypatch.setattr(app.robot, "get_robot_service", lambda: _Robot())
    payload = {
        "state": "finished",
        "entry_id": "praise",
        "file_path": "resources/audio/praise.mp3",
        "behavior_id": "behavior-current",
    }
    result = controller.on_audio_status("session-1", payload)

    assert result.status == AudioStatus.ENDED
    assert result.current_audio_id == "praise"
    assert result.current_file == "resources/audio/praise.mp3"
    assert payload["behaviorId"] == "behavior-current"
    assert completed[0]["session_id"] == "session-1"


def test_audio_controller_does_not_release_without_behavior_id(monkeypatch):
    socket = _Socket()
    controller = AudioController(socket)
    completed = []

    class _Robot:
        def mark_behavior_audio_complete(self, **kwargs):
            completed.append(kwargs)
            return "must-not-run"

    import app.robot

    monkeypatch.setattr(app.robot, "get_robot_service", lambda: _Robot())
    result = controller.on_audio_status(
        "session-1",
        {
            "status": "ended",
            "entry_id": "legacy",
            "file_path": "resources/audio/legacy.mp3",
        },
    )

    assert result.status == AudioStatus.ENDED
    assert completed == []


def test_audio_controller_ignores_unknown_status(monkeypatch):
    socket = _Socket()
    controller = AudioController(socket)

    result = controller.on_audio_status(
        "session-1",
        {
            "status": "loaded",
            "behaviorId": "behavior-current",
        },
    )

    assert result is None
