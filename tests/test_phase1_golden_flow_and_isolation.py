"""第一阶段：黄金主流程、房间隔离和行为互斥的 characterization tests。"""

import os
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture(scope="module")
def phase1_socket_runtime():
    old = {
        key: os.environ.get(key)
        for key in ("START_TEACHER_FRONTEND", "START_VOICE_SERVICE", "DIALOGUE_ENABLED")
    }
    os.environ["START_TEACHER_FRONTEND"] = "0"
    os.environ["START_VOICE_SERVICE"] = "0"
    os.environ["DIALOGUE_ENABLED"] = "0"
    try:
        yield runpy.run_path("app.py", run_name="phase1_socket_runtime")
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _events(runtime, client):
    return [item for item in client.get_received() if item.get("name")]


def _event_names(runtime, client):
    return [item["name"] for item in _events(runtime, client)]


def _authenticated_socket(runtime, teacher_id, username=None):
    http = runtime["app"].test_client()
    with http.session_transaction() as flask_session:
        flask_session["teacher_id"] = teacher_id
        flask_session["teacher_username"] = username or f"teacher-{teacher_id}"
    return runtime["socketio"].test_client(
        runtime["app"],
        flask_test_client=http,
    )


def _prepare_test_dependencies(monkeypatch, tmp_path, student_id):
    import app.behavior as behavior_package
    from app.behavior.service import BehaviorService
    from app.behavior.store import BehaviorStore
    from app.behavior.timeline import BehaviorTimeline
    from app.services import recording_timeline as timeline
    from app.session import get_session_manager
    from app.sockets import handlers as handlers_mod

    manager = get_session_manager()
    for session in list(manager.get_sessions_by_student(student_id)):
        manager.remove_session(session.session_id)

    behavior = BehaviorService()
    behavior.store = BehaviorStore(tmp_path / "behavior")
    behavior.timeline = BehaviorTimeline(behavior.store)
    monkeypatch.setattr(handlers_mod, "get_behavior_service", lambda: behavior)
    monkeypatch.setattr(behavior_package, "get_behavior_service", lambda: behavior)
    monkeypatch.setattr(
        handlers_mod,
        "load_student_label",
        lambda _student_id: (f"phase1-student-{student_id}", 6),
    )
    monkeypatch.setattr(handlers_mod, "resolve_course_type_id", lambda _course_id: 1)
    monkeypatch.setattr(
        handlers_mod.PlayResourceHandler,
        "_resolve_course_type",
        staticmethod(lambda _course_id, fallback="default": "naming"),
    )
    monkeypatch.setattr(timeline, "sessions_root", lambda: tmp_path / "sessions")

    calls = {"media_start": [], "media_stop": [], "analysis_start": [], "analysis_end": [], "reconfigure": []}

    class Media:
        def start_recording(self, session_id, *args, **kwargs):
            calls["media_start"].append(session_id)
            return True

        def stop_recording(self, session_id, *args, **kwargs):
            calls["media_stop"].append(session_id)
            return True

    class Analysis:
        def start_session(self, session_id, *args, **kwargs):
            calls["analysis_start"].append(session_id)
            return True

        def end_session(self, session_id, *args, **kwargs):
            calls["analysis_end"].append(session_id)

        def reconfigure_session(self, session_id, *args, **kwargs):
            calls["reconfigure"].append(session_id)
            return True

        def set_speech_target(self, *args, **kwargs):
            return True

        def set_pose_target_from_path(self, *args, **kwargs):
            return True

    monkeypatch.setattr(handlers_mod, "get_media_service", lambda: Media())
    monkeypatch.setattr(handlers_mod, "get_analysis_service", lambda: Analysis())
    return behavior, manager, calls


def test_phase1_golden_flow_freezes_current_warmup_and_continuous_recording(
    monkeypatch, tmp_path, phase1_socket_runtime
):
    runtime = phase1_socket_runtime
    from app.routes import config_content as config_content_mod
    from app.routes import report as report_routes
    from app.services import recording_timeline as timeline
    from app.services import readiness_service as readiness_mod
    from app.sockets import events as events_mod

    student_id = 99101
    behavior, manager, calls = _prepare_test_dependencies(monkeypatch, tmp_path, student_id)

    # Freeze the HTTP entry steps that precede the socket training workflow.
    # Database access is isolated, but the real Flask routes and envelopes run.
    class Query:
        def __init__(self, rows):
            self.rows = rows

        def filter_by(self, **_kwargs):
            return self

        def first(self):
            return self.rows[0] if self.rows else None

        def order_by(self, *_args):
            return self

        def all(self):
            return self.rows

    teacher_row = SimpleNamespace(
        id=7,
        username="phase1-teacher",
        is_active=True,
        last_login=None,
        check_password=lambda password: password == "phase1-password",
        to_dict=lambda: {"id": 7, "username": "phase1-teacher"},
    )
    student_row = SimpleNamespace(
        to_dict=lambda: {"id": student_id, "name": "phase1-student"}
    )
    root_globals = runtime["app"].view_functions["teacher_login"].__globals__
    monkeypatch.setitem(root_globals, "Teacher", SimpleNamespace(query=Query([teacher_row])))
    monkeypatch.setitem(
        root_globals,
        "Student",
        SimpleNamespace(
            query=Query([student_row]),
            created_at=SimpleNamespace(desc=lambda: object()),
        ),
    )
    monkeypatch.setitem(
        root_globals,
        "db",
        SimpleNamespace(session=SimpleNamespace(commit=lambda: None)),
    )
    course_row = SimpleNamespace(id=1)
    monkeypatch.setattr(
        config_content_mod,
        "Course",
        SimpleNamespace(query=Query([course_row]), id=object()),
    )
    monkeypatch.setattr(config_content_mod, "_load_course_map", lambda: {})
    monkeypatch.setattr(config_content_mod, "_course_ids_with_mapping", lambda _mapping: set())
    monkeypatch.setattr(
        config_content_mod,
        "_course_admin_dict",
        lambda _course, _mapped: {"id": 7, "title": "Naming", "type": "naming"},
    )
    http = runtime["app"].test_client()
    login = http.post(
        "/api/teacher/login",
        json={"username": "phase1-teacher", "password": "phase1-password"},
    )
    assert login.status_code == 200 and login.get_json()["success"] is True
    students = http.get("/api/students")
    assert students.status_code == 200
    assert students.get_json()["students"][0]["id"] == student_id
    courses = http.get("/api/config/courses")
    assert courses.status_code == 200
    assert courses.get_json()["courses"][0]["type"] == "naming"

    # The class-start barrier owns only formal recording and server video
    # evidence. Resource, audio and analyzer checks are not part of this path.
    readiness = readiness_mod.ReadinessService()
    readiness.set_emitter(lambda *_args, **_kwargs: None)
    monkeypatch.setattr(readiness, "_schedule_poll", lambda _gate: None)
    monkeypatch.setattr(readiness, "_schedule_timeout", lambda _gate: None)
    readiness.set_capture_start_callback(
        lambda training_id: {
            "ok": True,
            "sessionId": next(
                session.session_id
                for session in manager.list_all_sessions()
                if session.training_session_id == training_id
            ),
        }
    )
    capture_results = []
    real_check_capture = readiness.check_capture

    def record_capture(*args, **kwargs):
        result = real_check_capture(*args, **kwargs)
        capture_results.append(result)
        return result

    monkeypatch.setattr(readiness, "check_capture", record_capture)

    class Robot:
        def reserve_behavior(self, behavior_id=None, request_id=None, **kwargs):
            return {"accepted": True, "behaviorId": behavior_id or "phase1-behavior"}

        def abort_behavior(self, _behavior_id):
            return None

        def set_behavior_audio_expected(self, *_args, **_kwargs):
            return True

        def set_behavior_animation_expected(self, *_args, **_kwargs):
            return True

        def get_behavior_busy_state(self):
            return {"busy": False, "eventId": None, "remainingMs": 0}

    monkeypatch.setattr(events_mod, "get_readiness_service", lambda: readiness)
    monkeypatch.setattr(events_mod, "_assign_child_for_identity", lambda *args, **kwargs: (None, "child_offline"))
    monkeypatch.setattr(events_mod, "_resource_ready_support_for_identity", lambda *args, **kwargs: True)
    monkeypatch.setattr(events_mod, "_start_or_defer_course_behavior", lambda *args, **kwargs: {"success": True, "skipped": True})
    monkeypatch.setattr("app.robot.get_robot_service", lambda: Robot())

    class Audio:
        def process_play_resource(self, *args, **kwargs):
            return {"triggered": False, "dispatchCount": 0, "deferred": False}

    monkeypatch.setattr("app.audio.get_audio_service", lambda: Audio())

    teacher = runtime["socketio"].test_client(runtime["app"], flask_test_client=http)
    assert teacher.is_connected()
    teacher.get_received()

    teacher.emit("prepare_training", {"studentId": student_id, "mode": "assessment", "requestId": "phase1-prepare-1"})
    prepare_events = _events(runtime, teacher)
    prepare_ack = next(item["args"][0] for item in prepare_events if item["name"] == "prepare_training_ack")
    assert prepare_ack["success"] is True
    media_session_id = prepare_ack["sessionId"]
    training_id = prepare_ack["trainingSessionId"]
    assert calls["media_start"] == [media_session_id]
    assert calls["analysis_start"] == []
    warmup = manager.get_session(media_session_id)
    assert warmup is not None and warmup.is_active()
    assert (warmup.metadata or {}).get("warmup") is True

    teacher.emit(
        "readiness_start",
        {
            "studentId": student_id,
            "trainingSessionId": training_id,
            "mediaMode": "browser",
            "items": [{"courseId": 1, "itemId": 10, "courseType": "naming"}],
        },
    )
    readiness_ack = next(
        item["args"][0]
        for item in _events(runtime, teacher)
        if item["name"] == "readiness_start_ack"
    )
    assert readiness_ack["success"] is True
    assert [item["moduleId"] for item in readiness_ack["snapshot"]["modules"]] == ["M2"]
    readiness._poll_capture(readiness.get_gate(training_id))
    assert capture_results[-1]["pending"] is True
    assert capture_results[-1]["sessionId"] == media_session_id
    assert manager.get_session(media_session_id).is_active()
    readiness.cancel(training_session_id=training_id)

    teacher.emit(
        "play_resource",
        {
            "action": "play",
            "studentId": student_id,
            "courseId": 1,
            "itemId": 10,
            "courseType": "naming",
            "trainingSessionId": training_id,
            "sessionId": media_session_id,
            "requestId": "phase1-play-1",
            "aux": {"targetText": "apple"},
        },
    )
    play_events = _events(runtime, teacher)
    play_ack = next(item["args"][0] for item in play_events if item["name"] == "play_resource_ack")
    assert play_ack["accepted"] is True
    assert play_ack["sessionId"] == media_session_id
    assert calls["media_start"] == [media_session_id]
    assert calls["media_stop"] == []
    recording = timeline.get_recording_session(media_session_id)
    assert recording is not None
    assert len(recording.segments) >= 2
    assert any(segment.seg_kind == "course" for segment in recording.segments)

    monkeypatch.setattr(events_mod, "_process_teacher_rating", lambda payload: {"success": True, "trainingSessionId": payload.get("trainingSessionId"), "rating": payload.get("rating")})
    teacher.emit("teacher_rating_submit", {"trainingSessionId": training_id, "rating": 5})
    rating_ack = next(item["args"][0] for item in _events(runtime, teacher) if item["name"] == "teacher_rating_ack")
    assert rating_ack == {"success": True, "trainingSessionId": training_id, "rating": 5}

    teacher.emit("finalize_training", {"trainingSessionId": training_id, "studentId": student_id, "operationId": "phase1-finalize-1"})
    finalize_ack = next(item["args"][0] for item in _events(runtime, teacher) if item["name"] == "finalize_training_ack")
    assert finalize_ack["success"] is True
    assert calls["media_stop"] == [media_session_id]
    assert manager.get_session(media_session_id) is None

    class ReportService:
        def generate(self, report_training_id, **_kwargs):
            return {"trainingSessionId": report_training_id, "publicationStatus": "draft"}

        def get_for_viewer(self, report_training_id, **_kwargs):
            return {"trainingSessionId": report_training_id, "publicationStatus": "draft"}

        def review_status(self, report_training_id):
            return {"trainingSessionId": report_training_id, "publicationStatus": "draft"}

    monkeypatch.setattr(report_routes, "get_report_service", lambda: ReportService())
    generated = http.post(f"/api/report/{training_id}/generate", json={"soft": True})
    reviewed = http.get(f"/api/report/{training_id}/review-status")
    fetched = http.get(f"/api/report/{training_id}?role=teacher&view=auto")
    assert generated.status_code == reviewed.status_code == fetched.status_code == 200
    assert generated.get_json()["data"]["publicationStatus"] == "draft"
    assert reviewed.get_json()["data"]["trainingSessionId"] == training_id
    assert fetched.get_json()["data"]["trainingSessionId"] == training_id

    # A second preparation is used only to freeze the cancel_prepare path.
    student_cancel = 99102
    _, manager_cancel, cancel_calls = _prepare_test_dependencies(monkeypatch, tmp_path / "cancel", student_cancel)
    teacher.emit("prepare_training", {"studentId": student_cancel, "mode": "training", "requestId": "phase1-prepare-cancel"})
    cancel_prepare_ack = next(item["args"][0] for item in _events(runtime, teacher) if item["name"] == "prepare_training_ack")
    teacher.emit("cancel_prepare_training", {"studentId": student_cancel, "trainingSessionId": cancel_prepare_ack["trainingSessionId"], "operationId": "phase1-cancel-1"})
    cancel_ack = next(item["args"][0] for item in _events(runtime, teacher) if item["name"] == "cancel_prepare_training_ack")
    assert cancel_ack["success"] is True
    assert cancel_prepare_ack["sessionId"] in cancel_ack["stoppedSessions"]
    assert cancel_calls["media_stop"] == [cancel_prepare_ack["sessionId"]]
    assert manager_cancel.get_session(cancel_prepare_ack["sessionId"]) is None


def _install_play_resource_fakes(monkeypatch, events_mod, child_sid):
    class Robot:
        def reserve_behavior(self, behavior_id=None, request_id=None, **kwargs):
            return {"accepted": True, "behaviorId": behavior_id or "phase1-behavior"}

        def abort_behavior(self, _behavior_id):
            return None

        def set_behavior_audio_expected(self, *_args, **_kwargs):
            return True

        def set_behavior_animation_expected(self, *_args, **_kwargs):
            return True

        def get_behavior_busy_state(self):
            return {"busy": False, "eventId": None, "remainingMs": 0}

    class Audio:
        def process_play_resource(self, *args, **kwargs):
            return {"triggered": False, "dispatchCount": 0, "deferred": False}

    monkeypatch.setattr("app.robot.get_robot_service", lambda: Robot())
    monkeypatch.setattr("app.audio.get_audio_service", lambda: Audio())
    monkeypatch.setattr(events_mod, "_resource_ready_support_for_identity", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        events_mod,
        "PlayResourceHandler",
        SimpleNamespace(
            handle=lambda payload: {
                "session_id": "phase1-play-session",
                "training_session_id": "phase1-training",
                "question_id": "phase1-question",
                "resolved_file": "question.mp4",
                "is_aux_operation": False,
                "audio_pending": False,
            }
        ),
    )
    monkeypatch.setattr(events_mod, "_start_or_defer_course_behavior", lambda *args, **kwargs: {"success": True, "skipped": True})


def test_phase1_room_isolation_targets_child_and_never_broadcasts_unresolved(
    monkeypatch, phase1_socket_runtime
):
    runtime = phase1_socket_runtime
    from app.sockets import events as events_mod

    teacher = _authenticated_socket(runtime, 31)
    child = runtime["socketio"].test_client(runtime["app"], flask_test_client=runtime["app"].test_client())
    unrelated = runtime["socketio"].test_client(runtime["app"], flask_test_client=runtime["app"].test_client())
    teacher.get_received()
    child_sid = next(
        item["args"][0]["sid"]
        for item in child.get_received()
        if item["name"] == "connected"
    )
    unrelated.get_received()

    _install_play_resource_fakes(monkeypatch, events_mod, child_sid)
    monkeypatch.setattr(events_mod, "_assign_child_for_identity", lambda *args, **kwargs: (child_sid, None))
    teacher.emit("teacher_enter_control", {"trainingSessionId": "phase1-training"})
    teacher.get_received()
    teacher.emit("play_resource", {"action": "play", "requestId": "phase1-room-child", "studentId": 1, "courseId": 1, "trainingSessionId": "phase1-training"})
    assert "play_resource" in _event_names(runtime, teacher)
    assert "play_resource" in _event_names(runtime, child)
    assert "play_resource" not in _event_names(runtime, unrelated)

    # An unresolved child is allowed to leave the request cached, but it must
    # not widen delivery to a global broadcast.
    monkeypatch.setattr(events_mod, "_assign_child_for_identity", lambda *args, **kwargs: (None, "child_offline"))
    teacher.emit("play_resource", {"action": "play", "requestId": "phase1-room-unresolved", "studentId": 2, "courseId": 1, "trainingSessionId": "phase1-training"})
    assert "play_resource" in _event_names(runtime, teacher)
    assert "play_resource" not in _event_names(runtime, unrelated)


@pytest.mark.parametrize(
    ("course_type", "rating_required", "return_to_question"),
    [
        ("pairing", False, True),
        ("ordering", False, True),
        ("naming", True, False),
    ],
)
def test_teacher_praise_policy_returns_interactive_courses_to_current_question(
    monkeypatch,
    phase1_socket_runtime,
    course_type,
    rating_required,
    return_to_question,
):
    runtime = phase1_socket_runtime
    from app.sockets import events as events_mod

    teacher = _authenticated_socket(runtime, 35)
    child = runtime["socketio"].test_client(
        runtime["app"],
        flask_test_client=runtime["app"].test_client(),
    )
    teacher.get_received()
    child_sid = next(
        item["args"][0]["sid"]
        for item in child.get_received()
        if item["name"] == "connected"
    )

    modality_commits = {"audio": [], "animation": []}
    started_payloads = []

    class Robot:
        def reserve_behavior(self, behavior_id=None, request_id=None, **_kwargs):
            return {
                "accepted": True,
                "behaviorId": behavior_id or f"{course_type}-manual-praise-behavior",
            }

        def abort_behavior(self, _behavior_id):
            return None

        def set_behavior_audio_expected(self, behavior_id, count, **_kwargs):
            modality_commits["audio"].append((behavior_id, count))
            return True

        def set_behavior_animation_expected(self, behavior_id, expected, **_kwargs):
            modality_commits["animation"].append((behavior_id, expected))
            return True

        def get_behavior_busy_state(self):
            return {"busy": False, "eventId": None, "remainingMs": 0}

    class Audio:
        def process_play_resource(self, *_args, **_kwargs):
            return {"triggered": True, "dispatchCount": 1, "deferred": False}

    monkeypatch.setattr("app.robot.get_robot_service", lambda: Robot())
    monkeypatch.setattr("app.audio.get_audio_service", lambda: Audio())
    monkeypatch.setattr(
        events_mod,
        "_assign_child_for_identity",
        lambda *_args, **_kwargs: (child_sid, None),
    )
    monkeypatch.setattr(
        events_mod,
        "_resource_ready_support_for_identity",
        lambda *_args, **_kwargs: True,
    )
    def handle_resource(payload):
        # The server-resolved course type wins over a stale client label.
        payload["courseType"] = course_type
        return {
            "session_id": f"{course_type}-manual-praise-session",
            "training_session_id": f"{course_type}-manual-praise-training",
            "question_id": f"{course_type}-question-7",
            "is_aux_operation": True,
            "audio_pending": True,
            "behavior_animation": "resources/Emotions/praise.mp4",
        }

    monkeypatch.setattr(
        events_mod,
        "PlayResourceHandler",
        SimpleNamespace(handle=handle_resource),
    )

    def start_behavior(_robot, payload):
        started_payloads.append(dict(payload))
        return {"success": True, "skipped": False}

    monkeypatch.setattr(events_mod, "_start_or_defer_course_behavior", start_behavior)

    training_id = f"{course_type}-manual-praise-training"
    teacher.emit("teacher_enter_control", {"trainingSessionId": training_id})
    teacher.get_received()
    teacher.emit(
        "play_resource",
        {
            "action": "play",
            "requestId": f"{course_type}-manual-praise-request",
            "studentId": 1,
            "courseId": 1,
            "courseType": "stale-client-type",
            "sessionId": f"{course_type}-manual-praise-session",
            "trainingSessionId": training_id,
            "questionId": f"{course_type}-question-7",
            "aux": {"praise": True},
        },
    )

    teacher_events = _events(runtime, teacher)
    child_events = _events(runtime, child)
    ack = next(
        item["args"][0]
        for item in teacher_events
        if item["name"] == "play_resource_ack"
    )
    assert ack["accepted"] is True, (ack, child_events)
    child_play = next(
        item["args"][0]
        for item in child_events
        if item["name"] == "play_resource"
    )

    assert ack["teacherRatingRequired"] is rating_required
    assert ack["returnToCurrentQuestion"] is return_to_question
    assert ack["holdLastFrame"] is (not return_to_question)
    assert child_play["questionId"] == f"{course_type}-question-7"
    assert child_play["courseType"] == course_type
    assert child_play["teacherRatingRequired"] is rating_required
    assert child_play["returnToCurrentQuestion"] is return_to_question
    assert child_play["holdLastFrame"] is (not return_to_question)
    assert child_play["behaviorAnimation"] == "resources/Emotions/praise.mp4"
    assert started_payloads[-1]["aux"]["praise"] is True
    assert modality_commits["audio"][-1][1] == 1
    assert modality_commits["animation"][-1][1] is True
    assert events_mod._should_forward_animation_terminal_to_teacher(
        ack["requestId"], ack["behaviorId"]
    ) is rating_required


def test_teacher_consumes_no_rating_policy_for_interactive_manual_praise():
    control = Path("teacher_frontend/components/ControlPage.tsx").read_text(
        encoding="utf-8"
    )
    play = control[
        control.index("const playCurrentItem = useCallback") :
        control.index("const retryFailedPlayback")
    ]
    ack = control[
        control.index("socket.on('play_resource_ack'") :
        control.index("socket.on('audio_status_update'")
    ]

    assert "selectedItem.course.type !== 'pairing'" in play
    assert "selectedItem.course.type !== 'ordering'" in play
    assert "data?.teacherRatingRequired === false" in ack
    no_rating = ack[ack.index("data?.teacherRatingRequired === false") :]
    assert no_rating.index("clearPraiseRequestContext(requestId)") < no_rating.index(
        "queuePraiseRating("
    )


def test_phase1_teacher_rating_ack_is_requester_only_and_not_globally_broadcast(
    monkeypatch, phase1_socket_runtime
):
    runtime = phase1_socket_runtime
    from app.sockets import events as events_mod

    teacher_one = _authenticated_socket(runtime, 41)
    teacher_two = _authenticated_socket(runtime, 42)
    teacher_one.get_received()
    teacher_two.get_received()
    monkeypatch.setattr(events_mod, "_process_teacher_rating", lambda _payload: {"success": True, "rating": 5})
    teacher_one.emit("teacher_enter_control", {"trainingSessionId": "phase1-rating"})
    teacher_one.get_received()
    teacher_one.emit("teacher_rating_submit", {"sessionId": "phase1-teacher-room", "trainingSessionId": "phase1-rating"})
    assert "teacher_rating_ack" in _event_names(runtime, teacher_one)
    assert "teacher_rating_ack" not in _event_names(runtime, teacher_two)


def test_phase1_demo_does_not_register_motion_socket_command(phase1_socket_runtime):
    runtime = phase1_socket_runtime
    client = runtime["socketio"].test_client(runtime["app"], flask_test_client=runtime["app"].test_client())
    client.get_received()
    client.emit("robot_play_motion", {"motionName": "wave"})
    assert "robot_playback_status" not in _event_names(runtime, client)
    assert "robot_motion_command" not in _event_names(runtime, client)


def test_phase1_busy_course_behavior_rejects_motion_and_expression_without_visual_leak(
    monkeypatch, phase1_socket_runtime
):
    runtime = phase1_socket_runtime
    from app.sockets import events as events_mod

    class BusyRobot:
        def __init__(self):
            self.abort_calls = []

        def reserve_behavior(self, **_kwargs):
            return {
                "accepted": False,
                "behaviorId": "active-behavior",
                "activeBehaviorId": "active-behavior",
                "remainingMs": 1000,
            }

        def get_behavior_busy_state(self):
            return {"busy": True, "eventId": "active-behavior", "remainingMs": 1000}

        def abort_behavior(self, behavior_id):
            self.abort_calls.append(behavior_id)

    busy_robot = BusyRobot()
    handler_calls = []
    monkeypatch.setattr("app.robot.get_robot_service", lambda: busy_robot)
    monkeypatch.setattr(events_mod, "_resource_ready_support_for_identity", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        events_mod,
        "PlayResourceHandler",
        SimpleNamespace(handle=lambda payload: handler_calls.append(payload)),
    )
    requester = _authenticated_socket(runtime, 51)
    observer = runtime["socketio"].test_client(
        runtime["app"], flask_test_client=runtime["app"].test_client()
    )
    requester.get_received()
    observer.get_received()
    requester.emit("teacher_enter_control", {"trainingSessionId": "phase1-busy"})
    requester.get_received()

    attempts = (
        {
            "action": "play",
            "studentId": 1,
            "courseId": 1,
            "requestId": "phase1-busy-motion",
            "behaviorId": "motion-attempt",
            "trainingSessionId": "phase1-busy",
            "aux": {"question": True},
        },
        {
            "action": "play",
            "studentId": 1,
            "courseId": 1,
            "requestId": "phase1-busy-expression",
            "behaviorId": "expression-attempt",
            "trainingSessionId": "phase1-busy",
            "aux": {"praise": True},
            "emotion": "happy.gif",
        },
    )
    for payload in attempts:
        requester.emit("play_resource", payload)
        received = _events(runtime, requester)
        assert "behavior_trigger_rejected" in [item["name"] for item in received]
        assert not {"robot_motion_command", "robot_emotion_change"}.intersection(
            item["name"] for item in received
        )
        assert not {"robot_motion_command", "robot_emotion_change"}.intersection(
            _event_names(runtime, observer)
        )

    assert handler_calls == []
    assert busy_robot.abort_calls == []
    assert busy_robot.get_behavior_busy_state()["busy"] is True
