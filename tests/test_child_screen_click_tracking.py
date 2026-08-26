from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask

from app.behavior.models import SessionBehaviorSummary
from app.behavior.screen_interaction import (
    CLICK_EVENT,
    summarize_screen_interaction,
    validate_click_details,
)


def _click_details(**overrides):
    value = {
        "schemaVersion": "child-screen-click-v1",
        "clickId": "click-001",
        "clientSequence": 1,
        "captureEvent": "pointerdown",
        "pointerType": "touch",
        "button": 0,
        "isPrimary": True,
        "clientMonotonicMs": 1234.5,
        "pageType": "interactive_iframe",
        "frameId": "interactive",
        "coordinateSpace": "top_viewport+iframe_content",
        "viewportX": 320,
        "viewportY": 240,
        "viewportWidth": 1280,
        "viewportHeight": 720,
        "viewportXRatio": 0.25,
        "viewportYRatio": 1 / 3,
        "contentX": 120,
        "contentY": 80,
        "contentWidth": 640,
        "contentHeight": 480,
        "contentXRatio": 0.1875,
        "contentYRatio": 1 / 6,
        "devicePixelRatio": 1.25,
        "orientation": "landscape",
        "courseType": "matching",
        "courseId": 3,
        "courseItemId": 11,
        "questionId": "q-1",
        "target": {
            "tag": "button",
            "id": "choice-1",
            "role": "option",
            "dataAction": "choose",
            "targetType": "choose",
            "targetKey": "choose",
            "interactionKind": "task",
            "interactive": True,
            "text": "must-not-be-persisted",
        },
    }
    value.update(overrides)
    return value


def test_click_details_are_bounded_and_do_not_keep_dom_text():
    result = validate_click_details(_click_details())

    assert result["schemaVersion"] == "child-screen-click-v1"
    assert result["viewportXRatio"] == 0.25
    assert result["target"]["interactionKind"] == "task"
    assert "text" not in result["target"]


@pytest.mark.parametrize(
    ("patch", "error"),
    [
        ({"captureEvent": "click"}, "capture_event_invalid"),
        ({"pointerType": "unknown"}, "pointer_type_invalid"),
        ({"viewportXRatio": 1.5}, "viewport_x_ratio_out_of_range"),
        ({"pointerType": "mouse", "button": 2}, "mouse_button_not_primary"),
    ],
)
def test_click_details_reject_invalid_or_duplicate_browser_semantics(patch, error):
    with pytest.raises(ValueError, match=error):
        validate_click_details(_click_details(**patch))


def test_click_route_uses_server_owned_contract(monkeypatch):
    from app.routes import interaction_timeline as routes

    calls = []
    monkeypatch.setattr(
        routes,
        "record_audit_event",
        lambda event, **kwargs: calls.append((event, kwargs)) or {"event": event},
    )
    monkeypatch.setattr(
        routes,
        "add_session_offset",
        lambda details, **_kwargs: {**details, "sessionOffsetMs": 4567.0},
    )
    app = Flask("screen-click-route")
    app.register_blueprint(routes.interaction_timeline_bp)

    response = app.test_client().post(
        "/api/v2/timeline/events",
        json={
            "event": CLICK_EVENT,
            "actor": "spoofed",
            "source": "spoofed",
            "category": "spoofed",
            "trainingSessionId": "training-1",
            "sessionId": "media-1",
            "questionId": "q-1",
            "clientTimestamp": 1000,
            "details": _click_details(),
        },
    )

    assert response.status_code == 201
    event, kwargs = calls[0]
    assert event == CLICK_EVENT
    assert kwargs["actor"] == "child"
    assert kwargs["source"] == "child_ui"
    assert kwargs["category"] == "child_interaction"
    assert kwargs["modality"] == "screen"
    assert kwargs["details"]["sessionOffsetMs"] == 4567.0


def test_click_route_rejects_out_of_range_coordinates(monkeypatch):
    from app.routes import interaction_timeline as routes

    monkeypatch.setattr(
        routes,
        "record_audit_event",
        lambda *_args, **_kwargs: pytest.fail("invalid click must not be recorded"),
    )
    app = Flask("screen-click-invalid-route")
    app.register_blueprint(routes.interaction_timeline_bp)
    response = app.test_client().post(
        "/api/v2/timeline/events",
        json={
            "event": CLICK_EVENT,
            "trainingSessionId": "training-1",
            "details": _click_details(viewportX=1500),
        },
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "viewport_x_out_of_range"


def test_click_summary_distinguishes_zero_from_not_collected_and_deduplicates():
    not_collected = summarize_screen_interaction([])
    assert not_collected["tracking_status"] == "NOT_COLLECTED"
    assert not_collected["total_click_count"] is None

    rows = [
        {
            "event": "child_screen_tracking_started",
            "serverEpochMs": 900,
            "details": {},
        },
        {
            "event": "question_presented",
            "questionId": "q-1",
            "serverEpochMs": 1000,
        },
        {
            "event": CLICK_EVENT,
            "eventId": "event-1",
            "questionId": "q-1",
            "serverEpochMs": 1250,
            "details": {
                "clickId": "click-1",
                "pointerType": "touch",
                "pageType": "interactive_iframe",
                "sessionOffsetMs": 5000,
                "target": {"interactionKind": "task"},
            },
        },
        {
            "event": CLICK_EVENT,
            "eventId": "event-duplicate",
            "questionId": "q-1",
            "serverEpochMs": 1260,
            "details": {
                "clickId": "click-1",
                "pointerType": "touch",
                "pageType": "interactive_iframe",
                "target": {"interactionKind": "task"},
            },
        },
        {
            "event": CLICK_EVENT,
            "eventId": "event-2",
            "questionId": "q-1",
            "serverEpochMs": 1400,
            "details": {
                "clickId": "click-2",
                "pointerType": "mouse",
                "pageType": "child_main",
                "sessionOffsetMs": 5150,
                "target": {"interactionKind": "blank"},
            },
        },
    ]
    summary = summarize_screen_interaction(rows)

    assert summary["tracking_status"] == "READY"
    assert summary["total_click_count"] == 2
    assert summary["task_click_count"] == 1
    assert summary["blank_click_count"] == 1
    assert summary["duplicate_clicks_ignored"] == 1
    assert summary["clicks_by_pointer_type"] == {"mouse": 1, "touch": 1}
    assert summary["clicks_by_question"]["q-1"]["first_click_latency_ms"] == 250


def test_session_summary_model_keeps_screen_interaction_for_disk_roundtrip():
    value = SessionBehaviorSummary(
        training_session_id="training-1",
        screen_interaction={"tracking_status": "READY", "total_click_count": 3},
    ).to_dict()
    assert value["screen_interaction"]["total_click_count"] == 3


def test_behavior_finalize_writes_session_and_question_click_summaries(
    tmp_path, monkeypatch
):
    from app.behavior import screen_interaction
    from app.behavior.store import BehaviorStore
    from app.behavior.timeline import BehaviorTimeline

    aggregate = {
        "schema_version": "screen-interaction-summary-v1",
        "tracking_status": "READY",
        "available": True,
        "total_click_count": 2,
        "task_click_count": 1,
        "blank_click_count": 1,
        "other_click_count": 0,
        "clicks_by_pointer_type": {"touch": 2},
        "clicks_by_page": {"interactive_iframe": 2},
        "clicks_by_question": {
            "q-1": {
                "total_click_count": 2,
                "task_click_count": 1,
                "blank_click_count": 1,
                "other_click_count": 0,
                "first_click_latency_ms": 250,
                "first_session_offset_ms": 5000,
            }
        },
        "first_session_offset_ms": 5000,
        "tracking_started_server_epoch_ms": 900,
        "duplicate_clicks_ignored": 0,
    }
    monkeypatch.setattr(
        screen_interaction,
        "load_screen_interaction_summary",
        lambda _training_id, _runtime_session_id=None: aggregate,
    )
    store = BehaviorStore(tmp_path / "behavior")
    timeline = BehaviorTimeline(store)
    training = timeline.open_training(student_id=1)
    timeline.open_window(
        training.training_session_id,
        question_id="q-1",
        course_type="matching",
    )

    summary = timeline.finalize(training.training_session_id)
    saved_window = store.get_window(training.training_session_id, "q-1")

    assert summary.screen_interaction["total_click_count"] == 2
    assert saved_window is not None
    assert saved_window.analysis_summary["screen_interaction"] == {
        "schema_version": "screen-interaction-window-v1",
        "tracking_status": "READY",
        "available": True,
        "total_click_count": 2,
        "task_click_count": 1,
        "blank_click_count": 1,
        "other_click_count": 0,
        "first_click_latency_ms": 250,
        "first_session_offset_ms": 5000,
    }
    disk_summary = store.get_summary(training.training_session_id)
    assert disk_summary is not None
    assert disk_summary.screen_interaction["total_click_count"] == 2


def test_child_tracker_covers_main_and_committed_iframe_without_text_capture():
    root = Path(__file__).resolve().parents[1]
    child = (root / "static/js/child.js").read_text(encoding="utf-8")
    tracker = (root / "static/js/child_screen_clicks.js").read_text(encoding="utf-8")

    assert "startChildScreenClickTracking" in child
    assert 'addEventListener("pointerdown"' in tracker
    assert "event.isTrusted !== true" in tracker
    assert 'frame.id !== "interactive"' in tracker
    assert 'pageContextActive !== "true"' in tracker
    assert "contentDocument" in tracker
    assert "innerText" not in tracker
    assert ".textContent" not in tracker
