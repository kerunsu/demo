import pytest

from app.report.narrative import generate_narrative
from app.report.limitations_copy import translate_limitation
from app.report.scoring import compute_dimensions
from app.report.service import _sync_course_evaluations


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
    evaluations = {item["courseType"]: item for item in result["courseEvaluations"]}
    assert evaluations["naming"]["status"] == "evaluated"
    assert evaluations["naming"]["score"] == 80.0
    assert evaluations["pairing"]["status"] == "not_evaluated"
    assert evaluations["pairing"]["score"] is None
    assert evaluations["pairing"]["targetScore"] == 70.0


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


def test_narrative_recommendations_are_evidence_linked_even_when_scores_are_high():
    summary = {
        "attention": {"avg_score": 90},
        "language": {},
        "task": {},
        "windows": [
            window("naming", 5, 3000),
            window("pairing", 5, 3000, {"matching": {"accuracy": 100, "avg_response_ms": 3000}}),
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
    assert "已完成 2/5" in narrative["summary"]["dataCompleteness"]
    assert narrative["headline"]
    assert list(narrative["overview"]) == ["overall", "stable", "attention", "boundary"]


def test_narrative_uses_percentage_gap_and_vocal_imitation_recommendation():
    summary = {
        "attention": {"avg_score": 74, "curve": [{"score": 80}, {"score": 50}]},
        "language": {},
        "task": {},
        "windows": [window("onomatopoeia", 3, 5000)],
    }
    scored = compute_dimensions(summary, CFG, soft=False)
    scored["attentionCurve"] = summary["attention"]["curve"]
    narrative = generate_narrative(scored, provider="rule")

    recommendation = narrative["recommendations"][0]
    assert "60.0%" in recommendation["evidence"]
    assert "10.0 个百分点" in recommendation["evidence"]
    assert "模仿发声" in recommendation["practice"]
    assert "图片选择" in recommendation["progressCheck"]
    assert "图片配对" not in str(recommendation)
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

    assert evaluations["pairing"]["gapToTarget"] == -9.0
    assert evaluations["ordering"]["score"] is None
    assert evaluations["ordering"]["status"] == "insufficient_data"
    assert set(evaluations) == {"mimic", "pairing", "ordering"}
    assert evaluations["mimic"]["score"] is None
    assert evaluations["mimic"]["status"] == "not_evaluated"
    assert set(report["courseScores"]) == {"mimic", "pairing", "ordering"}


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
    assert "未参加课程不按 0 分处理" in source
    assert "核心能力百分比柱状图" in source
    assert "课程参考目标" in source
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
