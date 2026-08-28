import json
from pathlib import Path

from app.course_scope import (
    enabled_course_dimensions,
    enabled_course_types,
    filter_course_payloads,
)
from app.report.scoring import compute_dimensions, load_scoring_config
from app.report.service import ReportService


ROOT = Path(__file__).resolve().parents[1]


def test_demo_course_scope_includes_naming_ordering_and_fails_closed(tmp_path):
    assert enabled_course_types() == ("naming", "ordering")
    assert enabled_course_dimensions() == (
        "attention", "expressiveLanguage", "receptiveLanguage", "ordering"
    )

    missing = tmp_path / "missing.json"
    assert enabled_course_types(missing) == ("naming", "ordering")

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text('{"schemaVersion": 99, "enabledCourseTypes": ["naming"]}', encoding="utf-8")
    assert enabled_course_types(corrupt) == ("naming", "ordering")

    unknown = tmp_path / "unknown.json"
    unknown.write_text('{"schemaVersion": 1, "enabledCourseTypes": ["future-course"]}', encoding="utf-8")
    assert enabled_course_types(unknown) == ("naming", "ordering")

    expanded = tmp_path / "expanded.json"
    expanded.write_text(
        '{"schemaVersion": 1, "enabledCourseTypes": ["naming", "ordering", "mimic"]}',
        encoding="utf-8",
    )
    assert enabled_course_types(expanded) == ("naming", "ordering")


def test_demo_course_filter_accepts_naming_and_ordering_alias_only():
    filtered = filter_course_payloads([
        {"id": 1, "type": "naming"},
        {"id": 2, "type": "imitation"},
        {"id": 9, "type": "matching"},
        {"id": 10, "type": "sequencing"},
        {"id": 11, "type": "social"},
    ])
    assert [item["id"] for item in filtered] == [1, 10]


def test_runtime_scoring_config_projects_only_demo_courses_and_dimensions():
    cfg = load_scoring_config()
    assert cfg["enabled_course_types"] == ["naming", "ordering"]
    assert cfg["enabled_dimension_keys"] == [
        "attention", "expressiveLanguage", "receptiveLanguage", "ordering"
    ]

    result = compute_dimensions({
        "attention": {"avg_score": 80},
        "language": {},
        "task": {},
        "windows": [
            {
                "course_type": "mimic",
                "task_metrics": {
                    "teacher_rating": {"rating": 4, "normalized_score": 80, "response_ms": 2500},
                },
            },
            {
                "course_type": "pairing",
                "task_metrics": {
                    "matching": {"accuracy": 80, "avg_response_ms": 3000, "answered": 5},
                    "teacher_rating": {"rating": 4, "normalized_score": 80, "response_ms": 3000},
                },
            },
            {
                "course_type": "ordering",
                "task_metrics": {
                    "sequencing": {"accuracy": 70, "avg_response_ms": 4000, "answered": 5},
                    "teacher_rating": {"rating": 4, "normalized_score": 80, "response_ms": 4000},
                },
            },
            {
                "course_type": "naming",
                "task_metrics": {
                    "teacher_rating": {"rating": 5, "normalized_score": 100, "response_ms": 1000},
                },
            },
            {
                "course_type": "naming",
                "task_metrics": {
                    "teacher_rating": {"rating": 4, "normalized_score": 80, "response_ms": 1200},
                },
            },
        ],
    }, cfg, soft=False)

    assert set(result["courseScores"]) == {"naming", "ordering"}
    assert set(result["dimensions"]) == {
        "attention", "expressiveLanguage", "receptiveLanguage", "ordering"
    }
    assert [item["courseType"] for item in result["courseEvaluations"]] == ["naming", "ordering"]
    assert set(result["teacherRatingCounts"]) == {"naming", "ordering"}

    report = ReportService()._build_report("demo-training", {
        "student_id": 1,
        "attention": {"avg_score": 80, "curve": []},
        "language": {},
        "emotion": {},
        "task": {},
        "windows": [
            {
                "course_type": "naming",
                "task_metrics": {
                    "teacher_rating": {"rating": 4, "normalized_score": 80, "response_ms": 3000},
                },
            },
            {
                "course_type": "naming",
                "task_metrics": {
                    "teacher_rating": {"rating": 4, "normalized_score": 80, "response_ms": 2500},
                },
            },
        ],
    }, soft=False)
    assert report["courseScope"]["enabledCourseTypes"] == ["naming", "ordering"]
    assert set(report["courseScores"]) == {"naming", "ordering"}
    assert set(report["dimensions"]) == {
        "attention", "expressiveLanguage", "receptiveLanguage", "ordering"
    }


def test_seeded_demo_preset_contains_naming_and_ordering_courses():
    document = json.loads((ROOT / "config" / "course_presets.json").read_text(encoding="utf-8"))
    assert document["schemaVersion"] == 3
    for mode, preset_id in document["defaultPresetIds"].items():
        default = next(item for item in document["presets"] if item["id"] == preset_id)
        assert default["mode"] == mode
        assert [item["courseType"] for item in default["courseSelections"]] == ["naming", "ordering"]
        assert default["courseSelections"][1] == {"courseType": "ordering", "itemIds": [80]}


def test_teacher_and_server_report_sources_expose_only_demo_course_fields():
    teacher = (ROOT / "teacher_frontend" / "components" / "ReportPage.tsx").read_text(encoding="utf-8")
    dimensions = teacher[teacher.index("const DIMENSIONS"):teacher.index("const COURSE_TYPES")]
    courses = teacher[teacher.index("const COURSE_TYPES"):teacher.index("const API_BASE")]
    assert "'expressiveLanguage'" in dimensions and "'receptiveLanguage'" in dimensions
    assert "'attention'" in dimensions and "'ordering'" in dimensions
    assert "'mimic'" not in courses and "'naming'" in courses and "'ordering'" in courses
    assert "'pairing'" not in courses and "'onomatopoeia'" not in courses

    server = (ROOT / "static" / "js" / "server_report_edit.js").read_text(encoding="utf-8")
    fields = server[server.index("const DIM_KEYS"):server.index("const els")]
    assert '["attention", "注意力参与"]' in fields
    assert '["expressiveLanguage", "表达性语言"]' in fields
    assert '["receptiveLanguage", "接受性语言"]' in fields
    assert '["ordering", "排序"]' in fields
    assert '["mimic", "模仿"]' not in fields
    assert '["naming", "命名"]' in (server[server.index("const COURSE_KEYS"):server.index("const els")])


def test_production_course_route_filters_database_and_static_fallbacks():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    route = source[source.index("@app.route('/courses')"):source.index("# video_frame事件处理")]
    assert route.count("filter_course_payloads") == 2


def test_student_history_routes_hide_legacy_course_and_ability_rows():
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    student_routes = source[
        source.index('@app.route("/api/students/<int:student_id>", methods=["GET"])'):
        source.index("# ==================== 字典表相关API ====================")
    ]
    assert student_routes.count("_enabled_demo_course_labels()") >= 2
    assert student_routes.count("_enabled_demo_ability_labels()") >= 3
    assert "imitation_placeholder" not in student_routes

    dictionary_routes = source[
        source.index("# ==================== 字典表相关API ===================="):
        source.index("# ==================== 新架构初始化 ====================")
    ]
    assert "enabled_labels = _enabled_demo_course_labels()" in dictionary_routes
    assert "enabled_labels = _enabled_demo_ability_labels()" in dictionary_routes
