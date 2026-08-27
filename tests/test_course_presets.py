"""Demo course presets keep exact items and independent mode defaults."""

import json
from pathlib import Path

import pytest
from flask import Flask

from app.routes import config_content
from app.storage.repositories.course_preset_store import JsonCoursePresetStore
from database.models import Course, CourseItem, CourseType, db


ROOT = Path(__file__).resolve().parents[1]


def test_course_preset_store_preserves_exact_items_and_mode_defaults(tmp_path):
    path = tmp_path / "course_presets.json"
    store = JsonCoursePresetStore(path)
    assessment = store.create(
        mode="assessment",
        name="Demo 评估",
        description="两门课程",
        course_selections=[
            {"courseType": "pairing", "itemIds": [79, 81, 79]},
            {"courseType": "ordering", "itemIds": [80]},
        ],
    )
    intervention = store.create(
        mode="intervention",
        name="Demo 干预",
        description="",
        course_selections=[{"courseType": "ordering", "itemIds": [80]}],
    )

    document = store.get_document()
    assert document["schemaVersion"] == 3
    assert document["defaultPresetIds"] == {
        "assessment": assessment["id"],
        "intervention": intervention["id"],
    }
    assert assessment["courseSelections"][0]["itemIds"] == [79, 81]

    updated = store.update(
        assessment["id"],
        mode="assessment",
        name="Demo 评估新版",
        description="顺序调整",
        course_selections=[
            {"courseType": "ordering", "itemIds": [80]},
            {"courseType": "pairing", "itemIds": [79]},
        ],
    )
    assert updated["id"] == assessment["id"]
    assert updated["courseSelections"][0]["courseType"] == "ordering"
    assert json.loads(path.read_text(encoding="utf-8"))["schemaVersion"] == 3


def test_course_preset_store_fails_closed_on_corrupt_document(tmp_path):
    path = tmp_path / "course_presets.json"
    original = '{"schemaVersion": 99, "presets": []}'
    path.write_text(original, encoding="utf-8")
    store = JsonCoursePresetStore(path)
    with pytest.raises(ValueError, match="invalid_course_preset_document"):
        store.create(
            mode="assessment",
            name="不能覆盖",
            description="",
            course_selections=[{"courseType": "pairing", "itemIds": [79]}],
        )
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
        db.session.add_all([
            CourseType(id=1, name="模仿"),
            CourseType(id=2, name="配对"),
            CourseType(id=3, name="排序"),
            CourseType(id=4, name="命名"),
        ])
        db.session.add_all([
            Course(id=1, course_type_id=1, title="模仿"),
            Course(id=9, course_type_id=2, title="配对"),
            Course(id=10, course_type_id=3, title="排序"),
            Course(id=13, course_type_id=4, title="历史命名"),
        ])
        db.session.flush()
        db.session.add_all([
            CourseItem(id=1, course_id=1, name="动作一", type="image"),
            CourseItem(id=2, course_id=1, name="动作二", type="image"),
            CourseItem(id=79, course_id=9, name="配对题", type="interactive"),
            CourseItem(id=80, course_id=10, name="排序题", type="interactive"),
            CourseItem(id=90, course_id=13, name="历史命名题", type="image"),
        ])
        db.session.commit()
        yield app.test_client()
        db.session.remove()
        db.drop_all()


def test_course_preset_api_accepts_demo_items_and_rejects_historical_type(course_preset_client):
    empty = course_preset_client.get("/api/config/course-presets").get_json()
    assert empty["defaultPresetIds"] == {"assessment": None, "intervention": None}
    assert empty["enabledCourseTypes"] == ["pairing", "ordering"]
    assert [course["id"] for course in empty["courseCatalog"]] == [9, 10]

    response = course_preset_client.post("/api/config/course-presets", json={
        "mode": "assessment",
        "name": "课堂默认",
        "courseSelections": [
            {"courseType": "pairing", "itemIds": [79]},
            {"courseType": "ordering", "itemIds": [80]},
        ],
        "isDefault": True,
    })
    assert response.status_code == 201
    created = response.get_json()
    assert created["preset"]["courseTypes"] == ["pairing", "ordering"]
    assert created["preset"]["courseIds"] == [9, 10]
    assert created["preset"]["available"] is True

    disabled = course_preset_client.post("/api/config/course-presets", json={
        "mode": "assessment",
        "name": "历史课程",
        "courseSelections": [{"courseType": "mimic", "itemIds": [2]}],
    })
    assert disabled.status_code == 400
    assert "Demo" in disabled.get_json()["error"]


def test_course_preset_surfaces_use_schema_v3_shared_api():
    teacher = (ROOT / "teacher_frontend/components/CourseSelectionPage.tsx").read_text(encoding="utf-8")
    server = (ROOT / "templates/server/config.html").read_text(encoding="utf-8")
    production = (ROOT / "app.py").read_text(encoding="utf-8")

    assert "fetch('/api/config/course-presets')" in teacher
    assert "preset.courseSelections" in teacher
    assert "selection.itemIds" in teacher
    assert "defaultPresetIds?.[presetMode]" in teacher
    assert 'id="course-preset-mode"' in server
    assert "no-store, no-cache, must-revalidate, max-age=0" in production
