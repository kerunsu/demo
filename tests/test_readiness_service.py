from types import SimpleNamespace

import app.services.readiness_service as readiness_mod
from app.services.readiness_service import ReadinessService


def _payload(**extra):
    return {
        "studentId": 7,
        "trainingSessionId": "training-7",
        "items": [{"courseId": 1, "itemId": 2, "courseType": "naming"}],
        **extra,
    }


def _without_background_threads(monkeypatch, service):
    monkeypatch.setattr(service, "_schedule_poll", lambda _gate: None)
    monkeypatch.setattr(service, "_schedule_timeout", lambda _gate: None)


def test_start_requires_only_business_identity_and_selected_items(monkeypatch):
    service = ReadinessService()
    _without_background_threads(monkeypatch, service)
    assert service.start("teacher", {})["error"] == "missing_student_id"
    assert service.start("teacher", {"studentId": 7})["error"] == "missing_training_session_id"
    assert service.start("teacher", {"studentId": 7, "trainingSessionId": "t"})["error"] == "missing_items"


def test_start_calls_formal_capture_once_and_never_sends_resource_prepare(monkeypatch):
    service = ReadinessService()
    _without_background_threads(monkeypatch, service)
    starts = []
    child_events = []
    service.set_capture_start_callback(
        lambda training: starts.append(training) or {"ok": True, "sessionId": "media-7"}
    )
    service.set_child_emitter(lambda event, payload: child_events.append((event, payload)))

    result = service.start("teacher-a", _payload())

    assert result["success"] is True
    assert result["status"] == "STARTING"
    assert [item["moduleId"] for item in result["modules"]] == ["M2"]
    assert starts == ["training-7"]
    assert [event for event, _ in child_events] == ["readiness_complete"]
    assert child_events[0][1]["captureStart"] is True
    assert "assetUrls" not in child_events[0][1]
    assert "audioUrls" not in child_events[0][1]


def test_repeated_start_is_monotonic_and_does_not_create_generation(monkeypatch):
    service = ReadinessService()
    _without_background_threads(monkeypatch, service)
    starts = []
    service.set_capture_start_callback(
        lambda training: starts.append(training) or {"ok": True, "sessionId": "media-7"}
    )
    monkeypatch.setattr(
        service,
        "check_capture",
        lambda *_args, **_kwargs: {"ok": True, "detail": "server video accepted", "sessionId": "media-7"},
    )

    first = service.start("teacher-a", _payload())
    gate = service.get_gate("training-7")
    service._poll_capture(gate)
    replay = service.start("teacher-b", _payload())

    assert replay["idempotentReplay"] is True
    assert replay["status"] == "RECORDING_CONFIRMED"
    assert replay["ok"] is True
    assert gate.generation == 1
    assert gate.teacher_sid == "teacher-b"
    assert starts == ["training-7"]


def test_server_video_sample_completes_once(monkeypatch):
    service = ReadinessService()
    _without_background_threads(monkeypatch, service)
    events = []
    service.set_emitter(lambda event, payload, sid=None: events.append((event, payload, sid)))
    service.set_capture_start_callback(lambda _training: {"ok": True, "sessionId": "media-7"})
    monkeypatch.setattr(
        service,
        "check_capture",
        lambda *_args, **_kwargs: {"ok": True, "detail": "server video accepted", "sessionId": "media-7"},
    )
    service.start("teacher", _payload())
    gate = service.get_gate("training-7")

    service._poll_capture(gate)
    service._poll_capture(gate)

    completed = [payload for event, payload, _ in events if event == "readiness_complete"]
    assert len(completed) == 1
    assert completed[0]["ok"] is True
    assert completed[0]["captureStarted"] is True
    assert gate.status == "RECORDING_CONFIRMED"


def test_resource_and_audio_reports_cannot_change_recording_state(monkeypatch):
    service = ReadinessService()
    _without_background_threads(monkeypatch, service)
    service.set_capture_start_callback(lambda _training: {"ok": True, "sessionId": "media-7"})
    monkeypatch.setattr(
        service,
        "check_capture",
        lambda *_args, **_kwargs: {"ok": True, "detail": "server video accepted", "sessionId": "media-7"},
    )
    service.start("teacher", _payload())
    gate = service.get_gate("training-7")
    service._poll_capture(gate)

    result = service.handle_child_report({
        "trainingSessionId": "training-7",
        "coursesReady": False,
        "assetsComplete": True,
        "assetFailed": ["missing.png"],
        "audioComplete": True,
        "audioFailed": ["missing.wav"],
        "recording": False,
        "mediaTracksOk": False,
    })

    assert result["success"] is True
    assert gate.status == "RECORDING_CONFIRMED"
    assert gate.snapshot()["ok"] is True


def test_capture_error_is_actionable_and_retry_reuses_same_gate(monkeypatch):
    service = ReadinessService()
    _without_background_threads(monkeypatch, service)
    attempts = []

    def start_capture(_training):
        attempts.append(1)
        if len(attempts) == 1:
            return {"ok": False, "error": "camera_open_failed"}
        return {"ok": True, "sessionId": "media-retry"}

    service.set_capture_start_callback(start_capture)
    first = service.start("teacher", _payload())
    gate = service.get_gate("training-7")
    retried = service.start("teacher", _payload(retry=True))

    assert first["status"] == "FAILED"
    assert "camera_open_failed" in first["modules"][0]["detail"]
    assert retried["status"] == "STARTING"
    assert gate.generation == 1
    assert gate.session_id == "media-retry"
    assert len(attempts) == 2


def test_force_enter_never_bypasses_missing_video(monkeypatch):
    service = ReadinessService()
    _without_background_threads(monkeypatch, service)
    service.set_capture_start_callback(lambda _training: {"ok": True, "sessionId": "media-7"})
    service.start("teacher", _payload())
    denied = service.force_enter("training-7", teacher_sid="teacher")
    assert denied["success"] is False
    assert denied["error"] == "recording_not_ready"


def test_check_capture_uses_server_video_not_audio_or_client_claims(monkeypatch):
    session = SimpleNamespace(
        session_id="media-7",
        training_session_id="training-7",
        total_frames=0,
        metadata={"continuous_recording": True, "recording_mode": "continuous"},
        is_active=lambda: True,
    )
    monkeypatch.setattr(
        "app.session.get_session_manager",
        lambda: SimpleNamespace(get_sessions_by_student=lambda _student: [session]),
    )
    upload_meta = {
        "lastAudioAccepted": 20,
        "lastAudioAt": readiness_mod._now_ms(),
        "lastVideoAccepted": 0,
    }
    monkeypatch.setattr("app.routes.media_upload.get_media_session_meta", lambda _sid: dict(upload_meta))
    service = ReadinessService()

    pending = service.check_capture(7, "training-7", {
        "recording": True,
        "mediaTracksOk": True,
        "frameCount": 999,
        "hasRecentUplink": True,
    })
    upload_meta.update({"lastVideoAccepted": 1, "lastFrameAt": readiness_mod._now_ms()})
    ready = service.check_capture(7, "training-7")

    assert pending["ok"] is False
    assert ready["ok"] is True


def test_old_generation_resource_report_is_ignored_as_recording_evidence(monkeypatch):
    service = ReadinessService()
    _without_background_threads(monkeypatch, service)
    service.set_capture_start_callback(lambda _training: {"ok": True, "sessionId": "media-7"})
    monkeypatch.setattr(
        service,
        "check_capture",
        lambda *_args, **_kwargs: {"ok": False, "pending": True, "detail": "waiting for video"},
    )
    service.start("teacher", _payload())
    result = service.handle_child_report({
        "trainingSessionId": "training-7",
        "generation": 99,
        "audioComplete": True,
        "coursesReady": True,
    })
    assert result["success"] is True
    assert service.get_gate("training-7").status == "STARTING"
