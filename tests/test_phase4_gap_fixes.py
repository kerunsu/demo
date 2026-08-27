"""Phase 4 regression tests for runtime wiring and safe rollout gaps."""

from __future__ import annotations

import io
import json
from pathlib import Path

from app.computation.interaction import EventCatalog, InteractionResolver, LegacyInteractionAdapter, infer_event_key, validate_profile
from app.contracts.models import InteractionContext


class _Store:
    def __init__(self, profiles):
        self.profiles = profiles

    def list(self, course_id=None):
        return tuple(
            p for p in self.profiles
            if course_id is None or str(p.get("courseId")) == str(course_id)
        )

    def get(self, course_id, version=None):
        values = list(self.list(course_id))
        if version is not None:
            return next((p for p in values if str(p.get("version")) == str(version)), None)
        published = [p for p in values if p.get("status") == "published"]
        return published[0] if published else None


class _Legacy:
    def normalize_event(self, context, aux=None):
        return context.event_key or "question.naming"

    def resolve(self, context, aux=None):
        return {"motions": ["legacy-motion"], "emotion": "legacy-emotion", "sequence": {}}


def _context(**changes):
    values = {"course_id": "course-1", "course_type": "naming", "event_key": "question.naming"}
    values.update(changes)
    return InteractionContext(**values)


def test_phase4_v2_speech_is_consumed_and_preserves_context():
    store = _Store([{
        "courseId": "course-1",
        "courseType": "naming",
        "version": "v2",
        "status": "published",
        "events": {"question.naming": {"binding": {
            "mode": "replace",
            "speech": [{"text": "你知道这是什么吗？", "lineId": "naming.prompt", "delayMs": 40}],
        }}},
    }])
    plan = InteractionResolver(store=store, legacy=_Legacy(), catalog=EventCatalog()).resolve(_context())
    assert plan.source == "v2.replace"
    assert plan.speech[0].text == "你知道这是什么吗？"
    assert plan.speech[0].line_id == "naming.prompt"
    assert plan.metadata["speechConfigured"] is True
    assert plan.speech[0].metadata["delayMs"] == 40


def test_phase4_v2_speech_dispatch_targets_child_and_keeps_correlation(monkeypatch):
    from app.sockets import events

    emitted = []
    monkeypatch.setattr(events, "emit", lambda *args, **kwargs: emitted.append((args, kwargs)))
    result = events._dispatch_v2_speech_commands(
        [{"text": "请回答", "line_id": "line-1", "pause_asr": True, "metadata": {"delayMs": 25}}],
        session_id="media-1",
        child_room="session_media-1_child",
        behavior_id="behavior-1",
        request_id="request-1",
    )
    assert result["dispatchCount"] == 1
    assert emitted[0][0][0] == "robot_speak_text"
    assert emitted[0][0][1]["text"] == "请回答"
    assert emitted[0][0][1]["behaviorId"] == "behavior-1"
    assert emitted[0][1]["room"] == "session_media-1_child"


def test_phase4_shadow_rollout_returns_diff_without_selecting_shadow_visuals():
    store = _Store([{
        "courseId": "course-1", "courseType": "naming", "version": "v2", "status": "published",
        "deployment": {"stage": "shadow"},
        "events": {"question.naming": {"binding": {"mode": "replace", "motions": ["v2-motion"]}}},
    }])
    active, report = InteractionResolver(store=store, legacy=_Legacy(), catalog=EventCatalog()).resolve_with_shadow(_context())
    assert active.source == "legacy"
    assert active.motions[0]["assetId"] == "legacy-motion"
    assert report["equal"] is False
    assert "motion" in report["differences"]


def test_phase4_profile_validation_covers_required_lines_duration_and_inheritance():
    profile = {
        "courseId": "course-1", "version": "v1",
        "requiredEvents": ["question.naming", "praise"],
        "transitions": {"question.naming": ["idle"], "praise": ["question.naming"]},
        "events": {
            "question.naming": {"binding": {
                "mode": "replace", "lineId": "same", "inherits": "question.naming",
                "speech": [{"text": "x", "durationMs": 130000}],
                "motions": [{"assetId": "missing", "version": "1"}],
            }},
        },
    }
    errors = validate_profile(profile, EventCatalog(), asset_exists=lambda *_: False)
    assert "required_event_fallback_missing:praise" in errors
    assert "asset_not_found:motions:missing" in errors
    assert any(error.startswith("duration_too_long:") for error in errors)
    assert any(error.startswith("binding_inheritance_cycle:") for error in errors)


def test_phase4_mimic_requires_explicit_vocal_imitation_metadata():
    assert infer_event_key("mimic", {"question": True}) is None
    assert infer_event_key("mimic", {"question": True, "isVocalImitation": True}) == "question.vocal_imitation"
    assert infer_event_key("onomatopoeia", {"question": True}) == "question.vocal_imitation"


def test_phase4_session_profile_version_freezes_server_choice(monkeypatch):
    from app.session.session_model import Session
    from app.sockets import handlers

    session = Session(session_id="phase4-session", metadata={})

    class Manager:
        def update_session(self, value):
            self.value = value

    manager = Manager()
    monkeypatch.setattr(handlers, "get_session_manager", lambda: manager)

    class Robot:
        def __init__(self):
            self.version = "v1"

        def get_active_profile_version(self, **_kwargs):
            return self.version

    robot = Robot()
    monkeypatch.setattr("app.robot.get_robot_service", lambda: robot)
    assert handlers._freeze_active_profile_version(session, course_id="course-1", course_type="naming") == "v1"
    robot.version = "v2"
    assert handlers._freeze_active_profile_version(session, course_id="course-1", course_type="naming") == "v1"
    assert session.metadata["activeProfileVersion"] == "v1"


def test_phase4_demo_has_no_full_expression_socket_module():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "app/sockets/robot_events.py").exists()
    assert "register_robot_events" not in (root / "app/sockets/events.py").read_text(encoding="utf-8")


def test_phase4_batch_upload_reads_only_bounded_sentinel_bytes():
    from app.routes.asset_library import _read_uploads_limited

    class Stream:
        def __init__(self, data):
            self.data = data
            self.read_sizes = []

        def read(self, size=-1):
            self.read_sizes.append(size)
            return self.data[:size]

    class Upload:
        filename = "large.json"
        mimetype = "application/json"

        def __init__(self):
            self.stream = Stream(b"x" * 100)

    class Importer:
        max_item_bytes = 10
        max_total_bytes = 20

    upload = Upload()
    result = _read_uploads_limited([upload], Importer())
    assert len(result[0]["content"]) == 11
    assert upload.stream.read_sizes == [11]
    assert result[0]["oversized"] is True


def test_phase4_deployment_stage_api_is_explicit_and_versioned(tmp_path, monkeypatch):
    from flask import Flask
    from app.routes import interaction_profiles as routes
    from app.storage.repositories.interaction_profile_store import JsonInteractionProfileStore

    store = JsonInteractionProfileStore(Path(tmp_path) / "profiles.json")
    monkeypatch.setattr(routes, "_store", store)
    app = Flask(__name__)
    app.register_blueprint(routes.interaction_profiles_bp)
    client = app.test_client()
    draft = client.put(
        "/api/v2/interaction/profiles/course-1/draft",
        json={"courseType": "naming", "version": "v1", "events": {"question.naming": {"binding": {"mode": "replace"}}}},
    )
    assert draft.status_code == 200
    assert client.post("/api/v2/interaction/profiles/course-1/publish", json={"version": "v1"}).status_code == 200
    deployed = client.post(
        "/api/v2/interaction/profiles/course-1/deploy",
        json={"version": "v1", "stage": "published_canary", "canaryPercent": 25},
    )
    assert deployed.status_code == 200
    assert deployed.get_json()["profile"]["deployment"]["stage"] == "published_canary"


def test_phase4_motion_commit_rolls_back_media_when_index_upsert_fails(tmp_path, monkeypatch):
    import app.robot.batch_asset_import as batch_module
    import app.robot.motion_storage as motion_storage
    from app.robot.batch_asset_import import BatchAssetImporter

    motion_file = Path(tmp_path) / "motions.json"
    original = {"version": 2, "updatedAt": None, "motions": {"old": []}, "motionMeta": {}}
    motion_file.write_text(json.dumps(original), encoding="utf-8")
    monkeypatch.setattr(batch_module, "MOTIONS_FILE", str(motion_file))
    monkeypatch.setattr(motion_storage, "MOTIONS_FILE", str(motion_file))
    importer = BatchAssetImporter(asset_index_path=str(Path(tmp_path) / "asset-index.json"))
    staged = importer.stage(kind="motions", items=[{
        "filename": "new.json",
        "content": json.dumps({
            "format": "dollser-motion", "version": 2, "name": "new",
            "commands": [{"axis": "pitch", "angle": 90, "time": 0, "moveMs": 100}],
        }).encode(),
    }])
    monkeypatch.setattr(importer._asset_index, "upsert", lambda _records: (_ for _ in ()).throw(RuntimeError("index down")))
    try:
        importer.commit(staged["stagingId"])
    except RuntimeError as exc:
        assert str(exc) == "index down"
    else:
        raise AssertionError("commit must expose index failure")
    assert json.loads(motion_file.read_text(encoding="utf-8")) == original
    assert not Path(tmp_path, "asset-index.json").exists()
