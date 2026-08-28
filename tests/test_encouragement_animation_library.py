import json
from pathlib import Path


def _minimal_mp4() -> bytes:
    return b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2"


def test_animation_library_upload_reference_and_random_fallback(tmp_path, monkeypatch):
    from app.robot import animation_assets

    static_root = tmp_path / "static"
    map_path = tmp_path / "course_map.json"
    map_path.write_text(
        json.dumps({"courses": {"7": {"praise": {"animation": "chosen.mp4"}}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(animation_assets.Config, "STATIC_DIR", static_root)
    monkeypatch.setattr(animation_assets, "COURSE_MAP_FILE", str(map_path))

    assert animation_assets.save_uploaded_animation("chosen.mp4", _minimal_mp4()) == "chosen.mp4"
    assert animation_assets.save_uploaded_animation("fallback.mp4", _minimal_mp4()) == "fallback.mp4"
    assert animation_assets.save_uploaded_animation(
        r"C:\fakepath\课堂鼓励 1.mp4", _minimal_mp4()
    ) == "课堂鼓励 1.mp4"
    renamed = animation_assets.rename_animation_file("chosen.mp4", "课堂选中.mp4")
    assert renamed == {
        "oldName": "chosen.mp4",
        "newName": "课堂选中.mp4",
        "referencesUpdated": 1,
    }
    assert animation_assets.resolve_animation("课堂选中.mp4").startswith(
        "resources/Animations/课堂选中.mp4?v="
    )
    assert animation_assets.find_animation_references("课堂选中.mp4") == ["courses.7.praise"]
    assert json.loads(map_path.read_text(encoding="utf-8"))["courses"]["7"]["praise"]["animation"] == "课堂选中.mp4"

    invalid = static_root / "resources" / "Animations" / "000-invalid.mp4"
    invalid.write_bytes(b"not-an-mp4")
    monkeypatch.setattr(animation_assets.random, "choice", lambda values: sorted(values)[0])
    assert animation_assets.resolve_animation("").startswith(
        "resources/Animations/fallback.mp4?v="
    )
    assert animation_assets.resolve_animation("000-invalid.mp4", allow_random_fallback=False) is None


def test_animation_library_rejects_bad_files_and_protects_references(tmp_path, monkeypatch):
    import pytest
    from app.robot import animation_assets

    static_root = tmp_path / "static"
    map_path = tmp_path / "course_map.json"
    map_path.write_text(
        json.dumps({
            "defaults": {
                "praise": {
                    "animation": "__random_praise_animation__",
                    "animations": ["bound.mp4", "other.mp4"],
                }
            }
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(animation_assets.Config, "STATIC_DIR", static_root)
    monkeypatch.setattr(animation_assets, "COURSE_MAP_FILE", str(map_path))
    animation_assets.save_uploaded_animation("bound.mp4", _minimal_mp4())
    animation_assets.save_uploaded_animation("other.mp4", _minimal_mp4())

    assert animation_assets.find_animation_references("bound.mp4") == [
        "defaults.praise.animations[0]"
    ]

    with pytest.raises(ValueError):
        animation_assets.save_uploaded_animation("bad.webm", _minimal_mp4())
    with pytest.raises(ValueError):
        animation_assets.save_uploaded_animation("bad.mp4", b"not-an-mp4")
    with pytest.raises(PermissionError):
        animation_assets.delete_animation_file("bound.mp4")

    renamed = animation_assets.rename_animation_file("bound.mp4", "renamed.mp4")
    assert renamed["referencesUpdated"] == 1
    persisted = json.loads(map_path.read_text(encoding="utf-8"))
    assert persisted["defaults"]["praise"]["animations"] == [
        "renamed.mp4", "other.mp4"
    ]


def test_mapping_round_trip_keeps_animation_without_robot_outputs(tmp_path):
    from app.robot.mapping_resolver import MappingResolver

    map_path = tmp_path / "course_map.json"
    map_path.write_text(json.dumps({"defaults": {}, "courses": {}, "students": {}}), encoding="utf-8")
    resolver = MappingResolver(str(map_path))
    resolver.update_course_motions(3, "praise", [], None, {}, "custom.mp4")
    resolver.reload()

    binding = resolver.find_mapping(None, 3, None, "praise")
    assert binding["motions"] == []
    assert binding["emotion"] == "v4_idle.mp4"
    assert binding["animation"] == "custom.mp4"
    persisted = json.loads(map_path.read_text(encoding="utf-8"))
    assert persisted["courses"]["3"]["praise"]["animation"] == "custom.mp4"


def test_demo_mapping_keeps_explicit_random_praise_animation_pool(tmp_path):
    from app.robot.config import PRAISE_RANDOM_ANIMATION
    from app.robot.mapping_resolver import MappingResolver

    map_path = tmp_path / "course_map.json"
    map_path.write_text(
        json.dumps({"defaults": {}, "courses": {}, "students": {}}),
        encoding="utf-8",
    )
    resolver = MappingResolver(str(map_path))
    resolver.update_default_motions(
        "praise", [], "happy.mp4", {}, PRAISE_RANDOM_ANIMATION, [],
        ["鼓励甲.mp4", "鼓励乙.mp4"],
    )
    resolver.reload()

    binding = resolver.find_mapping(None, -1, None, "praise")
    assert binding["motions"] == []
    assert binding["animation"] == PRAISE_RANDOM_ANIMATION
    assert binding["animations"] == ["鼓励甲.mp4", "鼓励乙.mp4"]


def test_praise_runtime_samples_only_the_reviewed_animation_pool(tmp_path, monkeypatch):
    from app.robot import animation_assets
    from app.robot.robot_service import RobotService

    static_root = tmp_path / "static"
    monkeypatch.setattr(animation_assets.Config, "STATIC_DIR", static_root)
    for name in ("随机甲.mp4", "随机乙.mp4", "历史素材.mp4"):
        animation_assets.save_uploaded_animation(name, _minimal_mp4())
    sampled = []

    def choose(values):
        sampled.append(tuple(values))
        return "随机乙.mp4"

    monkeypatch.setattr(animation_assets.random, "choice", choose)

    class Resolver:
        @staticmethod
        def parse_aux_type(_aux):
            return "praise"

        @staticmethod
        def find_mapping(_student_id, _course_id, _item_id, _aux_type):
            return {
                "animation": animation_assets.PRAISE_RANDOM_ANIMATION,
                "animations": ["随机甲.mp4", "随机乙.mp4"],
            }

    service = RobotService.__new__(RobotService)
    service._mapping_resolver = Resolver()
    resolved = service.resolve_encouragement_animation({
        "aux": {"praise": True}, "courseId": 7, "itemId": 16,
    })

    assert sampled == [("随机甲.mp4", "随机乙.mp4")]
    assert resolved.startswith("resources/Animations/随机乙.mp4?v=")


def test_random_praise_animation_fails_closed_without_reviewed_pool(tmp_path, monkeypatch):
    from app.robot import animation_assets

    static_root = tmp_path / "static"
    monkeypatch.setattr(animation_assets.Config, "STATIC_DIR", static_root)
    animation_assets.save_uploaded_animation("历史素材.mp4", _minimal_mp4())

    assert animation_assets.resolve_animation(
        animation_assets.PRAISE_RANDOM_ANIMATION,
        random_pool=[],
        allow_random_fallback=False,
    ) is None


def test_child_uses_behavior_animation_contract_only():
    root = Path(__file__).resolve().parents[1]
    child = (root / "static" / "js" / "child.js").read_text(encoding="utf-8")
    html = (root / "templates" / "child.html").read_text(encoding="utf-8")
    assert "behaviorAnimation" in child
    assert "behavior_animation_ended" in child
    assert "praiseVideo" not in child
    assert 'id="behaviorAnimationVideo"' in html


def test_config_sync_includes_demo_bindings_and_animations_only(tmp_path, monkeypatch):
    from app.routes import config_sync

    expected = {
        "doll/data/course_map.json": "{}",
        "static/resources/Animations/default.mp4": "animation",
    }
    for relative, content in expected.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(config_sync, "_ROOT", tmp_path)

    files = {path.relative_to(tmp_path).as_posix() for path, _kind in config_sync._iter_sync_files()}
    assert set(expected).issubset(files)
    assert "doll/data/motions.json" not in files
    assert "doll/data/emotions_meta.json" not in files
    assert not any(path.startswith("static/resources/Emotions/") for path in files)


def test_animation_rename_ui_and_api_contract():
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / "server" / "config.html").read_text(encoding="utf-8")
    script = (root / "static" / "js" / "config_content_animations.js").read_text(encoding="utf-8")
    assert 'id="btn-rename-animation"' in template
    assert "config_content_animations.js?v=20260823-module-guard-v1" in template
    assert "document.body?.dataset?.module !== 'content'" in script
    assert "/animations/${encodeURIComponent(selected)}/rename" in script
    assert "referencesUpdated" in script or "newName" in script
    binding = (root / "static" / "robot" / "js" / "robot_emotion_mapping.js").read_text(
        encoding="utf-8"
    )
    assert "const PRAISE_RANDOM_ANIMATION = '__random_praise_animation__';" in binding
    assert "data-animation-pool" in binding
    assert "随机表扬儿童动画池至少需要选择 2 个动画" in binding


def test_demo_animation_ui_keeps_expression_mapping_without_motion_mapping():
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / "server" / "config.html").read_text(encoding="utf-8")
    assert "config_content_animations.js" in template
    assert "robot_mapping.js" not in template
    assert not (root / "static" / "robot" / "js" / "robot_mapping.js").exists()
    assert "robot_emotion_mapping.js" in template
    assert (root / "static" / "robot" / "js" / "robot_emotion_mapping.js").is_file()
    assert 'id="page-binding"' not in template
