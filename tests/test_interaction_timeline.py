import json

import pytest

from app.behavior.interaction import InteractionStateService
from app.behavior.store import BehaviorStore
from app.behavior.audit_timeline import FullInteractionTimeline
from app.diagnostics.latency_report import build_latency_report, render_latency_markdown


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


def test_latency_callback_records_exact_server_receive_milestone(monkeypatch):
    from app.sockets.events import _record_latency_modality_callback

    calls = []
    monkeypatch.setattr(
        "app.behavior.audit_timeline.record_audit_event",
        lambda event, **kwargs: calls.append((event, kwargs)) or kwargs,
    )

    _record_latency_modality_callback({
        "trainingSessionId": "training-1",
        "sessionId": "runtime-1",
        "requestId": "request-1",
        "behaviorId": "behavior-1",
        "modality": "speech",
        "commandReceivedAtClientMs": 5000,
        "actualAtClientMs": 5620,
    }, phase="started")

    assert calls[0][0] == "latency.modality_started_callback"
    assert calls[0][1]["modality"] == "audio"
    assert calls[0][1]["client_timestamp"] == 5620
    assert calls[0][1]["details"]["commandReceivedAtClientMs"] == 5000


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


def test_full_timeline_isolates_reused_training_id_by_media_session(tmp_path):
    sessions = tmp_path / "sessions"
    for index, runtime_id in enumerate(("runtime-old", "runtime-new"), start=1):
        directory = sessions / f"child-session-{index}"
        directory.mkdir(parents=True)
        (directory / "session_meta.json").write_text(json.dumps({
            "mediaSessionId": runtime_id,
            "trainingSessionId": "training-reused",
            "recordingStartedAtUnix": index,
        }), encoding="utf-8")

    timeline = FullInteractionTimeline(recording_root=sessions)
    old = timeline.record(
        "old-event",
        training_session_id="training-reused",
        runtime_session_id="runtime-old",
    )
    new = timeline.record(
        "new-event",
        training_session_id="training-reused",
        runtime_session_id="runtime-new",
    )
    inferred = timeline.record(
        "latest-event-without-runtime-id",
        training_session_id="training-reused",
    )
    legacy_row = {
        "eventId": "legacy-misplaced-row",
        "event": "legacy-recovered-event",
        "trainingSessionId": "training-reused",
        "sessionId": "runtime-new",
        "serverEpochMs": inferred["serverEpochMs"] + 1,
        "sequence": 99,
    }
    with (
        sessions / "child-session-1" / "full_interaction_timeline.jsonl"
    ).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(legacy_row) + "\n")

    assert old["sequence"] == 1
    assert new["sequence"] == 1
    assert [row["event"] for row in timeline.read(
        "training-reused", "runtime-old"
    )] == ["old-event"]
    assert [row["event"] for row in timeline.read(
        "training-reused", "runtime-new"
    )] == [
        "new-event", "latest-event-without-runtime-id", "legacy-recovered-event"
    ]
    assert inferred["sessionId"] == "runtime-new"
    assert timeline.read("training-reused", "runtime-new")[-1][
        "_legacyMisplacedAuditRow"
    ] is True
    assert (
        sessions / "child-session-1" / "full_interaction_timeline.jsonl"
    ).is_file()
    assert (
        sessions / "child-session-2" / "full_interaction_timeline.jsonl"
    ).is_file()


def test_latency_report_separates_server_sync_network_and_modalities():
    common = {
        "trainingSessionId": "training-1",
        "sessionId": "runtime-1",
        "requestId": "request-1",
        "behaviorId": "behavior-1",
    }
    rows = [
        {
            **common,
            "event": "latency.play_resource_received",
            "serverEpochMs": 1000,
            "timestamp": "2026-08-22T00:00:01Z",
            "details": {
                "teacherNetworkRttMs": 80,
                "request": {"courseType": "naming", "aux": {"praise": True}},
            },
        },
        {
            **common,
            "event": "robot_behavior_queued",
            "serverEpochMs": 1100,
            "details": {"startAtEpochMs": 1800},
        },
        {
            **common,
            "event": "latency.multimodal_dispatched",
            "serverEpochMs": 1250,
        },
        {
            **common,
            "event": "play_resource_ack",
            "serverEpochMs": 1300,
            "status": "accepted",
        },
        {
            **common,
            "event": "robot_expression_status",
            "serverEpochMs": 1850,
            "category": "robot_execution",
            "modality": "expression",
            "status": "playing",
        },
        {
            **common,
            "event": "latency.modality_started_callback",
            "serverEpochMs": 1870,
            "modality": "audio",
            "details": {
                "commandReceivedAtClientMs": 5000,
                "actualAtClientMs": 5620,
            },
        },
        {
            **common,
            "event": "latency.modality_started_callback",
            "serverEpochMs": 1900,
            "modality": "display",
            "status": "ready",
        },
    ]

    report = build_latency_report("training-1", rows)
    item = report["interactions"][0]
    assert item["intent"] == "表扬"
    assert item["metrics"] == {
        "teacherNetworkRttMs": 80,
        "serverQueueMs": 100,
        "serverDispatchMs": 250,
        "serverAckMs": 300,
        "plannedSyncLeadMs": 700,
    }
    assert item["modalities"]["expression"]["startObservedMs"] == 850
    assert item["modalities"]["audio"]["clientReceiveToStartMs"] == 620
    assert item["modalities"]["display"]["startObservedMs"] == 900
    assert item["primarySource"] == "sync"
    assert "语音策略模拟" in render_latency_markdown(report)


def test_latency_report_exposes_display_stages_motion_proxy_and_dialogue_round():
    common = {
        "trainingSessionId": "training-1",
        "sessionId": "runtime-1",
        "requestId": "request-display",
    }
    rows = [
        {**common, "event": "latency.play_resource_received", "serverEpochMs": 1000,
         "timestamp": "2026-08-23T00:00:01Z"},
        {**common, "event": "robot_motion_status", "serverEpochMs": 1200,
         "category": "robot_execution", "modality": "motion", "status": "dispatched"},
        {**common, "event": "latency.modality_started_callback", "serverEpochMs": 1650,
         "modality": "display", "details": {"timing": {
             "preflightMs": 90, "preloadMs": 420, "paintWaitMs": 32,
             "crossfadeMs": 321, "totalClientMs": 870,
         }}},
        {"trainingSessionId": "training-1", "sessionId": "runtime-1",
         "requestId": "dialogue-1", "event": "dialogue.audio_received",
         "serverEpochMs": 2000, "timestamp": "2026-08-23T00:00:02Z",
         "details": {"clientTiming": {"vadSilenceTailMs": 910, "encodingMs": 18}}},
        {"trainingSessionId": "training-1", "sessionId": "runtime-1",
         "requestId": "dialogue-1", "event": "dialogue.stt_completed",
         "serverEpochMs": 2420, "details": {"durationMs": 415, "provider": "funasr",
         "timing": {"base64DecodeMs": 4, "audioConvertMs": 31,
                    "localAttemptMs": 376, "remoteFallbackMs": 0}}},
        {"trainingSessionId": "training-1", "sessionId": "runtime-1",
         "requestId": "dialogue-1", "event": "dialogue_reply_generated",
         "serverEpochMs": 2550, "status": "ok",
         "details": {"replyDurationMs": 125, "provider": "rule", "strategy": "rule"}},
        {"trainingSessionId": "training-1", "sessionId": "runtime-1",
         "requestId": "dialogue-1", "event": "dialogue.client_tts_started",
         "serverEpochMs": 2800, "details": {"clientStageMs": 110}},
    ]

    report = build_latency_report(
        "training-1", rows, media_session_id="runtime-1"
    )
    interaction = report["interactions"][0]
    assert interaction["modalities"]["motion"]["measurementQuality"] == "dispatch_proxy"
    assert report["modalities"]["motion"]["proxySamples"] == 1
    assert report["modalities"]["display"]["endpointStages"]["preloadMs"]["p50Ms"] == 420
    assert report["dialogue"]["metrics"]["vadSilenceTailMs"]["p50Ms"] == 910
    assert report["dialogue"]["metrics"]["sttLocalAttemptMs"]["p50Ms"] == 376
    assert report["dialogue"]["metrics"]["ttsStartObservedMs"]["p50Ms"] == 800
    assert report["dataQuality"]["isolated"] is True


def test_latency_report_routes_list_sessions_and_export_markdown(tmp_path, monkeypatch):
    from flask import Flask
    from app.routes import interaction_timeline as routes

    timeline = FullInteractionTimeline(tmp_path / "behavior")
    timeline.record(
        "latency.play_resource_received",
        training_session_id="training-1",
        request_id="request-1",
        details={"request": {"aux": {"question": True}}},
    )
    monkeypatch.setattr(routes, "get_full_interaction_timeline", lambda: timeline)
    monkeypatch.setattr(routes, "build_session_catalog", lambda limit=100: {
        "sessions": [{
            "trainingSessionId": "training-1",
            "mediaSessionId": "runtime-1",
            "folderName": "child-session",
            "student": {"name": "小明"},
            "recordingStartedAt": "2026-08-22T00:00:00Z",
            "status": "recording",
            "liveActive": True,
        }]
    })
    app = Flask("latency-api")
    app.register_blueprint(routes.interaction_timeline_bp)
    client = app.test_client()

    sessions = client.get("/api/v2/timeline/latency/sessions")
    assert sessions.status_code == 200
    assert sessions.get_json()["sessions"][0]["studentName"] == "小明"
    report = client.get("/api/v2/timeline/training-1/latency")
    assert report.status_code == 200
    assert report.get_json()["schemaVersion"] == "interaction-latency-report-v1"
    markdown = client.get("/api/v2/timeline/training-1/latency?format=markdown")
    assert markdown.status_code == 200
    assert "交互延迟诊断报告" in markdown.get_data(as_text=True)


def test_server_config_exposes_read_only_latency_dashboard():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    template = (root / "templates/server/config.html").read_text(encoding="utf-8")
    script = (root / "static/js/config_latency.js").read_text(encoding="utf-8")
    assert 'href="/server/config/latency"' in template
    assert 'id="module-latency"' in template
    assert "/api/v2/timeline/latency/sessions" in script
    assert "format=markdown" in script
