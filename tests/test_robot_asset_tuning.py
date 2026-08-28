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


def test_demo_capabilities_enable_screen_expression_only():
    from app.deployment_capabilities import load_demo_capabilities

    capabilities = load_demo_capabilities()["capabilities"]
    assert capabilities["robotMotion"] is False
    assert capabilities["robotExpression"] is True
    assert capabilities["robotRuntime"] is False
    assert capabilities["childAnimation"] is True


def test_demo_repository_has_expression_assets_but_no_motion_assets():
    assert not (ROOT / "doll/data/motions.json").exists()
    assert (ROOT / "doll/data/emotions_meta.json").is_file()
    pose_dir = ROOT / "doll/Pose"
    assert not pose_dir.exists() or not any(pose_dir.rglob("*.json"))
    emotion_dir = ROOT / "static/resources/Emotions"
    assert len(list(emotion_dir.glob("*.mp4"))) == 14
    assert (ROOT / "static/resources/Animations").is_dir()


def test_demo_course_map_contains_expression_and_child_animation_without_motion():
    mapping = json.loads((ROOT / "doll/data/course_map.json").read_text(encoding="utf-8"))
    keys = {key.casefold() for key in _walk_keys(mapping)}
    assert not {"motion", "motions"} & keys
    assert "emotion" in keys
    assert "animation" in keys
    assert set(mapping["courses"]) == {"7", "10"}


def test_demo_has_expression_frontend_but_no_robot_control_frontend():
    forbidden = [
        "templates/robot/control.html",
        "templates/robot_download.html",
        "static/robot/js/robot_control.js",
        "static/robot/js/robot_mapping.js",
    ]
    assert all(not (ROOT / relative).exists() for relative in forbidden)
    assert (ROOT / "templates/robot/emotion.html").is_file()
    assert (ROOT / "static/robot/js/emotion_display.js").is_file()
    assert (ROOT / "static/robot/js/robot_emotion_mapping.js").is_file()
    config_html = (ROOT / "templates/server/config.html").read_text(encoding="utf-8")
    assert 'id="page-motions"' not in config_html
    assert 'id="page-expressions"' in config_html
    assert 'id="page-expression-bindings"' in config_html
    assert 'id="page-binding"' not in config_html


def test_demo_robot_api_blocks_motion_but_allows_expressions_and_animations():
    from flask import Flask
    from app.robot.routes import robot_bp

    app = Flask(__name__)
    app.register_blueprint(robot_bp)
    client = app.test_client()
    for path in ("/api/robot/motions", "/api/robot/control/status"):
        response = client.get(path)
        if path.endswith("control/status"):
            assert response.status_code == 200
            assert response.get_json()["control"]["robotMotion"] is False
        else:
            assert response.status_code == 410
            assert response.get_json()["error"] == "demo_capability_disabled"
    expressions = client.get("/api/robot/emotions")
    assert expressions.status_code == 200
    assert expressions.get_json()["emotions"]
    assert client.get("/api/robot/animations").status_code == 200
