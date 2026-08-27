from __future__ import annotations

from pathlib import Path

import yaml


def _isolated_library(monkeypatch, tmp_path: Path):
    from app.dialogue import phrase_library

    path = tmp_path / "dialogue_phrase_selection.yaml"
    monkeypatch.setattr(phrase_library, "OVERLAY_PATH", path)
    return phrase_library, path


def test_selection_limits_runtime_pool_by_course(monkeypatch, tmp_path):
    from app.dialogue import phrases

    library, _path = _isolated_library(monkeypatch, tmp_path)
    base = phrases.base_lines_for("question", "naming")
    chosen = base[:2]

    library.set_enabled("question", "naming", chosen)

    assert library.effective_lines(base, "question", "naming") == chosen
    assert library.enabled_lines("question", "pairing") is None


def test_custom_phrase_is_persisted_and_auto_selected(monkeypatch, tmp_path):
    from app.dialogue import phrases

    library, path = _isolated_library(monkeypatch, tmp_path)
    custom = "看看圆圆的，再告诉麦麦。"

    slot = library.add_custom("hint", "naming", custom)

    assert custom in slot["library"]
    assert custom in slot["selected"]
    stored = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert custom in stored["custom"]["hint"]["naming"]
    assert custom in phrases._lines_for("hint", "naming")


def test_selection_rejects_empty_or_unknown_lines(monkeypatch, tmp_path):
    import pytest

    library, _path = _isolated_library(monkeypatch, tmp_path)

    with pytest.raises(ValueError, match="至少启用一句"):
        library.set_enabled("praise", "pairing", [])
    with pytest.raises(ValueError, match="不在本地语料库"):
        library.set_enabled("praise", "pairing", ["未入库的话"])


def test_phrase_config_api_lists_ordering_and_saves(monkeypatch, tmp_path):
    from flask import Flask

    from app.dialogue import phrase_library
    from app.routes import config_content

    class CourseTypeQuery:
        def filter_by(self, **kwargs):
            row = type("CourseTypeRow", (), {"id": kwargs.get("name")})()
            return type("CourseTypeResult", (), {"first": lambda self: row})()

    class CourseQuery:
        def __init__(self):
            self.course_type_id = None

        def filter_by(self, **kwargs):
            self.course_type_id = kwargs.get("course_type_id")
            return self

        def order_by(self, _field):
            return self

        def all(self):
            if self.course_type_id == "配对":
                return [type("CourseRow", (), {"id": 9, "title": "配对课程"})()]
            return []

    monkeypatch.setattr(
        config_content,
        "CourseType",
        type("FakeCourseType", (), {"query": CourseTypeQuery()}),
    )
    monkeypatch.setattr(
        config_content,
        "Course",
        type("FakeCourse", (), {"id": object(), "query": CourseQuery()}),
    )

    monkeypatch.setattr(
        phrase_library, "OVERLAY_PATH", tmp_path / "dialogue_phrase_selection.yaml"
    )
    app = Flask(__name__)
    app.register_blueprint(config_content.config_content_bp)
    client = app.test_client()

    payload = client.get("/api/config/phrases").get_json()
    assert payload["success"] is True
    ordering = next(x for x in payload["courseTypes"] if x["type"] == "ordering")
    assert len(ordering["slots"]) == 11
    pairing = next(x for x in payload["courseTypes"] if x["type"] == "pairing")
    assert pairing["courseCount"] == 1
    assert pairing["courses"] == [{"id": 9, "title": "配对课程"}]
    assert {item["type"] for item in payload["courseTypes"]} == {
        "global", "mimic", "pairing", "ordering"
    }
    selected = pairing["slots"][0]["library"][:1]

    saved = client.put(
        "/api/config/phrases/question/pairing", json={"selected": selected}
    )
    assert saved.status_code == 200
    assert saved.get_json()["slot"]["selected"] == selected

    rejected = client.put(
        "/api/config/phrases/question/naming", json={"selected": ["旧课程话术"]}
    )
    assert rejected.status_code == 400
    assert "Demo 版仅允许" in rejected.get_json()["error"]

    rejected_custom = client.post(
        "/api/config/phrases/social_greeting_intro/social/custom",
        json={"text": "旧社交话术"},
    )
    assert rejected_custom.status_code == 400
    assert "Demo 版仅允许" in rejected_custom.get_json()["error"]


def test_demo_disables_legacy_audio_entry_configuration():
    from flask import Flask

    from app.routes import config_content

    app = Flask(__name__)
    app.register_blueprint(config_content.config_content_bp)
    client = app.test_client()

    for method in (client.get, client.put):
        response = method("/api/config/audio/entries/social_greeting_intro")
        assert response.status_code == 410
        assert response.get_json()["code"] == "demo_capability_disabled"

    response = client.get("/api/config/audio/course-defaults/naming")
    assert response.status_code == 400
    assert "Demo 版仅允许" in response.get_json()["error"]


def test_audio_service_is_always_browser_tts(monkeypatch):
    from app.audio.service import AudioService

    monkeypatch.setenv("DIALOGUE_TTS_MODE", "file")
    assert AudioService._tts_mode() == "browser"
