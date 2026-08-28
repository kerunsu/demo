import pytest

from app.report.narrative import generate_narrative
from app.report.limitations_copy import translate_limitation
from app.report.scoring import compute_dimensions
from app.report.service import _sync_course_evaluations


CFG = {
    "schema_version": "education-training-index-v2-teacher-rating",
    "score_boundary": "education_training_reference_only",
    "weights": {
        "attention": 25,
        "expressiveLanguage": 25,
        "receptiveLanguage": 25,
        "ordering": 25,
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
        "attention": {"automatic": 1.0},
        "expressive": {"naming": 1.0},
        "receptive": {"naming": 1.0, "ordering": 1.0},
    },
    "course_weights": {"naming": 1, "ordering": 1},
    "enabled_course_types": ["naming", "ordering"],
    "enabled_dimension_keys": ["attention", "expressiveLanguage", "receptiveLanguage", "ordering"],
    "sample_sufficiency": {"minimum_effective_samples": {"naming": 2, "ordering": 5}},
    "grade_thresholds": {"excellent": 85, "good": 70, "fair": 55, "needs_support": 0},
}


def window(course_type, rating, response_ms, task_metrics=None):
    metrics = dict(task_metrics or {})
    objective_key = "sequencing" if course_type == "ordering" else None
    if objective_key and isinstance(metrics.get(objective_key), dict):
        metrics[objective_key] = {**metrics[objective_key]}
        metrics[objective_key].setdefault("answered", 5)
    metrics["teacher_rating"] = {
        "rating": rating,
        "normalized_score": rating * 20,
        "response_ms": response_ms,
    }
    return {"course_type": course_type, "task_metrics": metrics}


def test_v2_balances_two_demo_course_types_and_builds_dimensions():
    summary = {
        "attention": {"avg_score": 90},
        "language": {},
        "task": {},
        "windows": [
            window("naming", 4, 3000),
            window("naming", 5, 2500),
            window("ordering", 3, 12000, {"sequencing": {"accuracy": 60, "avg_response_ms": 12000}}),
            window("mimic", 3, 6000),
        ],
    }

    result = compute_dimensions(summary, CFG, soft=False)

    assert result["courseScores"] == {
        "naming": 90.0,
        "ordering": 49.5,
    }
    assert result["overall"] == 69.8
    assert result["dimensions"]["attention"]["score"] == 90.0
    assert result["dimensions"]["expressiveLanguage"]["score"] == 90.0
    assert result["dimensions"]["receptiveLanguage"]["score"] == 69.8
    assert result["dimensions"]["ordering"]["score"] == 49.5
    assert result["responseMetrics"]["sampleCount"] == 7


def test_missing_course_types_are_renormalized_not_scored_as_zero():
    summary = {
        "attention": {"avg_score": 80},
        "language": {},
        "task": {},
        "windows": [window("naming", 4, 4000), window("naming", 4, 3500)],
    }
    result = compute_dimensions(summary, CFG, soft=False)
    assert result["overall"] == 80.0
    assert result["dimensions"]["attention"]["score"] == 80.0
    assert result["dimensions"]["expressiveLanguage"]["score"] == 80.0
    assert result["dimensions"]["ordering"]["score"] is None
    assert result["responseMetrics"]["avgResponseMs"] == 3750.0
    evaluations = {item["courseType"]: item for item in result["courseEvaluations"]}
    assert evaluations["naming"]["status"] == "evaluated"
    assert evaluations["naming"]["score"] == 80.0
    assert evaluations["naming"]["targetScore"] == 70.0


def test_historical_interactive_training_without_teacher_rating_still_scores():
    summary = {
        "attention": {"avg_score": 70},
        "language": {"avg_speech_ratio": 0.4, "total_word_count": 20},
        "task": {"sequencing_accuracy": 85},
        "windows": [{
            "course_type": "ordering",
            "task_metrics": {"sequencing": {"accuracy": 85, "avg_response_ms": 3000, "answered": 5}},
        }],
    }
    result = compute_dimensions(summary, CFG, soft=False)
    assert result["courseScores"]["ordering"] == pytest.approx(88.8, abs=0.1)
    assert result["overall"] == pytest.approx(88.8, abs=0.1)
    assert "TEACHER_RATING_MISSING" in result["limitations"]


def test_interactive_score_stays_provisional_below_minimum_sample_count():
    summary = {
        "attention": {"avg_score": 70},
        "language": {},
        "task": {},
        "windows": [window(
            "ordering",
            4,
            3000,
            {"sequencing": {"accuracy": 80, "avg_response_ms": 3000, "answered": 2}},
        )],
    }
    result = compute_dimensions(summary, CFG, soft=False)
    ordering = next(item for item in result["courseEvaluations"] if item["courseType"] == "ordering")

    assert result["overall"] is None
    assert result["courseScores"]["ordering"] is None
    assert ordering["status"] == "insufficient_data"
    assert ordering["provisionalScore"] == 83.5
    assert ordering["validSampleCount"] == 2
    assert ordering["requiredSampleCount"] == 5
    assert ordering["contributesToOverall"] is False
    assert "COURSE_SAMPLE_INSUFFICIENT" in result["limitations"]


def test_narrative_recommendations_are_evidence_linked_even_when_scores_are_high():
    summary = {
        "attention": {"avg_score": 90},
        "language": {},
        "task": {},
        "windows": [
            window("naming", 5, 2500),
            window("naming", 5, 2500),
            window("ordering", 5, 3000, {"sequencing": {"accuracy": 100, "avg_response_ms": 3000}}),
        ],
    }
    scored = compute_dimensions(summary, CFG, soft=False)
    narrative = generate_narrative(scored, provider="rule")

    assert narrative["recommendations"]
    assert "保持节奏" not in str(narrative)
    first = narrative["recommendations"][0]
    assert first["priority"].startswith("巩固")
    assert "表现为" in first["evidence"]
    assert "%" in first["evidence"]
    assert first["practice"]
    assert first["why"]
    assert first["progressCheck"]
    assert "已完成 2/2" in narrative["summary"]["dataCompleteness"]
    assert narrative["headline"]
    assert list(narrative["overview"]) == ["overall", "stable", "attention", "boundary"]


def test_narrative_uses_percentage_gap_for_demo_ordering_course():
    summary = {
        "attention": {"avg_score": 74, "curve": [{"score": 80}, {"score": 50}]},
        "language": {},
        "task": {},
        "windows": [window("ordering", 3, 5000, {"sequencing": {"accuracy": 60, "avg_response_ms": 5000}})],
    }
    scored = compute_dimensions(summary, CFG, soft=False)
    scored["attentionCurve"] = summary["attention"]["curve"]
    narrative = generate_narrative(scored, provider="rule")

    recommendation = narrative["recommendations"][0]
    assert "%" in recommendation["evidence"]
    assert "个百分点" in recommendation["evidence"]
    assert recommendation["practice"]
    assert recommendation["progressCheck"]
    assert narrative["overview"]["overall"].startswith("本次综合表现为")
    assert "年龄常模" in narrative["overview"]["boundary"]


def test_unknown_limitation_code_never_reaches_teacher_copy():
    assert translate_limitation("SEQUENCING_DATA_MISSING") == "排序课程未形成足够的有效结果"
    assert translate_limitation("FUTURE_INTERNAL_CODE") == "部分过程数据未形成有效结果，相关项目未作推断"


def test_manual_course_score_sync_updates_teacher_chart_without_faking_missing_zero():
    report = {
        "courseGoalScore": 70,
        "courseScores": {"mimic": None, "naming": 84, "onomatopoeia": None, "pairing": 61, "ordering": None},
        "courseEvaluations": [
            {"courseType": "ordering", "status": "insufficient_data", "itemCount": 2, "teacherRatingCount": 0},
        ],
    }
    _sync_course_evaluations(report)
    evaluations = {item["courseType"]: item for item in report["courseEvaluations"]}

    assert evaluations["naming"]["gapToTarget"] == 14.0
    assert evaluations["ordering"]["score"] is None
    assert evaluations["ordering"]["status"] == "insufficient_data"
    assert set(evaluations) == {"naming", "ordering"}
    assert set(report["courseScores"]) == {"naming", "ordering"}


def test_teacher_report_source_hides_internal_identifiers_and_formula_version():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "teacher_frontend/components/ReportPage.tsx"
    ).read_text(encoding="utf-8")
    assert "trainingSessionId.slice" not in source
    assert "公式版本" not in source
    assert "formulaVersion" not in source
    assert "courseStatusText(course)" in source
    assert "未评估或数据不足不会按 0 分计入综合表现" in source
    assert "核心能力百分比柱状图" in source
    assert "训练参考目标" in source
    assert "个百分点" in source
    assert "radar" not in source.lower()
    assert "teacherFriendlyLimitation" in source
    assert "legacySingle" in source


def test_server_report_editor_preserves_unchanged_structured_recommendations():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "static/js/server_report_edit.js"
    ).read_text(encoding="utf-8")
    assert "...original" in source
    assert "body !== String(original.body || \"\")" in source
    assert "parseRecommendationBody" in source
