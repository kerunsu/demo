import json

import pytest

from app.behavior.models import QuestionWindow, TrainingSessionRecord
from app.behavior.service import BehaviorService
from app.behavior.store import BehaviorStore
from app.behavior.timeline import BehaviorTimeline


def make_service(tmp_path):
    store = BehaviorStore(tmp_path / "behavior")
    service = BehaviorService()
    service.store = store
    service.timeline = BehaviorTimeline(store)
    store.save_training(TrainingSessionRecord(
        training_session_id="training-1",
        student_id=1,
        current_question_id="question-1",
    ))
    store.save_window(QuestionWindow(
        training_session_id="training-1",
        question_id="question-1",
        course_id=8,
        course_type="pairing",
        task_metrics={
            "matching": {"accuracy": 80, "avg_response_ms": 3000},
        },
    ))
    return service, store


def test_teacher_rating_is_idempotent_and_preserves_task_metrics(tmp_path):
    service, store = make_service(tmp_path)

    service.record_teacher_rating(
        "training-1", "question-1", rating=3, response_ms=3500,
        advance_source="manual",
    )
    service.record_teacher_rating(
        "training-1", "question-1", rating=5, response_ms=3200,
        advance_source="matching_end",
    )

    window = store.get_window("training-1", "question-1")
    assert window.task_metrics["matching"]["accuracy"] == 80
    assert window.task_metrics["teacher_rating"]["rating"] == 5
    assert window.task_metrics["teacher_rating"]["normalized_score"] == 100
    assert window.task_metrics["teacher_rating"]["response_ms"] == 3200
    assert window.task_metrics["teacher_rating"]["advance_source"] == "matching_end"

    saved = json.loads((
        tmp_path / "behavior" / "training-1" / "windows" / "question-1.json"
    ).read_text(encoding="utf-8"))
    assert saved["task_metrics"]["matching"]["accuracy"] == 80
    assert saved["task_metrics"]["teacher_rating"]["rating"] == 5


@pytest.mark.parametrize("rating", [0, 6, 2.5, True])
def test_teacher_rating_rejects_invalid_values(tmp_path, rating):
    service, _ = make_service(tmp_path)
    with pytest.raises(ValueError, match="rating_must_be_integer_1_to_5"):
        service.record_teacher_rating("training-1", "question-1", rating=rating)


def test_teacher_rating_rejects_cross_window_reference(tmp_path):
    service, _ = make_service(tmp_path)
    with pytest.raises(ValueError, match="question_window_not_found"):
        service.record_teacher_rating("training-1", "another-question", rating=4)


def test_invalid_response_time_does_not_block_rating(tmp_path):
    service, store = make_service(tmp_path)
    service.record_teacher_rating(
        "training-1", "question-1", rating=4, response_ms=99_000_000,
    )
    rating = store.get_window("training-1", "question-1").task_metrics["teacher_rating"]
    assert rating["rating"] == 4
    assert rating["response_ms"] is None
