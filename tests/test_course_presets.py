"""Course presets stay atomic, ordered and shared by Server/teacher UI."""

import json
from pathlib import Path

import pytest
from flask import Flask

from app.routes import config_content
from app.storage.repositories.course_preset_store import JsonCoursePresetStore
from database.models import Course, CourseItem, CourseType, db


ROOT = Path(__file__).resolve().parents[1]


def test_course_preset_store_preserves_order_default_and_immutable_ids(tmp_path):
    path = tmp_path / "course_presets.json"
    store = JsonCoursePresetStore(path)

    first = store.create(
        name="基础评估",
        description="先命名后配对",
        course_ids=[9, 2, 9],
    )
    assert first["courseIds"] == [9, 2]
    assert store.get_document()["defaultPresetId"] == first["id"]

    updated = store.update(
        first["id"],
        name="基础评估（新版）",
        description="顺序调整",
        course_ids=[2, 9],
    )
    assert updated["id"] == first["id"]
    assert updated["courseIds"] == [2, 9]

    second = store.create(
        name="干预方案",
        description="",
        course_ids=[11],
        is_default=True,
    )
    assert store.get_document()["defaultPresetId"] == second["id"]
    store.delete(second["id"])
    assert store.get_document()["defaultPresetId"] == first["id"]
    assert json.loads(path.read_text(encoding="utf-8"))["schemaVersion"] == 1


def test_course_preset_store_fails_closed_on_corrupt_document(tmp_path):
    path = tmp_path / "course_presets.json"
    original = '{"schemaVersion": 99, "presets": []}'
    path.write_text(original, encoding="utf-8")

    store = JsonCoursePresetStore(path)
    with pytest.raises(ValueError, match="invalid_course_preset_document"):
        store.create(name="不能覆盖", description="", course_ids=[2])
    assert path.read_text(encoding="utf-8") == original


@pytest.fixture()
def course_preset_client(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    app.register_blueprint(config_content.config_content_bp)
    monkeypatch.setattr(
        config_content,
        "_COURSE_PRESET_STORE",
        JsonCoursePresetStore(tmp_path / "course_presets.json"),
    )
    with app.app_context():
        db.create_all()
        pairing_type = CourseType(id=1, name="配对")
        ordering_type = CourseType(id=2, name="排序")
        naming_type = CourseType(id=3, name="命名")
        mimic_type = CourseType(id=4, name="模仿")
        db.session.add_all([pairing_type, ordering_type, naming_type, mimic_type])
        db.session.add_all([
            Course(id=1, course_type_id=4, title="模仿课程"),
            Course(id=9, course_type_id=1, title="配对课程"),
            Course(id=10, course_type_id=2, title="排序课程"),
            Course(id=12, course_type_id=1, title="空课程"),
            Course(id=13, course_type_id=3, title="历史命名课程"),
        ])
        db.session.flush()
        db.session.add_all([
            CourseItem(course_id=1, name="举起双手", type="image"),
            CourseItem(course_id=9, name="相同图片", type="interactive"),
            CourseItem(course_id=10, name="大小排序", type="interactive"),
            CourseItem(course_id=13, name="苹果", type="image"),
        ])
        db.session.commit()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def test_course_preset_api_crud_and_teacher_catalog(course_preset_client):
    empty = course_preset_client.get("/api/config/course-presets").get_json()
    assert empty["success"] is True
    assert empty["presets"] == []
    assert empty["enabledCourseTypes"] == ["mimic", "pairing", "ordering"]
    assert [course["id"] for course in empty["courseCatalog"]] == [1, 9, 10, 12]

    response = course_preset_client.post("/api/config/course-presets", json={
        "name": "课堂默认",
        "description": "按课堂顺序",
        "courseIds": [10, 9],
        "isDefault": True,
    })
    assert response.status_code == 201
    created = response.get_json()
    preset_id = created["preset"]["id"]
    assert created["defaultPresetId"] == preset_id
    assert created["preset"]["courseIds"] == [10, 9]
    assert created["preset"]["available"] is True
    assert [course["id"] for course in created["preset"]["courses"]] == [10, 9]

    updated = course_preset_client.put(f"/api/config/course-presets/{preset_id}", json={
        "name": "课堂默认",
        "description": "调整顺序",
        "courseIds": [9, 10],
        "isDefault": False,
    })
    assert updated.status_code == 200
    assert updated.get_json()["preset"]["courseIds"] == [9, 10]
    assert updated.get_json()["defaultPresetId"] == preset_id

    rejected = course_preset_client.post("/api/config/course-presets", json={
        "name": "无效方案",
        "courseIds": [12],
    })
    assert rejected.status_code == 400
    assert rejected.get_json()["error"] == "课程没有课点: 12"

    disabled = course_preset_client.post("/api/config/course-presets", json={
        "name": "历史课程方案",
        "courseIds": [13],
    })
    assert disabled.status_code == 400
    assert disabled.get_json()["error"] == "Demo 机仅允许模仿、配对和排序课程: 13"

    deleted = course_preset_client.delete(f"/api/config/course-presets/{preset_id}")
    assert deleted.status_code == 200
    assert deleted.get_json()["presets"] == []
    assert deleted.get_json()["defaultPresetId"] is None


def test_course_preset_surfaces_are_wired_to_shared_api():
    teacher = (ROOT / "teacher_frontend" / "components" / "CourseSelectionPage.tsx").read_text(encoding="utf-8")
    server = (ROOT / "templates" / "server" / "config.html").read_text(encoding="utf-8")
    shell = (ROOT / "static" / "js" / "config_center.js").read_text(encoding="utf-8")

    assert "QUICK_PRESET_COURSE_IDS" not in teacher
    assert "fetch('/api/config/course-presets')" in teacher
    assert 'id="course-preset"' in teacher
    assert 'data-view="presets"' in server
    assert 'id="course-preset-selected"' in server
    assert "loadCoursePresetLibrary" in shell


def test_quick_assessment_uses_direct_course_checkboxes_for_every_preset_course():
    teacher = (ROOT / "teacher_frontend" / "components" / "CourseSelectionPage.tsx").read_text(
        encoding="utf-8"
    )

    assert "compactQuickAssessmentCourse" in teacher
    assert "mode === 'assessment'" in teacher
    assert "(viewedPreset || selectedPreset)?.courseIds.includes(course.id)" in teacher
    assert "keepQuickAssessmentLayout" in teacher
    assert "selectedPreset?.courseIds.includes(courseId)" in teacher
    assert "直接勾选整课，无需逐项打开" in teacher
    assert "勾选后自动使用本课程全部" in teacher
    assert "course.items.length > 0 && !compactQuickAssessmentCourse" in teacher
