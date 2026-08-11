import pytest

from app.report.scoring import compute_dimensions


CFG = {
    "schema_version": "education-training-index-v2-teacher-rating",
    "score_boundary": "education_training_reference_only",
    "weights": {
        "attention": 20,
        "expressiveLanguage": 20,
        "receptiveLanguage": 20,
        "matching": 20,
        "ordering": 20,
    },
    "teacher_rating": {"scale": 20},
    "interactive_course": {
        "accuracy_weight": 0.75,
        "response_weight": 0.25,
        "objective_weight": 0.70,
        "teacher_weight": 0.30,
        "ideal_response_sec": 3,
        "slow_response_sec": 12,
    },
    "dimension_weights": {
        "receptive": {"pairing": 1, "ordering": 1, "naming": 1, "onomatopoeia": 1},
        "expressive": {"naming": 1, "onomatopoeia": 1},
        "attention": {"automatic": 0.7, "mimic_teacher": 0.3},
    },
    "course_weights": {"mimic": 1, "naming": 1, "onomatopoeia": 1, "pairing": 1, "ordering": 1},
    "grade_thresholds": {"excellent": 85, "good": 70, "fair": 55, "needs_support": 0},
}


def window(course_type, rating, response_ms, task_metrics=None):
    metrics = dict(task_metrics or {})
    metrics["teacher_rating"] = {
        "rating": rating,
        "normalized_score": rating * 20,
        "response_ms": response_ms,
    }
    return {"course_type": course_type, "task_metrics": metrics}


def test_v2_balances_five_course_types_and_builds_dimensions():
    summary = {
        "attention": {"avg_score": 90},
        "language": {},
        "task": {},
        "windows": [
            window("pairing", 4, 3000, {"matching": {"accuracy": 80, "avg_response_ms": 3000}}),
            window("ordering", 3, 12000, {"sequencing": {"accuracy": 60, "avg_response_ms": 12000}}),
            window("naming", 5, 4000),
            window("onomatopoeia", 4, 5000),
            window("mimic", 3, 6000),
        ],
    }

    result = compute_dimensions(summary, CFG, soft=False)

    assert result["courseScores"] == {
        "mimic": 60.0,
        "naming": 100.0,
        "onomatopoeia": 80.0,
        "pairing": 83.5,
        "ordering": 49.5,
    }
    assert result["overall"] == 74.6
    assert result["dimensions"]["attention"]["score"] == 81.0
    assert result["dimensions"]["expressiveLanguage"]["score"] == 90.0
    assert result["dimensions"]["receptiveLanguage"]["score"] == 78.2
    assert result["dimensions"]["matching"]["score"] == 83.5
    assert result["dimensions"]["ordering"]["score"] == 49.5
    assert result["taskPerformance"] == 76.0
    assert result["responseMetrics"]["avgResponseMs"] == 6000.0
    assert result["responseMetrics"]["sampleCount"] == 5


def test_missing_course_types_are_renormalized_not_scored_as_zero():
    summary = {
        "attention": {},
        "language": {},
        "task": {},
        "windows": [window("naming", 4, 4000), window("onomatopoeia", 2, 6000)],
    }
    result = compute_dimensions(summary, CFG, soft=False)
    assert result["overall"] == 60.0
    assert result["dimensions"]["expressiveLanguage"]["score"] == 60.0
    assert result["dimensions"]["receptiveLanguage"]["score"] == 60.0
    assert result["dimensions"]["matching"]["score"] is None
    assert result["responseMetrics"]["avgResponseMs"] == 5000.0


def test_historical_interactive_training_without_teacher_rating_still_scores():
    summary = {
        "attention": {"avg_score": 70},
        "language": {"avg_speech_ratio": 0.4, "total_word_count": 20},
        "task": {"matching_accuracy": 85},
        "windows": [{
            "course_type": "pairing",
            "task_metrics": {"matching": {"accuracy": 85, "avg_response_ms": 3000}},
        }],
    }
    result = compute_dimensions(summary, CFG, soft=False)
    assert result["courseScores"]["pairing"] == pytest.approx(88.8, abs=0.1)
    assert result["overall"] == pytest.approx(88.8, abs=0.1)
    assert "TEACHER_RATING_MISSING" in result["limitations"]
