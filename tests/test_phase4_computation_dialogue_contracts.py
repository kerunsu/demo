"""第四阶段：模型、事件、交互解析和批量资源的可回滚契约。"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from app.computation.interaction import (
    EventCatalog,
    EventDefinition,
    InteractionResolver,
    LegacyInteractionAdapter,
    dry_run_course_migration,
    infer_event_key,
    validate_profile,
)
from app.computation.model_plugins import ModelPipeline, ModelRegistry
from app.contracts.models import (
    BehaviorPlan,
    DialogueRequest,
    DialogueResponse,
    ModelDescriptor,
    Observation,
    InteractionContext,
    SessionRef,
    TextObservation,
)
from app.robot.batch_asset_import import BatchAssetImporter
from app.storage.repositories.interaction_profile_store import JsonInteractionProfileStore
from app.dialogue.boundary import DialogueGateway, LegacyDialogueAdapter


class _LegacyMapping:
    def parse_aux_type(self, aux):
        if aux.get("question") is True:
            return "question"
        if aux.get("praise") is True:
            return "praise"
        return "silent"

    def find_mapping(self, student_id, course_id, item_id, aux_type):
        return {
            "motions": ["legacy_question.motion" if aux_type == "question" else "legacy_praise.motion"],
            "emotion": "legacy.gif",
            "sequence": {"motionOffsetMs": 120, "audio": {"offsetMs": 80}},
        }


def _dollser(name="new-question"):
    return json.dumps({
        "format": "dollser-motion",
        "version": 2,
        "name": name,
        "commands": [{"axis": "pitch", "angle": 180, "time": 0, "moveMs": 100}],
    }).encode()


def test_phase4_model_plugin_mock_real_selection_and_degraded_paths():
    registry = ModelRegistry()
    descriptor = ModelDescriptor(
        model_id="fake.attention",
        version="1.2.0",
        modalities=("video",),
        capabilities=("attention",),
    )

    class FakeModel:
        def __init__(self, config):
            self.config = config
            self.descriptor = descriptor

        def prepare(self, config=None):
            return {"ok": True}

        def health(self):
            return {"ok": True}

        def analyze(self, batch):
            return Observation(
                observation_id="fixed-observation",
                model_id=descriptor.model_id,
                model_version=descriptor.version,
                session=batch.session,
                modality="video",
                values={"attention": 0.75},
                confidence=0.9,
            )

        def close(self):
            pass

    registry.register(descriptor, FakeModel, mode="mock")
    pipeline = ModelPipeline(registry, max_workers=1, max_pending=1)
    batch = TextObservation(session=SessionRef(session_id="s1"), text="ignored")
    result = pipeline.analyze("fake.attention", batch, mode="real")
    assert result.values["attention"] == 0.75
    assert result.model_version == "1.2.0"
    missing = pipeline.analyze("missing", batch)
    assert missing.missing_reason == "model_not_registered"
    pipeline.close()
    assert pipeline.analyze("fake.attention", batch).missing_reason == "pipeline_closed"


def test_phase4_model_plugin_timeout_is_degraded_and_close_is_repeatable():
    registry = ModelRegistry()
    slow_descriptor = ModelDescriptor("fake.slow", "1", ("text",), ("slow",))

    class SlowModel:
        descriptor = slow_descriptor

        def prepare(self, config=None):
            pass

        def analyze(self, batch):
            time.sleep(0.08)
            return Observation("slow", "fake.slow", "1", batch.session, "text")

        def close(self):
            pass

    registry.register(slow_descriptor, lambda _config: SlowModel(), mode="real")
    pipeline = ModelPipeline(registry, max_workers=1, max_pending=1)
    result = pipeline.analyze("fake.slow", TextObservation(SessionRef(session_id="s2"), "x"), timeout_ms=5)
    assert result.missing_reason == "timeout"
    pipeline.close()
    pipeline.close()


def test_phase4_event_catalog_has_stable_sixteen_events_and_explicit_course_mapping():
    catalog = EventCatalog()
    assert len(catalog.list()) == 16
    assert catalog.get("question.naming").label == "提问-命名"
    assert catalog.get("calm_speech.2s").duration_ms == 2000
    assert infer_event_key("naming", {"question": True}) == "question.naming"
    assert infer_event_key("ordering", {"question": True}) == "question.ordering"
    assert infer_event_key("pairing", {"question": True}) == "question.pairing"
    assert infer_event_key("unknown", {"question": True}) is None


def test_phase4_legacy_question_naming_falls_back_field_for_field(tmp_path: Path):
    store = JsonInteractionProfileStore(tmp_path / "profiles.json")
    resolver = InteractionResolver(store=store, legacy=LegacyInteractionAdapter(_LegacyMapping()))
    context = InteractionContext(
        course_id="naming-1",
        course_type="naming",
        item_id="item-1",
        line_id="question.line.1",
        request_id="req-1",
    )
    plan = resolver.resolve(context, aux={"question": True})
    assert isinstance(plan, BehaviorPlan)
    assert plan.source == "legacy"
    assert plan.context.event_key == "question.naming"
    assert plan.motions[0]["assetId"] == "legacy_question.motion"
    assert plan.expressions[0]["assetId"] == "legacy.gif"
    assert "legacy:fallback" in plan.resolution_trace[-1]


def test_phase4_published_v2_scene_line_inherit_and_replace_do_not_touch_legacy_file(tmp_path: Path):
    profile_path = tmp_path / "profiles.json"
    store = JsonInteractionProfileStore(profile_path)
    store.save_draft({
        "courseId": "course-1",
        "courseType": "naming",
        "version": "v1",
        "events": {
            "question.naming": {
                "scenes": {
                    "red": {
                        "lineBindings": {
                            "line-1": {"mode": "inherit", "motions": ["v2.motion"]}
                        }
                    }
                }
            }
        },
    })
    store.publish("course-1", "v1")
    resolver = InteractionResolver(store=store, legacy=LegacyInteractionAdapter(_LegacyMapping()))
    context = InteractionContext(
        course_id="course-1", course_type="naming", item_id="i1",
        scene_key="red", line_id="line-1", request_id="r1",
    )
    inherited = resolver.resolve(context, aux={"question": True})
    assert inherited.source == "v2.inherit"
    assert inherited.motions[0]["assetId"] == "v2.motion"
    assert inherited.expressions[0]["assetId"] == "legacy.gif"
    assert any("scene=red/line=line-1" in item for item in inherited.resolution_trace)

    store.save_draft({
        "courseId": "course-1", "courseType": "naming", "version": "v2",
        "events": {"question.naming": {"binding": {
            "mode": "replace", "motions": ["replacement.motion"], "emotion": "replacement.gif"
        }}},
    })
    store.publish("course-1", "v2")
    replaced = resolver.resolve(context, aux={"question": True})
    assert replaced.source == "v2.replace"
    assert replaced.motions[0]["assetId"] == "replacement.motion"
    assert replaced.expressions[0]["assetId"] == "replacement.gif"


def test_phase4_profile_draft_is_not_runtime_visible_and_publish_is_atomic(tmp_path: Path):
    path = tmp_path / "profiles.json"
    store = JsonInteractionProfileStore(path)
    store.save_draft({"courseId": "c", "version": "draft-1", "events": {}})
    assert store.get("c") is None
    published = store.publish("c", "draft-1")
    assert published["status"] == "published"
    assert store.get("c")["version"] == "draft-1"


def test_phase4_session_profile_version_freezes_published_behavior_and_rejects_draft(tmp_path: Path):
    store = JsonInteractionProfileStore(tmp_path / "profiles.json")
    for version, motion in (("v1", "motion-v1"), ("v2", "motion-v2")):
        store.save_draft({
            "courseId": "course-freeze",
            "courseType": "naming",
            "version": version,
            "events": {"question.naming": {"binding": {"mode": "replace", "motions": [motion]}}},
        })
        store.publish("course-freeze", version)
    resolver = InteractionResolver(store=store, legacy=LegacyInteractionAdapter(_LegacyMapping()))
    frozen = resolver.resolve(
        InteractionContext(course_id="course-freeze", course_type="naming", profile_version="v1"),
        aux={"question": True},
    )
    assert frozen.profile_version == "v1"
    assert frozen.motions[0]["assetId"] == "motion-v1"
    draft = resolver.resolve(
        InteractionContext(course_id="course-freeze", course_type="naming", profile_version="not-published"),
        aux={"question": True},
    )
    assert draft.source == "legacy"


def test_phase4_batch_import_stages_bad_items_and_default_skip_preserves_existing(tmp_path: Path, monkeypatch):
    import app.robot.batch_asset_import as batch_module
    import app.robot.motion_storage as motion_storage

    motion_file = tmp_path / "motions.json"
    asset_index_file = tmp_path / "asset_index.json"
    monkeypatch.setattr(batch_module, "MOTIONS_FILE", str(motion_file))
    monkeypatch.setattr(motion_storage, "MOTIONS_FILE", str(motion_file))
    importer = BatchAssetImporter(max_item_bytes=10000, max_total_bytes=20000, asset_index_path=str(asset_index_file))
    first = importer.stage(kind="motions", items=[{"filename": "hello.json", "content": _dollser("hello")}])
    assert first["items"][0]["status"] == "ready"
    preview = importer.preview(first["stagingId"])
    assert "content" not in preview["items"][0]
    committed = importer.commit(first["stagingId"])
    assert committed["items"][0]["status"] == "success"

    second = importer.stage(kind="motions", items=[
        {"filename": "hello.json", "content": _dollser("hello-2")},
        {"filename": "bad.json", "content": b"not-json"},
        {"filename": "../escape.json", "content": _dollser("escape")},
    ])
    result = importer.commit(second["stagingId"])
    statuses = {item["filename"]: item["status"] for item in result["items"]}
    assert statuses["hello.json"] == "skipped"
    assert statuses["bad.json"] == "failed"
    assert statuses["../escape.json"] == "failed"
    document = json.loads(motion_file.read_text(encoding="utf-8"))
    assert set(document["motions"]) == {"hello"}
    index = json.loads(asset_index_file.read_text(encoding="utf-8"))
    assert index["assets"][0]["physicalFilename"] == "motions.json"
    assert index["assets"][0]["assetId"].startswith("motions:")


def test_phase4_dialogue_boundary_preserves_wake_context_and_tts_asr_pause():
    class FakeASR:
        def transcribe(self, audio, *, mime_type=None, request=None):
            assert audio == b"audio"
            assert mime_type == "audio/webm"
            assert request.context.course_id == "course-1"
            return {"transcript": "麦麦 告诉我"}

    class FakeProvider:
        def respond(self, request, cancel_event=None):
            assert request.text == "告诉我"
            assert request.context.line_id == "line-1"
            return {"reply": "好的，我们一起看看", "provider": "fake-llm"}

        def health(self):
            return {"ok": True, "provider": "fake-llm"}

    class FakeTTS:
        def synthesize(self, text, *, request):
            return {"assetId": "tts-1", "version": "3", "kind": "audio", "pauseAsr": True}

    gateway = DialogueGateway(
        FakeProvider(),
        asr=FakeASR(),
        tts=FakeTTS(),
        wake_matcher=lambda text: (text.startswith("麦麦"), text[2:].strip()),
        timeout_ms=500,
    )
    request = DialogueRequest(
        request_id="dialogue-1",
        session=SessionRef(session_id="s1"),
        context=InteractionContext(course_id="course-1", line_id="line-1"),
        audio=b"audio",
        mime_type="audio/webm",
        page_context={"questionId": "q1"},
    )
    response = gateway.respond(request)
    assert response.status == "ok"
    assert response.transcript == "麦麦 告诉我"
    assert response.text == "好的，我们一起看看"
    assert response.wake_matched is True
    assert response.asr_paused is True
    assert response.speech[0].audio_asset.asset_id == "tts-1"
    assert response.speech[0].context.course_id == "course-1"
    assert gateway.health()["ok"] is True
    gateway.close()
    gateway.close()


def test_phase4_dialogue_boundary_timeout_is_degraded_without_fake_reply():
    class SlowProvider:
        def respond(self, request, cancel_event=None):
            time.sleep(0.05)
            return {"reply": "不应返回"}

    gateway = DialogueGateway(SlowProvider(), timeout_ms=5)
    response = gateway.respond(
        DialogueRequest(
            request_id="dialogue-timeout",
            session=SessionRef(session_id="s2"),
            context=InteractionContext(course_id="c"),
            text="你好",
            require_wake=False,
        )
    )
    assert response.status == "degraded"
    assert response.degraded is True
    assert response.text is None
    assert response.error == "timeout"
    gateway.close()


def test_phase4_legacy_dialogue_adapter_keeps_reply_and_history_provider_metadata():
    class LegacyService:
        def generate_reply(self, text, *, session_id, page_context):
            assert session_id == "legacy-session"
            assert page_context["questionId"] == "q-old"
            return {"reply": "旧逻辑回复", "provider": "rule", "strategy": "encourage"}

    adapter = LegacyDialogueAdapter(LegacyService())
    response = adapter.respond(
        DialogueRequest(
            request_id="legacy-1",
            session=SessionRef(session_id="legacy-session"),
            context=InteractionContext(question_id="q-old"),
            text="我不会",
            page_context={"questionId": "q-old"},
            require_wake=False,
        )
    )
    assert response.status == "ok"
    assert response.text == "旧逻辑回复"
    assert response.provider == "rule"
    assert response.speech[0].pause_asr is True


def test_phase4_profile_validation_and_event_transition_rules_block_bad_publish():
    catalog = EventCatalog()
    catalog.register(EventDefinition(
        key="custom.waiting",
        label="等待",
        kind="state",
        allowed_from=("idle",),
    ))
    assert catalog.validate_transition("idle", "custom.waiting") is True
    assert catalog.validate_transition("praise", "custom.waiting") is False
    errors = validate_profile(
        {
            "courseId": "c",
            "version": "v1",
            "events": {
                "custom.missing": {"binding": {"mode": "replace", "motions": ["m"]}},
                "custom.waiting": {"binding": {"mode": "invalid", "sequence": []}},
            },
        },
        catalog,
    )
    assert "event_not_registered:custom.missing" in errors
    assert "binding_mode_invalid:custom.waiting:invalid" in errors
    assert "sequence_must_be_object:custom.waiting" in errors


def test_phase4_legacy_migration_is_dry_run_and_never_auto_publishes():
    report = dry_run_course_migration(
        course_id="naming-1",
        course_type="naming",
        legacy_course_entries={
            "question": {"motions": ["old.motion"], "emotion": "old.gif", "sequence": {"audio": {"offsetMs": 80}}},
            "praise": ["praise.motion"],
            "future_custom": {"motions": ["unknown.motion"]},
        },
    )
    assert report["status"] == "review_required"
    assert report["sourceEntryCount"] == 3
    assert report["convertedEventCount"] == 2
    assert report["writes"] == []
    assert report["profile"]["status"] == "draft"
    assert report["profile"]["events"]["question.naming"]["binding"]["emotion"] == "old.gif"
    assert "unmapped_legacy_aux:future_custom" in report["profile"]["migration"]["warnings"]
