"""Hard deployment boundaries for the independent hardware-free Demo build."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from flask import Flask

from app.deployment_capabilities import load_demo_capabilities
from app.config import Config
from app.robot import routes as output_routes
from app.runtime_modes import load_runtime_modes


ROOT = Path(__file__).resolve().parents[1]


def test_demo_capabilities_and_runtime_modes_fail_closed(tmp_path, monkeypatch):
    capabilities = load_demo_capabilities()["capabilities"]
    assert capabilities == {
        "robotMotion": False,
        "robotExpression": False,
        "robotRuntime": False,
        "childAnimation": True,
        "browserSpeech": True,
    }

    expanded = tmp_path / "expanded.json"
    expanded.write_text(json.dumps({
        "schemaVersion": 1,
        "deployment": "demo-machine",
        "capabilities": {"robotMotion": True, "childAnimation": True},
    }), encoding="utf-8")
    assert load_demo_capabilities(expanded)["capabilities"]["robotMotion"] is False

    monkeypatch.setenv("CHILD_MEDIA_MODE", "agent")
    monkeypatch.setenv("ROBOT_CONTROL_MODE", "robot_runtime")
    modes = load_runtime_modes()
    assert modes["child_media_mode"] == "browser"
    assert modes["robot_control_mode"] == "disabled"

    child_config = Config.get_child_runtime_config()
    assert child_config["mediaMode"] == "browser"
    assert "mediaAgentBase" not in child_config
    assert "mediaAgentPort" not in child_config
    assert "skipRuntimeRecordingCheck" not in child_config
    child_source = (ROOT / "static/js/child.js").read_text(encoding="utf-8")
    assert "19091" not in child_source
    assert "callMediaAgent" not in child_source


def test_demo_launcher_refuses_to_reuse_a_different_project_server():
    launcher = (ROOT / "start_server.ps1").read_text(encoding="utf-8")
    assert "$status.deployment -ne 'demo-machine'" in launcher
    assert "occupied by another project/version" in launcher

    app_source = (ROOT / "app.py").read_text(encoding="utf-8")
    status_route = app_source[
        app_source.index('@app.route("/api/server/status"'):
        app_source.index("# @app.route('/manifest.json')")
    ]
    assert 'payload["deployment"] = deployment["deployment"]' in status_route
    assert 'payload["capabilities"] = deployment["capabilities"]' in status_route


def test_demo_routes_allow_child_animation_and_block_hardware(monkeypatch):
    calls = []

    class OutputService:
        def get_animations_payload(self):
            return {"animations": ["勾勾.mp4"], "default": "勾勾.mp4"}

        def trigger_course_event(self, payload):
            calls.append(payload)
            return {"success": True, "motion": None, "emotion": ""}

    monkeypatch.setattr(output_routes, "get_robot_service", lambda: OutputService())
    app = Flask(__name__)
    app.register_blueprint(output_routes.robot_bp)
    client = app.test_client()

    animations = client.get("/api/robot/animations")
    assert animations.status_code == 200
    assert animations.get_json()["animations"] == ["勾勾.mp4"]

    for method, path in (
        (client.get, "/api/robot/motions"),
        (client.get, "/api/robot/emotions"),
        (client.get, "/api/robot/runtime/status"),
        (client.post, "/api/robot/play/wave"),
        (client.put, "/api/robot/mapping/defaults/praise"),
    ):
        response = method(path)
        assert response.status_code == 410
        assert response.get_json()["error"] == "demo_capability_disabled"

    response = client.post("/api/robot/course-event", json={
        "courseId": 1,
        "aux": {"praise": True},
        "motions": ["wave"],
        "emotion": "happy.mp4",
    })
    assert response.status_code == 200
    assert "motions" not in calls[0]
    assert "emotion" not in calls[0]


def test_demo_release_resources_and_behavior_map_have_no_hardware_expression_data():
    forbidden_files = [
        ROOT / "doll/data/motions.json",
        ROOT / "doll/data/emotions_meta.json",
        ROOT / "app/sockets/robot_events.py",
        ROOT / "templates/robot/control.html",
        ROOT / "templates/robot/emotion.html",
        ROOT / "templates/robot_download.html",
    ]
    assert not any(path.exists() for path in forbidden_files)
    assert not list((ROOT / "doll/Pose").rglob("*.json"))
    assert not list((ROOT / "static/resources/Emotions").rglob("*.mp4"))
    assert not (ROOT / "doll/DollSer").exists()
    assert not (ROOT / "doll/robot_agent.py").exists()
    assert not (ROOT / "scripts/pack_robot_release.ps1").exists()
    assert list((ROOT / "static/resources/Animations").glob("*.mp4"))

    behavior_map = json.loads((ROOT / "doll/data/course_map.json").read_text(encoding="utf-8"))
    assert set(behavior_map["courses"]) == {"9", "10"}

    forbidden_keys = {"motion", "motions", "emotion", "expressionMediaId", "motionOffsetMs"}

    def walk(value):
        if isinstance(value, dict):
            assert forbidden_keys.isdisjoint(value)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(behavior_map)


def test_demo_config_template_renders_without_hardware_or_full_expression_ui():
    app = Flask(__name__, template_folder=str(ROOT / "templates"), static_folder=str(ROOT / "static"))
    with app.test_request_context("/server/config/overview"):
        rendered = app.jinja_env.get_template("server/config.html").render(active_module="overview")

    for forbidden in (
        "page-expressions",
        "page-motions",
        "config_content_expressions.js",
        "config_content_motions.js",
        "config_behavior_sequence.js",
        "config_dialogue_expressions.js",
        "/robot/download",
    ):
        assert forbidden not in rendered
    assert "page-animations" in rendered
    assert "儿童屏鼓励动画" in rendered


def test_mechanical_socket_events_are_not_present_or_registered():
    socket_source = (ROOT / "app/sockets/events.py").read_text(encoding="utf-8")
    assert "register_robot_events" not in socket_source
    assert not (ROOT / "app/sockets/robot_events.py").exists()


def test_dialogue_output_is_audio_only_without_full_product_behavior_selection():
    source = (ROOT / "app/dialogue/sockets.py").read_text(encoding="utf-8")
    emit_speak = source[source.index("def _emit_speak("):source.index("def _queue_pending_dialogue_speak(")]

    assert "reserve_audio_only_behavior" in emit_speak
    assert "select_dialogue_reply_motion" not in emit_speak
    assert "select_dialogue_reply_emotion" not in emit_speak
    assert "start_dialogue_reply_behavior" not in emit_speak
    assert 'payload["expression"]' not in emit_speak
    assert 'payload["directionAction"]' not in emit_speak


def test_fresh_demo_database_seed_is_idempotent_and_has_only_two_courses(tmp_path):
    database_path = tmp_path / "fresh-demo.db"
    env = os.environ.copy()
    env["EIART_DATABASE_PATH"] = str(database_path)
    for _ in range(2):
        subprocess.run(
            [sys.executable, "database/seed_standard.py"],
            cwd=ROOT,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    with sqlite3.connect(database_path) as connection:
        course_types = [row[0] for row in connection.execute(
            "SELECT name FROM course_type ORDER BY id"
        )]
        courses = [row[0] for row in connection.execute(
            "SELECT title FROM course ORDER BY id"
        )]
        ability_types = [row[0] for row in connection.execute(
            "SELECT name FROM ability_type ORDER BY id"
        )]
    assert course_types == ["配对", "排序"]
    assert courses == ["配对", "排序"]
    assert ability_types == ["注意力", "配对", "排序"]
