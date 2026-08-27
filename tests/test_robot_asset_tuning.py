import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _walk_keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def test_demo_capabilities_permanently_disable_robot_outputs():
    from app.deployment_capabilities import load_demo_capabilities

    capabilities = load_demo_capabilities()["capabilities"]
    assert capabilities["robotMotion"] is False
    assert capabilities["robotExpression"] is False
    assert capabilities["robotRuntime"] is False
    assert capabilities["childAnimation"] is True


def test_demo_repository_has_no_robot_motion_or_expression_assets():
    assert not (ROOT / "doll/data/motions.json").exists()
    assert not (ROOT / "doll/data/emotions_meta.json").exists()
    pose_dir = ROOT / "doll/Pose"
    assert not pose_dir.exists() or not any(pose_dir.rglob("*.json"))
    emotion_dir = ROOT / "static/resources/Emotions"
    assert not emotion_dir.exists() or not any(emotion_dir.iterdir())
    assert (ROOT / "static/resources/Animations").is_dir()


def test_demo_course_map_contains_child_animation_only():
    mapping = json.loads((ROOT / "doll/data/course_map.json").read_text(encoding="utf-8"))
    keys = {key.casefold() for key in _walk_keys(mapping)}
    assert not {"motion", "motions", "emotion", "expression"} & keys
    assert "animation" in keys
    assert set(mapping["courses"]) == {"9", "10"}


def test_demo_has_no_robot_control_or_expression_frontend():
    forbidden = [
        "templates/robot/control.html",
        "templates/robot/emotion.html",
        "templates/robot_download.html",
        "static/robot/js/robot_control.js",
        "static/robot/js/robot_mapping.js",
        "static/robot/js/robot_emotion_mapping.js",
        "static/robot/js/emotion_display.js",
    ]
    assert all(not (ROOT / relative).exists() for relative in forbidden)
    config_html = (ROOT / "templates/server/config.html").read_text(encoding="utf-8")
    assert 'id="page-motions"' not in config_html
    assert 'id="page-expressions"' not in config_html
    assert 'id="page-binding"' not in config_html


def test_demo_robot_api_is_fail_closed_but_animations_remain_available():
    from flask import Flask
    from app.robot.routes import robot_bp

    app = Flask(__name__)
    app.register_blueprint(robot_bp)
    client = app.test_client()
    for path in ("/api/robot/motions", "/api/robot/emotions", "/api/robot/control/status"):
        response = client.get(path)
        if path.endswith("control/status"):
            assert response.status_code == 200
            assert response.get_json()["control"]["robotMotion"] is False
        else:
            assert response.status_code == 410
            assert response.get_json()["error"] == "demo_capability_disabled"
    assert client.get("/api/robot/animations").status_code == 200
