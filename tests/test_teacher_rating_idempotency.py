from types import SimpleNamespace

from app.sockets import events


def _clear_rating_request(request_id):
    with events._teacher_rating_lock:
        events._teacher_rating_cache.pop(request_id, None)


def test_teacher_rating_ack_echoes_request_and_writes_once():
    request_id = "rating-once-1"
    _clear_rating_request(request_id)
    calls = []

    class _Behavior:
        def record_teacher_rating(self, training_id, question_id, **kwargs):
            calls.append((training_id, question_id, kwargs))
            return SimpleNamespace(
                question_id=question_id,
                task_metrics={
                    "teacher_rating": {
                        "rating": kwargs["rating"],
                        "normalized_score": 1.0,
                        "updated_at": "now",
                    }
                },
            )

    payload = {
        "requestId": request_id,
        "trainingSessionId": "training-1",
        "questionId": "question-1",
        "rating": 5,
    }
    first = events._process_teacher_rating(
        payload,
        behavior_service=_Behavior(),
    )
    replay = events._process_teacher_rating(
        payload,
        behavior_service=_Behavior(),
    )

    assert first["success"] is True
    assert first["requestId"] == request_id
    assert replay["requestId"] == request_id
    assert replay["idempotentReplay"] is True
    assert len(calls) == 1
    _clear_rating_request(request_id)


def test_teacher_rating_failure_is_correlated_and_idempotent():
    request_id = "rating-failure-1"
    _clear_rating_request(request_id)
    calls = []

    class _Behavior:
        def record_teacher_rating(self, *args, **kwargs):
            calls.append((args, kwargs))
            raise RuntimeError("rating store unavailable")

    payload = {
        "requestId": request_id,
        "trainingSessionId": "training-2",
        "questionId": "question-2",
        "rating": 4,
    }
    first = events._process_teacher_rating(
        payload,
        behavior_service=_Behavior(),
    )
    replay = events._process_teacher_rating(
        payload,
        behavior_service=_Behavior(),
    )

    assert first["success"] is False
    assert first["requestId"] == request_id
    assert first["error"] == "rating store unavailable"
    assert replay["idempotentReplay"] is True
    assert len(calls) == 1
    _clear_rating_request(request_id)


def test_teacher_rating_request_id_cannot_be_reused_for_other_payload():
    request_id = "rating-conflict-1"
    _clear_rating_request(request_id)

    class _Behavior:
        def record_teacher_rating(self, training_id, question_id, **kwargs):
            return SimpleNamespace(
                question_id=question_id,
                task_metrics={
                    "teacher_rating": {
                        "rating": kwargs["rating"],
                        "normalized_score": 0.5,
                        "updated_at": "now",
                    }
                },
            )

    first = events._process_teacher_rating(
        {
            "requestId": request_id,
            "trainingSessionId": "training-3",
            "questionId": "question-3",
            "rating": 3,
        },
        behavior_service=_Behavior(),
    )
    conflict = events._process_teacher_rating(
        {
            "requestId": request_id,
            "trainingSessionId": "training-3",
            "questionId": "question-3",
            "rating": 1,
        },
        behavior_service=_Behavior(),
    )

    assert first["success"] is True
    assert conflict == {
        "success": False,
        "trainingSessionId": "training-3",
        "questionId": "question-3",
        "requestId": request_id,
        "error": "request_id_conflict",
    }
    _clear_rating_request(request_id)
