from flask import Flask
from flask_socketio import SocketIO

from app.sockets.audio_events import register_audio_events
from app.sockets import events
from app.sockets.events import register_socket_events
from app.services.teacher_control import get_teacher_control_registry
from app.services.teacher_control import TeacherControlRegistry


def _received(client, event_name):
    return [
        item.get("args", [{}])[0]
        for item in client.get_received()
        if item.get("name") == event_name
    ]


def _authenticated_http_client(app, teacher_id, username):
    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["teacher_id"] = teacher_id
        flask_session["teacher_username"] = username
    return client


def test_new_training_replaces_same_teachers_old_control_lease():
    registry = TeacherControlRegistry()
    first = registry.claim(
        "training-old",
        teacher_id=101,
        teacher_username="teacher-a",
        sid="old-tab",
    )
    assert first["writable"] is True

    second = registry.claim(
        "training-new",
        teacher_id=101,
        teacher_username="teacher-a",
        sid="new-tab",
        replace_existing_for_teacher=True,
    )
    assert second["writable"] is True
    assert registry.authorize(
        "training-old", teacher_id=101, sid="old-tab"
    )["error"] == "control_lease_missing"
    assert registry.authorize(
        "training-new", teacher_id=101, sid="new-tab"
    )["writable"] is True


def test_teacher_registry_does_not_write_without_process_lock(tmp_path, monkeypatch):
    state = tmp_path / "teacher-leases.json"
    registry = TeacherControlRegistry(state_path=state)
    monkeypatch.setattr(registry._process_lock, "acquire", lambda **kwargs: False)

    try:
        registry.claim(
            "training-lock-failed",
            teacher_id=101,
            teacher_username="teacher-a",
            sid="tab-a",
        )
    except RuntimeError as error:
        assert str(error) == "teacher_control_temporarily_unavailable"
    else:
        raise AssertionError("claim unexpectedly continued without process lock")

    assert state.exists() is False


def test_authenticated_controller_and_read_only_observer(monkeypatch):
    app = Flask(__name__)
    app.config.update(SECRET_KEY="teacher-lease-test", TESTING=True)
    socketio = SocketIO(app, async_mode="threading")
    register_socket_events(socketio)
    register_audio_events(socketio)
    registry = get_teacher_control_registry()
    registry.clear()

    anonymous = socketio.test_client(app)
    teacher_a = socketio.test_client(
        app,
        flask_test_client=_authenticated_http_client(app, 101, "teacher-a"),
    )
    teacher_b = socketio.test_client(
        app,
        flask_test_client=_authenticated_http_client(app, 202, "teacher-b"),
    )
    child = socketio.test_client(app)
    identity = {
        "trainingSessionId": "training-lease-1",
        "sessionId": "runtime-lease-1",
    }

    anonymous.emit("join_session", {**identity, "role": "teacher"})
    anonymous_join = _received(anonymous, "joined_session")[-1]
    assert anonymous_join["status"] == "error"
    assert anonymous_join["error"] == "teacher_auth_required"

    teacher_a.emit("teacher_enter_control", identity)
    controller = _received(teacher_a, "teacher_control_state")[-1]
    assert controller["success"] is True
    assert controller["controlRole"] == "controller"
    assert controller["lease"]["ownerTeacherId"] == 101

    teacher_b.emit("teacher_enter_control", identity)
    observer = _received(teacher_b, "teacher_control_state")[-1]
    assert observer["success"] is False
    assert observer["controlRole"] == "observer"
    assert observer["lease"]["ownerTeacherId"] == 101

    teacher_b.emit("play_resource", {
        **identity,
        "requestId": "observer-play-1",
        "studentId": 1,
        "courseId": 1,
    })
    play_ack = _received(teacher_b, "play_resource_ack")[-1]
    assert play_ack["success"] is False
    assert play_ack["error"] == "observer_read_only"

    teacher_b.emit("teacher_rating_submit", {
        **identity,
        "requestId": "observer-rating-1",
        "questionId": "q1",
        "rating": 5,
    })
    rating_ack = _received(teacher_b, "teacher_rating_ack")[-1]
    assert rating_ack["success"] is False
    assert rating_ack["error"] == "observer_read_only"

    teacher_b.emit("stop_audio", {
        **identity,
        "session_id": identity["sessionId"],
        "immediate": True,
    })
    stop_ack = _received(teacher_b, "stop_audio_ack")[-1]
    assert stop_ack["success"] is False
    assert stop_ack["error"] == "observer_read_only"

    teacher_a.emit("join_session", {**identity, "role": "teacher"})
    assert _received(teacher_a, "joined_session")[-1]["status"] == "ok"
    child_sid = _received(child, "connected")[-1]["sid"]
    events._touch_presence("child", child_sid)
    with events._presence_lock:
        events._child_session_owners[identity["sessionId"]] = child_sid
        events._child_sid_bindings[child_sid] = {
            **identity,
            "studentId": 1,
        }
    with events._play_request_lock:
        events._play_request_cache["animation-request-1"] = {
            "behaviorId": "animation-behavior-1",
            "expiresAt": 10**12,
        }

    class _Robot:
        def mark_behavior_animation_complete(self, **kwargs):
            return {
                "behaviorId": kwargs["behavior_id"],
                "status": kwargs["status"],
                "degraded": False,
            }

    monkeypatch.setattr("app.robot.get_robot_service", lambda: _Robot())
    animation_terminal = {
        **identity,
        "requestId": "animation-request-1",
        "behaviorId": "animation-behavior-1",
        "status": "ended",
    }
    teacher_b.emit("behavior_animation_ended", animation_terminal)
    assert _received(teacher_a, "behavior_animation_ended") == []

    child.emit("behavior_animation_ended", animation_terminal)
    forwarded = _received(teacher_a, "behavior_animation_ended")[-1]
    assert forwarded["requestId"] == "animation-request-1"
    assert forwarded["degraded"] is False

    anonymous.disconnect()
    teacher_a.disconnect()
    teacher_b.disconnect()
    child.disconnect()
    registry.clear()
    with events._presence_lock:
        events._child_session_owners.clear()
        events._child_sid_bindings.clear()
    with events._play_request_lock:
        events._play_request_cache.clear()


def test_readiness_start_recovers_missing_or_reconnected_teacher_lease(monkeypatch):
    class _Readiness:
        def __init__(self):
            self.starts = []

        def set_emitter(self, *args):
            pass

        def set_capture_start_callback(self, *args):
            pass

        def set_device_preflight_callback(self, *args):
            pass

        def set_child_emitter(self, *args):
            pass

        def start(self, sid, data):
            self.starts.append((sid, dict(data)))
            return {
                "success": True,
                "trainingSessionId": data["trainingSessionId"],
                "studentId": data["studentId"],
                "ok": False,
                "modules": [],
                "progress01": 0.0,
                "plan": {},
            }

        def force_enter(self, training_session_id, *, teacher_sid, reason=""):
            return {
                "success": True,
                "forced": True,
                "snapshot": {"trainingSessionId": training_session_id},
            }

    readiness = _Readiness()
    monkeypatch.setattr(events, "get_readiness_service", lambda: readiness)
    app = Flask(__name__)
    app.config.update(SECRET_KEY="teacher-lease-recovery", TESTING=True)
    socketio = SocketIO(app, async_mode="threading")
    registry = get_teacher_control_registry()
    registry.clear()
    register_socket_events(socketio)
    payload = {
        "studentId": 1,
        "trainingSessionId": "training-recover-1",
        "items": [{"courseId": 1, "itemId": 1}],
    }

    first = socketio.test_client(
        app,
        flask_test_client=_authenticated_http_client(app, 303, "teacher-recover"),
    )
    first.get_received()
    # No prepare-time lease exists (for example after a backend restart).
    first.emit("readiness_start", payload)
    assert _received(first, "readiness_start_ack")[-1]["success"] is True
    first.disconnect()

    second = socketio.test_client(
        app,
        flask_test_client=_authenticated_http_client(app, 303, "teacher-recover"),
    )
    second.get_received()
    # The same teacher receives a new Socket SID and rebinds atomically.
    second.emit("readiness_start", payload)
    assert _received(second, "readiness_start_ack")[-1]["success"] is True
    second.emit("readiness_force_enter", {
        **payload,
        "requestId": "force-recover-1",
        "reason": "test override",
    })
    forced = _received(second, "readiness_force_enter_ack")[-1]
    assert forced["success"] is True
    assert forced["forced"] is True
    assert forced["requestId"] == "force-recover-1"

    observer = socketio.test_client(
        app,
        flask_test_client=_authenticated_http_client(app, 404, "teacher-observer"),
    )
    observer.get_received()
    observer.emit("readiness_start", payload)
    denied = _received(observer, "readiness_start_ack")[-1]
    assert denied["success"] is False
    assert denied["error"] == "observer_read_only"
    assert len(readiness.starts) == 2

    second.disconnect()
    observer.disconnect()
    registry.clear()


def test_teacher_leave_control_finalizes_even_without_behavior_idle(monkeypatch):
    finalized = []
    monkeypatch.setattr(
        events.FinalizeTrainingHandler,
        "handle",
        staticmethod(
            lambda payload: finalized.append(dict(payload)) or {
                "success": True,
                "trainingSessionId": payload["trainingSessionId"],
                "stoppedRuntimeSessions": ["media-leave-1"],
                "status": "FINALIZED",
            }
        ),
    )
    app = Flask(__name__)
    app.config.update(SECRET_KEY="teacher-leave-test", TESTING=True)
    socketio = SocketIO(app, async_mode="threading")
    registry = get_teacher_control_registry()
    registry.clear()
    register_socket_events(socketio)
    teacher = socketio.test_client(
        app,
        flask_test_client=_authenticated_http_client(app, 505, "teacher-leave"),
    )
    teacher.get_received()
    payload = {
        "studentId": 1,
        "trainingSessionId": "training-leave-1",
        "sessionId": "media-leave-1",
    }
    teacher.emit("teacher_enter_control", payload)
    _received(teacher, "teacher_control_state")

    teacher.emit("teacher_leave_control", payload)
    ack = _received(teacher, "teacher_leave_control_ack")[-1]

    assert ack["success"] is True
    assert finalized[0]["operationId"] == "teacher-leave:training-leave-1"
    assert registry.authorize(
        "training-leave-1", teacher_id=505, sid=teacher.eio_sid
    )["error"] == "control_lease_missing"
    teacher.disconnect()
    registry.clear()
