from app.sockets.events import _build_child_session_forward


def test_freeze_course_frame_target_is_exact_child_session_room():
    payload, room = _build_child_session_forward({
        "sessionId": "runtime-freeze",
        "trainingSessionId": "training-freeze",
        "questionId": "question-freeze",
    })

    assert room == "session_runtime-freeze_child"
    assert payload["sessionId"] == "runtime-freeze"
    assert payload["session_id"] == "runtime-freeze"
    assert payload["trainingSessionId"] == "training-freeze"
    assert payload["questionId"] == "question-freeze"


def test_freeze_course_frame_without_session_is_rejected():
    assert _build_child_session_forward({
        "trainingSessionId": "training-freeze",
        "questionId": "question-freeze",
    }) is None
