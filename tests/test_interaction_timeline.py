import json

import pytest

from app.behavior.interaction import InteractionStateService
from app.behavior.store import BehaviorStore
from app.behavior.audit_timeline import FullInteractionTimeline


def test_behavior_json_replace_preserves_previous_file_on_write_failure(tmp_path, monkeypatch):
    store = BehaviorStore(tmp_path / "behavior")
    target = tmp_path / "behavior" / "session-1" / "training.json"
    store._write_json(target, {"version": 1})

    def interrupted_dump(data, stream, **kwargs):
        stream.write('{"version":')
        raise OSError("simulated interruption")

    monkeypatch.setattr("app.behavior.store.json.dump", interrupted_dump)
    with pytest.raises(OSError, match="simulated interruption"):
        store._write_json(target, {"version": 2})

    assert json.loads(target.read_text(encoding="utf-8")) == {"version": 1}
    assert list(target.parent.glob(".training.json.*.tmp")) == []


def test_interaction_timeline_uses_audio_end_and_keeps_first_prompt_baseline(tmp_path):
    store = BehaviorStore(tmp_path / "behavior")
    service = InteractionStateService(store)
    common = {
        "training_session_id": "training-1",
        "question_id": "question-1",
        "runtime_session_id": "runtime-1",
    }

    service.record("question_presented", **common, server_epoch_ms=1_000)
    service.record("question_audio_ended", **common, server_epoch_ms=2_000)
    repeat = service.record("question_presented", **common, server_epoch_ms=4_000)
    service.record("question_audio_ended", **common, server_epoch_ms=5_000)
    response = service.record("child_response", **common, server_epoch_ms=5_750)

    assert repeat.event_type == "question_repeat"
    assert response.metadata["responseMsFromFirstQuestion"] == 3_750
    assert response.metadata["responseMsFromLatestPrompt"] == 750
    assert service.response_metrics("training-1", "question-1") == {
        "responseMsFromFirstQuestion": 3_750,
        "responseMsFromLatestPrompt": 750,
    }

    records = [
        json.loads(line)
        for line in (
            tmp_path
            / "behavior"
            / "training-1"
            / "interaction_timeline.jsonl"
        ).read_text(encoding="utf-8").splitlines()
    ]
    assert [record["event_type"] for record in records] == [
        "question_presented",
        "question_audio_ended",
        "question_repeat",
        "question_audio_ended",
        "child_response",
    ]


def test_interaction_state_restores_response_metrics_after_restart(tmp_path):
    root = tmp_path / "behavior"
    first = InteractionStateService(BehaviorStore(root))
    first.record(
        "question_presented", "training-1", question_id="question-1",
        server_epoch_ms=10_000,
    )
    first.record(
        "question_audio_ended", "training-1", question_id="question-1",
        server_epoch_ms=11_000,
    )
    first.record(
        "child_response", "training-1", question_id="question-1",
        server_epoch_ms=12_250,
    )

    restored = InteractionStateService(BehaviorStore(root))
    assert restored.response_metrics("training-1", "question-1")[
        "responseMsFromFirstQuestion"
    ] == 1_250


def test_full_timeline_is_server_ordered_sanitized_and_exportable(tmp_path):
    timeline = FullInteractionTimeline(tmp_path / "behavior")
    first = timeline.record(
        "teacher_socket_emit.play_resource",
        training_session_id="training-1",
        runtime_session_id="runtime-1",
        request_id="request-1",
        actor="teacher",
        source="teacher_ui",
        category="teacher_operation",
        client_timestamp=1000,
        details={"audioBase64": "raw-private-audio", "token": "secret"},
    )
    second = timeline.record(
        "robot_expression_status",
        training_session_id="training-1",
        runtime_session_id="runtime-1",
        request_id="request-1",
        behavior_id="behavior-1",
        actor="robot_service",
        category="robot_execution",
        modality="expression",
        phase="running",
        status="dispatched",
    )

    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert second["serverEpochMs"] >= first["serverEpochMs"]
    assert first["details"]["audioBase64"]["omitted"] is True
    assert first["details"]["token"] == "[redacted]"
    persisted = timeline.read("training-1")
    assert [row["event"] for row in persisted] == [
        "teacher_socket_emit.play_resource", "robot_expression_status"
    ]
    exported = timeline.export_csv("training-1")
    assert "serverMonotonicMs" in exported
    assert "robot_expression_status" in exported


def test_full_timeline_rejects_path_traversal(tmp_path):
    timeline = FullInteractionTimeline(tmp_path / "behavior")
    with pytest.raises(ValueError, match="invalid_training_session_id"):
        timeline.read("../outside")


def test_socket_interaction_helper_reaches_behavior_service(monkeypatch):
    from app.sockets.events import _record_interaction

    calls = []

    class Behavior:
        def get_interaction_snapshot(self, *_args):
            return {"firstResponseAtMs": None, "lastEventType": None, "questionPresentationCount": 0}

        def record_interaction(self, event_type, training_id, **kwargs):
            calls.append((event_type, training_id, kwargs))
            return {"event": event_type}

    monkeypatch.setattr("app.behavior.get_behavior_service", lambda: Behavior())
    result = _record_interaction("question_presented", {
        "trainingSessionId": "training-1",
        "sessionId": "runtime-1",
        "questionId": "question-1",
        "requestId": "request-1",
        "behaviorId": "behavior-1",
    }, actor="server")

    assert result == {"event": "question_presented"}
    assert calls[0][0:2] == ("question_presented", "training-1")
    assert calls[0][2]["runtime_session_id"] == "runtime-1"


def test_full_timeline_http_query_and_csv_export(tmp_path, monkeypatch):
    from flask import Flask
    from app.routes import interaction_timeline as routes

    timeline = FullInteractionTimeline(tmp_path / "behavior")
    timeline.record("course_screen_ready", training_session_id="training-1")
    monkeypatch.setattr(routes, "get_full_interaction_timeline", lambda: timeline)
    app = Flask("timeline-api")
    app.register_blueprint(routes.interaction_timeline_bp)
    client = app.test_client()

    response = client.get("/api/v2/timeline/training-1")
    assert response.status_code == 200
    assert response.get_json()["events"][0]["event"] == "course_screen_ready"
    csv_response = client.get("/api/v2/timeline/training-1?format=csv")
    assert csv_response.status_code == 200
    assert b"course_screen_ready" in csv_response.data


def test_full_timeline_uses_same_per_course_directory_as_recordings(tmp_path):
    sessions = tmp_path / "sessions"
    course_dir = sessions / "小明-6-20260809-1"
    course_dir.mkdir(parents=True)
    (course_dir / "session_meta.json").write_text(json.dumps({
        "mediaSessionId": "runtime-1",
        "trainingSessionId": "training-1",
        "humanDirName": course_dir.name,
    }), encoding="utf-8")
    (course_dir / "video.avi").write_bytes(b"")
    (course_dir / "audio.wav").write_bytes(b"")

    timeline = FullInteractionTimeline(recording_root=sessions)
    recorded = timeline.record(
        "teacher_socket_emit.play_resource",
        training_session_id="training-1",
        runtime_session_id="runtime-1",
    )

    assert recorded is not None
    assert (course_dir / "full_interaction_timeline.jsonl").is_file()
    assert not (sessions / "training-1").exists()
