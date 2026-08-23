import json
from pathlib import Path

import pytest
from flask import Flask


def test_repository_idle_motion_has_gentle_return_speed():
    root = Path(__file__).resolve().parents[1]
    document = json.loads(
        (root / "doll/data/motions.json").read_text(encoding="utf-8")
    )
    assert document["motionMeta"]["空动作"]["speedMultiplier"] == 0.5


def test_motion_speed_defaults_scales_and_persists(tmp_path, monkeypatch):
    from app.robot import motion_storage

    target = tmp_path / "motions.json"
    target.write_text(json.dumps({
        "version": 2,
        "motions": {
            "wave": [
                {"time": 0, "pose": {"pitch": 180}, "moveMs": 100},
                {"time": 1000, "pose": {"pitch": 200}, "moveMs": 400},
            ]
        },
        "motionMeta": {},
    }), encoding="utf-8")
    monkeypatch.setattr(motion_storage, "MOTIONS_FILE", str(target))

    assert motion_storage.get_motion_metadata("wave")["speedMultiplier"] == 1.0
    assert motion_storage.set_motion_speed("wave", 2)["speedMultiplier"] == 2.0
    frames = motion_storage.get_scaled_motion_frames("wave")
    assert [(item["time"], item["moveMs"]) for item in frames] == [(0, 50), (500, 200)]
    assert json.loads(target.read_text(encoding="utf-8"))["motionMeta"]["wave"]["speedMultiplier"] == 2.0

    for invalid in (True, "NaN", float("inf"), 0.24, 4.01):
        with pytest.raises(ValueError):
            motion_storage.set_motion_speed("wave", invalid)


def test_motion_library_accepts_windows_utf8_bom(tmp_path, monkeypatch):
    from app.robot import motion_storage

    target = tmp_path / "motions.json"
    target.write_bytes(
        b"\xef\xbb\xbf" + json.dumps({
            "version": 2,
            "motions": {"wave": [{"time": 0, "pose": {}, "moveMs": 100}]},
        }).encode("utf-8")
    )
    monkeypatch.setattr(motion_storage, "MOTIONS_FILE", str(target))

    assert "wave" in motion_storage.load_document()["motions"]


def test_motion_atomic_write_failure_keeps_previous_file(tmp_path, monkeypatch):
    from app.robot import motion_storage

    target = tmp_path / "motions.json"
    original = '{"version": 2, "motions": {"old": []}, "motionMeta": {}}'
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(motion_storage, "MOTIONS_FILE", str(target))
    monkeypatch.setattr(motion_storage.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("fail")))

    with pytest.raises(OSError, match="fail"):
        motion_storage.save_document({"motions": {"new": []}, "motionMeta": {}})
    assert target.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob("*.tmp"))


def _prepare_emotions(tmp_path, monkeypatch):
    from app.robot import emotion_assets

    static_root = tmp_path / "static"
    emotion_dir = static_root / "resources" / "Emotions"
    emotion_dir.mkdir(parents=True)
    (emotion_dir / "happy.mp4").write_bytes(b"video")
    (emotion_dir / "legacy.gif").write_bytes(b"gif")
    meta = tmp_path / "emotions_meta.json"
    meta.write_text('{"default":"happy.mp4"}', encoding="utf-8")
    monkeypatch.setattr(emotion_assets.Config, "STATIC_DIR", str(static_root))
    monkeypatch.setattr(emotion_assets, "EMOTIONS_META_FILE", str(meta))
    return emotion_assets, meta


def test_emotion_style_global_filter_and_legacy_defaults(tmp_path, monkeypatch):
    emotion_assets, meta = _prepare_emotions(tmp_path, monkeypatch)

    assert emotion_assets.get_emotion_style("happy.mp4") == emotion_assets.DEFAULT_EMOTION_STYLE
    style = emotion_assets.set_emotion_style("happy.mp4", {
        "speedMultiplier": 2,
        "scale": 1.2,
        "hueDeg": -12,
        "brightness": 0.9,
        "saturation": 1.1,
        "opacity": 0.8,
    })
    assert style["speedMultiplier"] == 2.0
    assert emotion_assets.get_emotions_payload()["items"][0]["style"] == style

    global_filter = emotion_assets.set_global_filter({
        "enabled": True,
        "hueDeg": 8,
        "brightness": 1.1,
        "saturation": 0.9,
        "contrast": 1.05,
        "opacity": 0.95,
    })
    assert global_filter["enabled"] is True
    assert json.loads(meta.read_text(encoding="utf-8"))["version"] == 2

    with pytest.raises(ValueError, match="only supported for MP4"):
        emotion_assets.set_emotion_style("legacy.gif", {
            **emotion_assets.DEFAULT_EMOTION_STYLE,
            "speedMultiplier": 2,
        })
    with pytest.raises(ValueError, match="unknown style fields"):
        emotion_assets.set_emotion_style("happy.mp4", {"unknown": 1})
    with pytest.raises(ValueError):
        emotion_assets.set_global_filter({"enabled": True, "brightness": "NaN"})


def test_emotion_speed_scales_server_duration(tmp_path, monkeypatch):
    emotion_assets, _meta = _prepare_emotions(tmp_path, monkeypatch)
    monkeypatch.setattr(emotion_assets, "_decode_mp4_duration", lambda *_args: 4000)
    emotion_assets.set_emotion_style("happy.mp4", {
        **emotion_assets.DEFAULT_EMOTION_STYLE,
        "speedMultiplier": 2,
    })
    assert emotion_assets.get_expression_duration_ms("happy.mp4") == 2000


def test_idle_emotion_pool_is_backward_compatible_and_persists(tmp_path, monkeypatch):
    emotion_assets, meta = _prepare_emotions(tmp_path, monkeypatch)

    assert emotion_assets.get_idle_emotions() == ["happy.mp4"]
    assert emotion_assets.set_idle_emotions(["legacy.gif", "happy.mp4", "legacy.gif"]) == [
        "legacy.gif", "happy.mp4",
    ]
    payload = emotion_assets.get_emotions_payload()
    assert payload["idlePool"] == ["legacy.gif", "happy.mp4"]
    assert [item["name"] for item in payload["items"] if item["isIdle"]] == [
        "happy.mp4", "legacy.gif",
    ]
    stored = json.loads(meta.read_text(encoding="utf-8"))
    assert stored["default"] == "legacy.gif"
    assert stored["idlePool"] == ["legacy.gif", "happy.mp4"]

    with pytest.raises(ValueError, match="at least one"):
        emotion_assets.set_idle_emotions([])
    with pytest.raises(FileNotFoundError):
        emotion_assets.set_idle_emotions(["missing.mp4"])


def test_deleting_idle_emotion_keeps_remaining_pool(tmp_path, monkeypatch):
    emotion_assets, _meta = _prepare_emotions(tmp_path, monkeypatch)
    emotion_assets.set_idle_emotions(["happy.mp4", "legacy.gif"])
    emotion_assets.delete_emotion_file("happy.mp4")
    assert emotion_assets.get_idle_emotions() == ["legacy.gif"]
    assert emotion_assets.get_default_emotion() == "legacy.gif"


def test_sequence_busy_duration_uses_scaled_motion(monkeypatch):
    from app.robot import robot_service

    monkeypatch.setattr(robot_service, "get_motion_metadata", lambda _name: {"speedMultiplier": 2})
    monkeypatch.setattr(robot_service, "get_scaled_motion_frames", lambda _name: [
        {"time": 0, "moveMs": 50}, {"time": 500, "moveMs": 200},
    ])
    from app.robot import emotion_assets
    monkeypatch.setattr(emotion_assets, "get_expression_duration_ms", lambda _name: 300)
    monkeypatch.setattr(emotion_assets, "get_emotion_style", lambda _name: {"speedMultiplier": 2})
    service = robot_service.RobotService.__new__(robot_service.RobotService)
    plan = service._build_sequence_plan(motion="wave", emotion="happy.mp4", sequence={})
    assert plan["motionDurationMs"] == 700
    assert plan["durationMs"] == 700
    explicit = service._build_sequence_plan(
        motion=None,
        emotion="happy.mp4",
        sequence={"expressionDurationMs": 1000},
    )
    assert explicit["expressionDurationMs"] == 500
    praise = service._build_sequence_plan(
        motion=None,
        emotion="happy.mp4",
        sequence={"expressionDurationMs": 1000},
        event_data={"aux": {"praise": True}},
    )
    assert praise["startLeadMs"] == robot_service.BEHAVIOR_FEEDBACK_START_LEAD_MS


def test_asset_tuning_http_contract(monkeypatch):
    from app.robot import routes

    class Service:
        def get_motion(self, name):
            return [] if name in {"wave", "folder/wave"} else None

        def get_available_emotions(self):
            return ["happy.mp4"]

        def get_emotion_style(self, _name):
            return {"speedMultiplier": 1.0}

        def set_emotion_style(self, _name, value):
            return value

        def get_global_emotion_filter(self):
            return {"enabled": False}

        def set_global_emotion_filter(self, value):
            return value

        def get_default_emotion(self):
            return "happy.mp4"

        def get_idle_emotions(self):
            return ["happy.mp4"]

        def set_idle_emotions(self, names):
            return names

        def trigger_emotion(self, *_args, **_kwargs):
            return True

    monkeypatch.setattr(routes, "get_robot_service", lambda: Service())
    monkeypatch.setattr(routes, "get_motion_metadata", lambda _name: {"speedMultiplier": 1.0})
    monkeypatch.setattr(routes, "set_motion_speed", lambda _name, value: {"speedMultiplier": float(value)})
    app = Flask("asset-tuning")
    app.register_blueprint(routes.robot_bp)
    client = app.test_client()

    assert client.put("/api/robot/motions/wave/playback", json={"speedMultiplier": 1.5}).get_json()["playback"]["speedMultiplier"] == 1.5
    assert client.get("/api/robot/motions/folder%2Fwave/playback").status_code == 200
    assert client.put("/api/robot/motions/wave/playback", json={"speedMultiplier": 1, "extra": 1}).status_code == 400
    assert client.put("/api/robot/emotions/happy.mp4/style", json={"scale": 1.1}).status_code == 200
    assert client.put("/api/robot/emotions/global-filter", json={"enabled": True}).status_code == 200
    idle = client.put("/api/robot/emotions/idle-pool", json={"emotions": ["happy.mp4"]})
    assert idle.status_code == 200
    assert idle.get_json()["emotions"] == ["happy.mp4"]


def test_asset_tuning_frontend_contract():
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / "robot" / "emotion.html").read_text(encoding="utf-8")
    display = (root / "static" / "robot" / "js" / "emotion_display.js").read_text(encoding="utf-8")
    config = (root / "static" / "js" / "config_content_expressions.js").read_text(encoding="utf-8")

    assert 'id="emotion-global-filter-layer"' in template
    assert "element.playbackRate = style.speedMultiplier" in display
    assert "globalFilterLayer.style.filter" in display
    assert "data.settingsOnly === true" in display
    assert "media.style.transform" in config
    assert "/emotions/global-filter" in config
    assert "/emotions/idle-pool" in config
    assert "pendingEmotionEvents.push(eventData)" in display
    assert "stopIdlePlayback();" in display
    assert "idleVideo.addEventListener('ended'" in display


def test_dialogue_reply_expression_rules_validate_and_select(tmp_path, monkeypatch):
    emotion_assets, meta = _prepare_emotions(tmp_path, monkeypatch)
    Path(emotion_assets.emotions_dir(), "long.mp4").write_bytes(b"video")

    saved = emotion_assets.set_dialogue_reply_expressions({
        "enabled": True,
        "rules": [
            {"maxChars": 12, "emotion": "happy.mp4"},
            {"maxChars": 40, "emotion": "long.mp4"},
        ],
    })
    assert saved["enabled"] is True
    assert emotion_assets.select_dialogue_reply_emotion("你好 世界") == {
        "emotion": "happy.mp4",
        "charCount": 4,
        "maxChars": 12,
    }
    assert emotion_assets.select_dialogue_reply_emotion("x" * 100)["emotion"] == "long.mp4"
    assert json.loads(meta.read_text(encoding="utf-8"))["dialogueReplyExpressions"] == saved

    with pytest.raises(ValueError, match="strictly increasing|严格递增"):
        emotion_assets.set_dialogue_reply_expressions({
            "enabled": True,
            "rules": [
                {"maxChars": 20, "emotion": "happy.mp4"},
                {"maxChars": 20, "emotion": "long.mp4"},
            ],
        })
    with pytest.raises(ValueError, match="MP4"):
        emotion_assets.set_dialogue_reply_expressions({
            "enabled": True,
            "rules": [{"maxChars": 20, "emotion": "legacy.gif"}],
        })


def test_dialogue_reply_rules_http_contract(monkeypatch):
    from app.robot import routes

    class Service:
        def get_dialogue_reply_expressions(self):
            return {"enabled": False, "rules": []}

        def set_dialogue_reply_expressions(self, value):
            return value

    monkeypatch.setattr(routes, "get_robot_service", lambda: Service())
    app = Flask("dialogue-expression-rules")
    app.register_blueprint(routes.robot_bp)
    client = app.test_client()

    assert client.get("/api/robot/emotions/dialogue-reply-rules").get_json() == {
        "success": True,
        "config": {"enabled": False, "rules": []},
    }
    response = client.put(
        "/api/robot/emotions/dialogue-reply-rules",
        json={"enabled": True, "rules": [{"maxChars": 20, "emotion": "happy.mp4"}]},
    )
    assert response.status_code == 200
    assert response.get_json()["config"]["rules"][0]["maxChars"] == 20


def test_dialogue_reply_frontend_binding_contract():
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / "server" / "config.html").read_text(encoding="utf-8")
    script = (root / "static" / "js" / "config_dialogue_expressions.js").read_text(encoding="utf-8")
    assert 'id="dialogue-expression-card"' in template
    assert 'id="dialogue-expression-rules"' in template
    assert "/api/robot/emotions/dialogue-reply-rules" in script
    assert "maxChars" in script
    assert "有效字数" in script
