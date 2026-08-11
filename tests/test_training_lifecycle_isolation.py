"""训练生命周期操作的幂等与跨会话隔离回归。"""

from types import SimpleNamespace

from app.session import get_session_manager
from app.sockets import handlers as handlers_mod
from app.sockets.handlers import (
    CancelPrepareTrainingHandler,
    FinalizeTrainingHandler,
    PrepareTrainingHandler,
    _close_runtime_session,
)


class _Media:
    def start_recording(self, *args, **kwargs):
        return True

    def stop_recording(self, *args, **kwargs):
        return True


def _remove_student_sessions(student_id):
    manager = get_session_manager()
    for session in list(manager.get_sessions_by_student(student_id)):
        manager.remove_session(session.session_id)


def _create_active_session(student_id, training_id):
    manager = get_session_manager()
    session = manager.create_session(
        student_id=student_id,
        course_id=1,
        course_item_id=1,
        training_session_id=training_id,
        question_id=f"{training_id}_q",
        metadata={
            "continuous_recording": True,
            "recording_mode": "continuous",
        },
    )
    session.start()
    manager.update_session(session)
    return session


def test_prepare_request_id_is_idempotent(monkeypatch, tmp_path):
    from app.behavior.service import BehaviorService
    from app.behavior.store import BehaviorStore
    from app.behavior.timeline import BehaviorTimeline

    student_id = 99001
    _remove_student_sessions(student_id)
    behavior = BehaviorService()
    behavior.store = BehaviorStore(tmp_path / "behavior")
    behavior.timeline = BehaviorTimeline(behavior.store)
    monkeypatch.setattr(handlers_mod, "get_behavior_service", lambda: behavior)
    monkeypatch.setattr(handlers_mod, "get_media_service", lambda: _Media())
    monkeypatch.setattr(
        handlers_mod,
        "load_student_label",
        lambda _student_id: ("幂等测试", 6),
    )
    monkeypatch.setattr(
        handlers_mod,
        "begin_recording_session",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(handlers_mod, "_refresh_session_paths", lambda session: None)

    payload = {
        "studentId": student_id,
        "mode": "assessment",
        "requestId": "prepare-once-99001",
    }
    first = PrepareTrainingHandler.handle(payload)
    second = PrepareTrainingHandler.handle(payload)

    assert first["success"] is True
    assert second["idempotentReplay"] is True
    assert second["training_session_id"] == first["training_session_id"]
    assert second["session_id"] == first["session_id"]
    assert len(
        [
            session
            for session in get_session_manager().get_sessions_by_student(student_id)
            if session.is_active()
        ]
    ) == 1
    _remove_student_sessions(student_id)


def test_cancel_with_training_id_does_not_stop_newer_training(monkeypatch):
    student_id = 99002
    _remove_student_sessions(student_id)
    old_session = _create_active_session(student_id, "training-old")
    new_session = _create_active_session(student_id, "training-new")
    stopped = []
    monkeypatch.setattr(
        handlers_mod,
        "finalize_recording_session",
        lambda session_id, status: stopped.append(session_id),
    )
    monkeypatch.setattr(
        handlers_mod,
        "_close_runtime_session",
        lambda session_id, send_summary, **_kwargs: None,
    )

    result = CancelPrepareTrainingHandler.handle(
        {
            "studentId": student_id,
            "trainingSessionId": "training-old",
        }
    )

    assert result["stoppedSessions"] == [old_session.session_id]
    assert stopped == [old_session.session_id]
    assert new_session.session_id not in stopped
    _remove_student_sessions(student_id)


def test_finalize_with_training_id_does_not_close_newer_training(monkeypatch):
    student_id = 99003
    _remove_student_sessions(student_id)
    old_session = _create_active_session(student_id, "training-old-finalize")
    new_session = _create_active_session(student_id, "training-new-finalize")
    stopped = []

    class _Behavior:
        def close_window(self, *args, **kwargs):
            return None

        def finalize(self, training_session_id):
            assert training_session_id == "training-old-finalize"
            return SimpleNamespace(
                window_count=1,
                attention={"avg_score": None},
                limitations=[],
            )

    monkeypatch.setattr(handlers_mod, "get_behavior_service", lambda: _Behavior())
    monkeypatch.setattr(
        handlers_mod,
        "finalize_recording_session",
        lambda session_id, status: stopped.append(session_id),
    )
    monkeypatch.setattr(
        handlers_mod,
        "_close_runtime_session",
        lambda session_id, send_summary, **_kwargs: None,
    )

    payload = {
        "studentId": student_id,
        "trainingSessionId": "training-old-finalize",
        "operationId": "finalize-once-99003",
    }
    result = FinalizeTrainingHandler.handle(payload)
    replay = FinalizeTrainingHandler.handle(payload)

    assert result["success"] is True
    assert replay["idempotentReplay"] is True
    assert replay["trainingSessionId"] == result["trainingSessionId"]
    assert result["stoppedRuntimeSessions"] == [old_session.session_id]
    assert stopped == [old_session.session_id]
    assert new_session.session_id not in stopped
    _remove_student_sessions(student_id)


def test_cancel_cleanup_failure_is_not_reported_as_success(monkeypatch):
    student_id = 99004
    _remove_student_sessions(student_id)
    session = _create_active_session(student_id, "training-cancel-failure")
    monkeypatch.setattr(
        handlers_mod,
        "finalize_recording_session",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("recorder unavailable")
        ),
    )

    result = CancelPrepareTrainingHandler.handle({
        "studentId": student_id,
        "trainingSessionId": "training-cancel-failure",
    })

    assert result["success"] is False
    assert result["error"] == "cancel_runtime_cleanup_failed"
    assert result["stoppedSessions"] == []
    assert result["failedSessions"][0]["sessionId"] == session.session_id
    _remove_student_sessions(student_id)


def test_strict_runtime_cleanup_rejects_false_media_stop(monkeypatch):
    student_id = 99006
    _remove_student_sessions(student_id)
    session = _create_active_session(student_id, "training-media-stop-false")

    class _MediaStopFails:
        def stop_recording(self, _session_id):
            return False

    class _Analysis:
        def end_session(self, _session_id):
            return None

    monkeypatch.setattr(
        handlers_mod,
        "get_media_service",
        lambda: _MediaStopFails(),
    )
    monkeypatch.setattr(
        handlers_mod,
        "get_analysis_service",
        lambda: _Analysis(),
    )

    try:
        _close_runtime_session(
            session.session_id,
            send_summary=False,
            strict=True,
        )
    except RuntimeError as exc:
        assert "stop_media:return_false" in str(exc)
    else:
        raise AssertionError("strict cleanup accepted a failed media stop")

    assert get_session_manager().get_session(session.session_id) is session
    assert session.is_active()
    _remove_student_sessions(student_id)


def test_finalize_timeline_failure_does_not_leave_recording_active(
    monkeypatch,
):
    student_id = 99005
    _remove_student_sessions(student_id)
    session = _create_active_session(student_id, "training-finalize-retry")
    finalize_calls = []

    class _Behavior:
        def get_training(self, training_session_id):
            return SimpleNamespace(student_id=student_id)

        def close_window(self, *args, **kwargs):
            return None

        def finalize(self, training_session_id):
            finalize_calls.append(training_session_id)
            return SimpleNamespace(
                window_count=1,
                attention={"avg_score": None},
                limitations=[],
            )

    monkeypatch.setattr(handlers_mod, "get_behavior_service", lambda: _Behavior())
    should_fail = {"value": True}

    def finalize_recording(*_args, **_kwargs):
        if should_fail["value"]:
            raise RuntimeError("timeline unavailable")

    monkeypatch.setattr(
        handlers_mod,
        "finalize_recording_session",
        finalize_recording,
    )
    monkeypatch.setattr(
        handlers_mod,
        "_close_runtime_session",
        lambda session_id, send_summary, **_kwargs: None,
    )

    payload = {
        "studentId": student_id,
        "trainingSessionId": "training-finalize-retry",
        "operationId": "finalize-retry-99005",
    }
    finalized = FinalizeTrainingHandler.handle(payload)
    should_fail["value"] = False
    replay = FinalizeTrainingHandler.handle(payload)

    assert finalized["success"] is True
    assert finalized["stoppedRuntimeSessions"] == [session.session_id]
    assert "timeline unavailable" in finalized["cleanupWarnings"][0]["error"]
    assert finalize_calls == ["training-finalize-retry"]
    assert replay["success"] is True
    assert replay["idempotentReplay"] is True
    _remove_student_sessions(student_id)
