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
    assert animation_assets.resolve_animation("课堂选中.mp4") == "resources/Animations/课堂选中.mp4"
    assert animation_assets.find_animation_references("课堂选中.mp4") == ["courses.7.praise"]
    assert json.loads(map_path.read_text(encoding="utf-8"))["courses"]["7"]["praise"]["animation"] == "课堂选中.mp4"

    monkeypatch.setattr(animation_assets.random, "choice", lambda values: sorted(values)[0])
    assert animation_assets.resolve_animation("") == "resources/Animations/fallback.mp4"


def test_animation_library_rejects_bad_files_and_protects_references(tmp_path, monkeypatch):
    import pytest
    from app.robot import animation_assets

    static_root = tmp_path / "static"
    map_path = tmp_path / "course_map.json"
    map_path.write_text(
        json.dumps({"defaults": {"praise": {"animation": "bound.mp4"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(animation_assets.Config, "STATIC_DIR", static_root)
    monkeypatch.setattr(animation_assets, "COURSE_MAP_FILE", str(map_path))
    animation_assets.save_uploaded_animation("bound.mp4", _minimal_mp4())

    with pytest.raises(ValueError):
        animation_assets.save_uploaded_animation("bad.webm", _minimal_mp4())
    with pytest.raises(ValueError):
        animation_assets.save_uploaded_animation("bad.mp4", b"not-an-mp4")
    with pytest.raises(PermissionError):
        animation_assets.delete_animation_file("bound.mp4")


def test_mapping_round_trip_keeps_explicit_animation(tmp_path):
    from app.robot.mapping_resolver import MappingResolver

    map_path = tmp_path / "course_map.json"
    map_path.write_text(json.dumps({"defaults": {}, "courses": {}, "students": {}}), encoding="utf-8")
    resolver = MappingResolver(str(map_path))
    resolver.update_course_motions(3, "praise", ["wave"], "happy.mp4", {}, "custom.mp4")
    resolver.reload()

    binding = resolver.find_mapping(None, 3, None, "praise")
    assert binding["motions"] == ["wave"]
    assert binding["animation"] == "custom.mp4"
    persisted = json.loads(map_path.read_text(encoding="utf-8"))
    assert persisted["courses"]["3"]["praise"]["animation"] == "custom.mp4"


def test_child_uses_behavior_animation_contract_only():
    root = Path(__file__).resolve().parents[1]
    child = (root / "static" / "js" / "child.js").read_text(encoding="utf-8")
    html = (root / "templates" / "child.html").read_text(encoding="utf-8")
    assert "behaviorAnimation" in child
    assert "behavior_animation_ended" in child
    assert "praiseVideo" not in child
    assert 'id="behaviorAnimationVideo"' in html


def test_config_sync_includes_robot_libraries_bindings_and_animations(tmp_path, monkeypatch):
    from app.routes import config_sync

    expected = {
        "doll/data/motions.json": "{}",
        "doll/data/course_map.json": "{}",
        "doll/data/emotions_meta.json": "{}",
        "static/resources/Emotions/idle.mp4": "emotion",
        "static/resources/Animations/default.mp4": "animation",
    }
    for relative, content in expected.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    monkeypatch.setattr(config_sync, "_ROOT", tmp_path)

    files = {path.relative_to(tmp_path).as_posix() for path, _kind in config_sync._iter_sync_files()}
    assert set(expected).issubset(files)


def test_animation_rename_ui_and_api_contract():
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates" / "server" / "config.html").read_text(encoding="utf-8")
    script = (root / "static" / "js" / "config_content_animations.js").read_text(encoding="utf-8")
    assert 'id="btn-rename-animation"' in template
    assert "/animations/${encodeURIComponent(selected)}/rename" in script
    assert "referencesUpdated" in script or "newName" in script
