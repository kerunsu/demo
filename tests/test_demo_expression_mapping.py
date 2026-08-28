import json
from pathlib import Path


def _resolver(tmp_path):
    from app.robot.mapping_resolver import MappingResolver

    mapping_path = tmp_path / "course_map.json"
    mapping_path.write_text(
        json.dumps({"defaults": {}, "courses": {}, "students": {}}),
        encoding="utf-8",
    )
    return MappingResolver(str(mapping_path)), mapping_path


def test_expression_binding_round_trip_discards_motion(tmp_path):
    resolver, mapping_path = _resolver(tmp_path)
    resolver.update_course_motions(
        7,
        "question",
        ["forbidden-motion"],
        "v3_speak_lookdown_namecall.mp4",
        {"motionOffsetMs": 500, "audio": {"offsetMs": 300}},
        "",
    )

    binding = resolver.find_mapping(None, 7, None, "question")
    assert binding["motions"] == []
    assert binding["emotion"] == "v3_speak_lookdown_namecall.mp4"
    assert binding["sequence"] == {
        "expressionMediaId": "",
        "expressionDurationMs": 0,
        "audio": {"offsetMs": 300},
    }
    persisted = json.loads(mapping_path.read_text(encoding="utf-8"))
    assert persisted["courses"]["7"]["question"]["emotion"] == binding["emotion"]
    assert "motions" not in persisted["courses"]["7"]["question"]
    assert "motionOffsetMs" not in persisted["courses"]["7"]["question"]["sequence"]


def test_praise_expression_pool_is_deduplicated_and_sampled(tmp_path, monkeypatch):
    from app.robot import mapping_resolver

    resolver, mapping_path = _resolver(tmp_path)
    resolver.update_default_motions(
        "praise",
        ["forbidden-motion"],
        "v3_speak_excitedly_short.mp4",
        emotions=[
            "v3_speak_excitedly_short.mp4",
            "v3_speak_excitedly_long.mp4",
            "v3_speak_excitedly_short.mp4",
        ],
    )
    binding = resolver.find_mapping(None, -1, None, "praise")
    assert binding["emotions"] == [
        "v3_speak_excitedly_short.mp4",
        "v3_speak_excitedly_long.mp4",
    ]
    monkeypatch.setattr(mapping_resolver.random, "choice", lambda values: values[-1])
    assert resolver.select_emotion(binding) == "v3_speak_excitedly_long.mp4"

    persisted = json.loads(mapping_path.read_text(encoding="utf-8"))
    praise = persisted["defaults"]["praise"]
    assert praise["emotions"] == binding["emotions"]
    assert "motions" not in praise


def test_course_event_uses_runtime_praise_expression_draw(tmp_path, monkeypatch):
    from app.robot import mapping_resolver
    from app.robot.robot_service import RobotService

    resolver, _mapping_path = _resolver(tmp_path)
    resolver.update_course_motions(
        7,
        "praise",
        ["forbidden-motion"],
        emotions=[
            "v3_speak_excitedly_short.mp4",
            "v3_speak_excitedly_long.mp4",
        ],
    )
    monkeypatch.setattr(mapping_resolver.random, "choice", lambda values: values[-1])

    service = RobotService.__new__(RobotService)
    monkeypatch.setattr(service, "_mapping_resolver", resolver, raising=False)
    monkeypatch.setattr(service, "get_default_emotion", lambda: "v4_idle.mp4")
    monkeypatch.setattr(service, "_build_sequence_plan", lambda **kwargs: {
        "id": "behavior-random-praise",
        "emotion": kwargs["emotion"],
        "motion": kwargs["motion"],
        "durationMs": 10,
        "scheduledDelayMs": 0,
    })
    monkeypatch.setattr(service, "_enqueue_sequence", lambda _plan: True)
    monkeypatch.setattr(
        service,
        "get_behavior_busy_state",
        lambda: {"remainingMs": 10},
    )

    result = service.trigger_course_event({
        "courseId": 7,
        "courseType": "naming",
        "aux": {"praise": True},
    })
    assert result["success"] is True
    assert result["emotion"] == "v3_speak_excitedly_long.mp4"
    assert result["motion"] is None


def test_random_expression_pool_is_praise_only(tmp_path):
    import pytest

    resolver, _mapping_path = _resolver(tmp_path)
    with pytest.raises(ValueError, match="only supported for praise"):
        resolver.update_default_motions(
            "question", [], "v4_idle.mp4", emotions=["a.mp4", "b.mp4"]
        )
    with pytest.raises(ValueError, match="at least two"):
        resolver.update_default_motions(
            "praise", [], "v4_idle.mp4", emotions=["a.mp4"]
        )


def test_random_child_animation_pool_is_praise_only_and_requires_two(tmp_path):
    import pytest
    from app.robot.config import PRAISE_RANDOM_ANIMATION

    resolver, _mapping_path = _resolver(tmp_path)
    with pytest.raises(ValueError, match="only supported for praise"):
        resolver.update_default_motions(
            "question", [], "v4_idle.mp4", animation="fixed.mp4",
            animations=["a.mp4", "b.mp4"],
        )
    with pytest.raises(ValueError, match="at least two animations"):
        resolver.update_default_motions(
            "praise", [], "v4_idle.mp4", animation=PRAISE_RANDOM_ANIMATION,
            animations=["a.mp4"],
        )


def test_praise_pool_assets_are_reference_protected(tmp_path, monkeypatch):
    from app.robot import emotion_assets

    mapping_path = tmp_path / "course_map.json"
    mapping_path.write_text(
        json.dumps({
            "defaults": {
                "praise": {
                    "emotion": "v3_speak_excitedly_short.mp4",
                    "emotions": [
                        "v3_speak_excitedly_short.mp4",
                        "v3_speak_excitedly_long.mp4",
                    ],
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(emotion_assets, "COURSE_MAP_FILE", str(mapping_path))
    assert emotion_assets.find_emotion_references(
        "v3_speak_excitedly_long.mp4"
    ) == ["defaults.praise.emotions[1]"]


def test_dialogue_expression_rules_keep_short_medium_long_tiers():
    from app.robot.emotion_assets import get_dialogue_reply_expressions

    rules = get_dialogue_reply_expressions()["rules"]
    assert [rule["tier"] for rule in rules] == ["short", "medium", "long"]
    assert [rule["maxChars"] for rule in rules] == sorted(
        rule["maxChars"] for rule in rules
    )


def test_public_mapping_projection_never_exposes_mechanical_data():
    from app.robot.routes import _public_expression_mapping

    projected = _public_expression_mapping({
        "defaults": {
            "praise": {
                "motions": ["wave"],
                "emotion": "praise-a.mp4",
                "emotions": ["praise-a.mp4", "praise-b.mp4"],
                "animation": "__random_praise_animation__",
                "animations": ["鼓励甲.mp4", "鼓励乙.mp4"],
                "sequence": {
                    "motionOffsetMs": 500,
                    "expressionDurationMs": 1200,
                    "audio": {"offsetMs": 100},
                },
            }
        },
        "courses": {
            "7": {"question": {"emotion": "question.mp4"}},
            "9": {"question": {"emotion": "legacy.mp4"}},
        },
        "students": {"1": {"7": {"praise": {"motions": ["wave"]}}}},
    }, active_course_ids={"7"})
    encoded = json.dumps(projected)
    assert projected["students"] == {}
    assert set(projected["courses"]) == {"7"}
    assert projected["defaults"]["praise"]["emotions"] == [
        "praise-a.mp4", "praise-b.mp4",
    ]
    assert projected["defaults"]["praise"]["animations"] == [
        "鼓励甲.mp4", "鼓励乙.mp4",
    ]
    assert '"motions":' not in encoded
    assert '"motionOffsetMs":' not in encoded


def test_demo_mapping_api_forwards_random_animation_pool_without_motion(monkeypatch):
    from flask import Flask
    from app.robot import routes

    captured = {}

    class Service:
        def update_default_motions(self, *args):
            captured["args"] = args

    monkeypatch.setattr(routes, "get_robot_service", lambda: Service())
    app = Flask("demo-praise-animation-pool")
    app.register_blueprint(routes.robot_bp)
    response = app.test_client().put(
        "/api/robot/mapping/defaults/praise",
        json={
            "emotion": "praise.mp4",
            "emotions": [],
            "sequence": {},
            "animation": "__random_praise_animation__",
            "animations": ["鼓励甲.mp4", "鼓励乙.mp4"],
        },
    )

    assert response.status_code == 200
    assert response.get_json()["animations"] == ["鼓励甲.mp4", "鼓励乙.mp4"]
    assert captured["args"][1] == []
    assert captured["args"][-1] == ["鼓励甲.mp4", "鼓励乙.mp4"]


def test_expression_binding_ui_is_expression_only_and_supports_random_praise():
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates/server/config.html").read_text(encoding="utf-8")
    script = (root / "static/robot/js/robot_emotion_mapping.js").read_text(
        encoding="utf-8"
    )

    assert 'id="page-expression-bindings"' in template
    assert "全局 → 课程 → 课点三级覆盖" in template
    assert "表扬随机表情池（至少选 2 个）" in script
    assert "表扬随机儿童动画池（至少选 2 个）" in script
    assert "__random_praise_animation__" in script
    assert "/api/robot/mapping/defaults/" in script
    assert "/api/robot/sequence/preview" in script
    assert "/api/robot/motions" not in script
    assert "robot_mapping.js" not in template
