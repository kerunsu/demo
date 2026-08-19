import json
import hashlib
import io
from pathlib import Path

import pytest


def _box(kind: bytes, payload: bytes) -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + kind + payload


def _minimal_mp4(duration_ms: int = 2500) -> bytes:
    ftyp = _box(b"ftyp", b"isom\x00\x00\x02\x00isommp41")
    mvhd_payload = (
        b"\x00\x00\x00\x00"  # version + flags
        + (0).to_bytes(4, "big")
        + (0).to_bytes(4, "big")
        + (1000).to_bytes(4, "big")
        + int(duration_ms).to_bytes(4, "big")
    )
    return ftyp + _box(b"moov", _box(b"mvhd", mvhd_payload))


def test_phase5_new_emotions_are_mp4_and_legacy_gif_remains_readable(tmp_path, monkeypatch):
    from app.robot import emotion_assets

    static_root = tmp_path / "static"
    emotion_root = static_root / "resources" / "Emotions"
    emotion_root.mkdir(parents=True)
    (emotion_root / "legacy.gif").write_bytes(b"GIF89a")
    monkeypatch.setattr(emotion_assets.Config, "STATIC_DIR", str(static_root))
    monkeypatch.setattr(emotion_assets, "EMOTIONS_META_FILE", str(tmp_path / "emotions_meta.json"))

    name = emotion_assets.save_uploaded_emotion("greeting.mp4", _minimal_mp4(2500))
    assert name == "greeting.mp4"
    assert emotion_assets.get_expression_duration_ms(name) == 2500
    payload = emotion_assets.get_emotions_payload()
    by_name = {item["name"]: item for item in payload["items"]}
    assert by_name["greeting.mp4"]["format"] == "mp4"
    assert by_name["greeting.mp4"]["deprecated"] is False
    assert by_name["legacy.gif"]["deprecated"] is True
    with pytest.raises(ValueError, match="仅允许 .mp4"):
        emotion_assets.save_uploaded_emotion("new.gif", b"GIF89a")


def test_phase5_batch_emotion_import_accepts_mp4_and_rejects_new_gif(tmp_path):
    from app.robot.batch_asset_import import BatchAssetImporter

    importer = BatchAssetImporter(asset_index_path=str(tmp_path / "asset-index.json"))
    stage = importer.stage(kind="emotions", items=[
        {"filename": "hello.mp4", "content": _minimal_mp4(), "mimeType": "video/mp4"},
        {"filename": "legacy-new.gif", "content": b"GIF89a", "mimeType": "image/gif"},
    ])
    by_name = {item["filename"]: item for item in stage["items"]}
    assert by_name["hello.mp4"]["status"] == "ready"
    assert by_name["hello.mp4"]["sourceFormat"] == "mp4"
    assert by_name["legacy-new.gif"]["status"] == "failed"
    assert "emotion_asset_must_be_mp4" in by_name["legacy-new.gif"]["error"]


def test_phase5_session_catalog_groups_files_by_child(tmp_path, monkeypatch):
    from app.storage import session_catalog

    recordings = tmp_path / "recordings"
    session_dir = recordings / "sessions" / "小明-6-20260807-1"
    session_dir.mkdir(parents=True)
    (session_dir / "video.avi").write_bytes(b"video")
    (session_dir / "audio.wav").write_bytes(b"audio")
    (session_dir / "timeline.csv").write_text(
        "seg_index,seg_kind,t_start_sec,t_end_sec\n0,warmup,0,1\n",
        encoding="utf-8",
    )
    (session_dir / "session_meta.json").write_text(json.dumps({
        "mediaSessionId": "media-1",
        "trainingSessionId": "training-1",
        "studentId": 7,
        "status": "finalized",
        "tracks": [
            {"trackId": "child_video", "kind": "video", "role": "primary_child", "filename": "video.avi"},
            {"trackId": "child_audio", "kind": "audio", "role": "primary_child", "filename": "audio.wav"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(session_catalog.Config, "RECORDINGS_DIR", recordings)
    monkeypatch.setattr(session_catalog, "_student_index", lambda: {
        "7": {"id": 7, "name": "小明", "age": 6, "teacher": "王老师"}
    })

    catalog = session_catalog.build_session_catalog()
    assert catalog["storage"]["sessionCount"] == 1
    assert catalog["children"][0]["student"]["name"] == "小明"
    session = catalog["children"][0]["sessions"][0]
    assert session["folderName"] == "小明-6-20260807-1"
    assert {item["filename"] for item in session["files"]} >= {"video.avi", "audio.wav"}
    assert {item["trackId"] for item in session["tracks"]} == {"child_video", "child_audio"}


def test_phase5_session_folder_resolution_rejects_traversal(tmp_path, monkeypatch):
    from app.storage import session_catalog

    recordings = tmp_path / "recordings"
    (recordings / "sessions" / "safe-session").mkdir(parents=True)
    monkeypatch.setattr(session_catalog.Config, "RECORDINGS_DIR", recordings)
    assert session_catalog.resolve_session_folder("safe-session").name == "safe-session"
    with pytest.raises(ValueError, match="invalid_session_folder"):
        session_catalog.resolve_session_folder("../outside")


def test_phase5_session_catalog_does_not_report_stale_recording_as_live(tmp_path, monkeypatch):
    from app.storage import session_catalog

    recordings = tmp_path / "recordings"
    session_dir = recordings / "sessions" / "stale-recording"
    session_dir.mkdir(parents=True)
    (session_dir / "session_meta.json").write_text(json.dumps({
        "mediaSessionId": "media-stale",
        "status": "recording",
    }), encoding="utf-8")
    monkeypatch.setattr(session_catalog.Config, "RECORDINGS_DIR", recordings)
    monkeypatch.setattr(session_catalog, "_student_index", lambda: {})
    monkeypatch.setattr(session_catalog, "_active_recording_ids", lambda: set())

    session = session_catalog.build_session_catalog()["sessions"][0]
    assert session["status"] == "interrupted"
    assert session["persistedStatus"] == "recording"
    assert session["liveActive"] is False
    assert "stale_recording_metadata" in session["degradationReasons"]


def test_phase5_device_check_reports_runtime_offline_without_false_success(monkeypatch):
    from flask import Flask
    from app.routes import control_overview

    class EmptyRegistry:
        @staticmethod
        def list_devices():
            return []

    monkeypatch.setattr(control_overview, "get_device_registry", lambda: EmptyRegistry())
    monkeypatch.setattr(control_overview, "get_runtime_status", lambda: {"primary": None})
    app = Flask(__name__)
    app.register_blueprint(control_overview.control_overview_bp)
    response = app.test_client().post("/api/v2/control/devices/check", json={})
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["allConnected"] is False
    assert {item["deviceId"] for item in body["checks"]} == {
        "default.child.camera", "default.child.microphone"
    }
    assert all(item["error"] == "robot_runtime_offline" for item in body["checks"])


def test_phase5_control_overview_and_local_reveal_are_additive(monkeypatch, tmp_path):
    from flask import Flask
    from app.routes import control_overview

    class EmptyRegistry:
        @staticmethod
        def list_devices():
            return []

    folder = tmp_path / "小明-6-20260807-1"
    folder.mkdir()
    opened = []
    monkeypatch.setattr(control_overview, "get_device_registry", lambda: EmptyRegistry())
    monkeypatch.setattr(control_overview, "get_runtime_status", lambda: {
        "primary": None, "onlineCount": 0, "runtimes": [], "count": 0
    })
    monkeypatch.setattr(control_overview, "build_session_catalog", lambda limit=200: {
        "storage": {"sessionCount": 1, "totalBytes": 12}, "sessions": [], "children": []
    })
    monkeypatch.setattr(control_overview, "resolve_session_folder", lambda name: folder)
    monkeypatch.setattr(control_overview, "_reveal_local_folder", lambda path: opened.append(str(path)))

    app = Flask(__name__)
    app.register_blueprint(control_overview.control_overview_bp)
    client = app.test_client()
    overview = client.get("/api/v2/control/overview")
    assert overview.status_code == 200
    assert overview.get_json()["recordings"]["storage"]["sessionCount"] == 1
    reveal = client.post(f"/api/v2/control/sessions/{folder.name}/reveal")
    assert reveal.status_code == 200
    assert opened == [str(folder)]


def test_phase5_emotion_page_uses_native_single_play_mp4_contract():
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates/robot/emotion.html").read_text(encoding="utf-8")
    script = (root / "static/robot/js/emotion_display.js").read_text(encoding="utf-8")
    assert 'id="emotion-idle-video"' in template
    assert "emotionVideo.loop = false" in script
    assert "emotionVideo.addEventListener('ended'" in script
    assert "playDefaultEmotion();" in script
    assert "function nextVideoBuffer()" in script
    assert "requestVideoFrameCallback" in script
    assert "commitMediaTransition(" in script
    assert "activeMediaElement !== emotionVideo" in script
    assert "activeMediaElement !== idleVideo" in script
    assert "incoming.style.opacity = '0'" in script
    assert "outgoing.style.opacity = '0'" in script
    queued = script[
        script.index("if (isPlayingNonDefault) {") :
        script.index("pendingEmotionEvents.push(eventData)")
    ]
    assert "preloadVideoAsset(emotionName)" in queued
    assert "stageEmotionReady(eventData, emotionName)" in queued


def test_phase5_control_page_explains_device_and_recording_workflow():
    root = Path(__file__).resolve().parents[1]
    template = (root / "templates/server/config.html").read_text(encoding="utf-8")
    script = (root / "static/js/config_phase5.js").read_text(encoding="utf-8")
    assert "设备与录制总览" in template
    assert 'href="/server/config/devices"' in template
    assert 'data-view="phase5"' not in template
    assert "默认设备（无需添加）" in script
    assert "课程录制（按儿童）" in template
    assert "在服务器本机打开文件夹" in script
    assert "/api/v2/control/devices/check" in script
    assert "phase5-device-index" in template
    assert "selector: { index: deviceIndex }" in script
    teacher_app = (root / "teacher_frontend/App.tsx").read_text(encoding="utf-8")
    assert "preflightMode: 'auto'" in teacher_app


def test_phase5_runtime_freezes_stable_environment_track_filenames():
    from robot_runtime.agent import MediaRecorderState

    state = MediaRecorderState()
    tracks = state._prepare_extra_tracks([
        {"deviceId": "env-cam-1", "trackId": "cam-room", "kind": "video", "role": "primary_environment", "owner": "runtime", "enabled": True, "required": True},
        {"deviceId": "env-cam-2", "trackId": "cam-side", "kind": "video", "role": "environment_secondary", "owner": "runtime", "enabled": True},
        {"deviceId": "env-mic-1", "trackId": "mic-room", "kind": "audio", "role": "primary_environment", "owner": "runtime", "enabled": True},
    ])
    assert [item["filename"] for item in tracks] == [
        "video.environment.avi",
        "video.environment.cam-side.avi",
        "audio.environment.wav",
    ]
    assert tracks[0]["required"] is True


def test_phase5_runtime_preflight_requires_first_samples_and_multitrack_capability(monkeypatch):
    from app.acquisition.device_preflight_runtime import perform_device_preflight
    from app.contracts.models import DeviceProfile
    import requests

    class Registry:
        @staticmethod
        def list_devices():
            return [DeviceProfile(
                device_id="env-cam-2", track_id="cam-side", kind="video",
                role="environment_secondary", owner="runtime", required=True,
                selector={"index": 2},
            )]

    class Response:
        status_code = 200
        content = b"{}"

        @staticmethod
        def json():
            return {"ok": True, "checks": [
                {"deviceId": "default.child.camera", "kind": "video", "connected": True},
                {"deviceId": "default.child.microphone", "kind": "audio", "connected": True},
                {"deviceId": "env-cam-2", "kind": "video", "connected": True},
            ]}

    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: Response())
    runtime = {
        "primary": {
            "online": True,
            "compatible": True,
            "advertisedUrl": "http://runtime.invalid",
            "capabilities": ["device-preflight-v1", "multi-track-media-v1"],
        }
    }
    result = perform_device_preflight(Registry(), runtime)
    assert result["ok"] is True
    assert all(item["captureReady"] for item in result["checks"])

    runtime["primary"]["capabilities"] = ["device-preflight-v1"]
    missing_capability = perform_device_preflight(Registry(), runtime)
    assert missing_capability["ok"] is False
    extra = next(item for item in missing_capability["checks"] if item["deviceId"] == "env-cam-2")
    assert extra["error"] == "runtime_multitrack_capability_missing"


def test_phase5_dynamic_track_archive_upload_updates_manifest_atomically(tmp_path, monkeypatch):
    from flask import Flask
    from app.routes import media_upload

    session_dir = tmp_path / "小明-6-20260807-1"
    session_dir.mkdir()
    (session_dir / "session_meta.json").write_text(json.dumps({"tracks": []}), encoding="utf-8")
    monkeypatch.setattr(media_upload.Config, "CHILD_MEDIA_AGENT_KEY", "")
    monkeypatch.setattr(media_upload.Config, "get_recording_path", lambda session_id: session_dir)
    monkeypatch.setattr(media_upload.Config, "get_video_file_path", lambda session_id: session_dir / "video.avi")
    monkeypatch.setattr(media_upload.Config, "get_audio_file_path", lambda session_id: session_dir / "audio.wav")

    content = b"environment-video"
    manifest = [{
        "trackId": "cam-side",
        "deviceId": "env-cam-2",
        "kind": "video",
        "role": "environment_secondary",
        "required": False,
        "filename": "video.environment.cam-side.avi",
        "format": "avi",
        "clockDomain": "runtime.session.monotonic",
        "sha256": hashlib.sha256(content).hexdigest(),
    }]
    app = Flask(__name__)
    app.register_blueprint(media_upload.media_bp)
    response = app.test_client().post(
        "/api/media/media-1/upload",
        data={
            "trackManifest": json.dumps(manifest),
            "track__cam-side": (io.BytesIO(content), "video.environment.cam-side.avi"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert (session_dir / "video.environment.cam-side.avi").read_bytes() == content
    meta = json.loads((session_dir / "session_meta.json").read_text(encoding="utf-8"))
    assert meta["tracks"][0]["trackId"] == "cam-side"

    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    monkeypatch.setattr(media_upload.Config, "get_recording_path", lambda session_id: bad_dir)
    bad_manifest = [{**manifest[0], "sha256": "0" * 64}]
    bad = app.test_client().post(
        "/api/media/media-2/upload",
        data={
            "trackManifest": json.dumps(bad_manifest),
            "track__cam-side": (io.BytesIO(content), "video.environment.cam-side.avi"),
        },
        content_type="multipart/form-data",
    )
    assert bad.status_code == 400
    assert not (bad_dir / "video.environment.cam-side.avi").exists()


def test_phase5_config_center_sync_manifest_and_export_are_reviewable(tmp_path, monkeypatch):
    from flask import Flask
    from app.routes import config_sync

    config_file = tmp_path / "config" / "runtime_modes.yaml"
    config_file.parent.mkdir(parents=True)
    config_file.write_text("child_media_mode: agent\n", encoding="utf-8")
    monkeypatch.setattr(config_sync, "_ROOT", tmp_path)
    monkeypatch.setattr(config_sync, "_iter_sync_files", lambda: iter([(config_file, "configuration")]))
    monkeypatch.setattr(config_sync, "_course_catalog", lambda: {
        "schemaVersion": 1,
        "exportedAt": "now",
        "courses": [{"id": 10, "title": "社交课程", "items": [{"name": "打招呼"}]}],
    })

    app = Flask(__name__)
    app.register_blueprint(config_sync.config_sync_bp)
    client = app.test_client()
    manifest_response = client.get("/api/v2/config/sync/manifest")
    assert manifest_response.status_code == 200
    manifest = manifest_response.get_json()["manifest"]
    assert manifest["fileCount"] == 1
    assert manifest["courseCount"] == 1
    assert manifest["files"][0]["path"].endswith("runtime_modes.yaml")

    export_response = client.get("/api/v2/config/sync/export")
    assert export_response.status_code == 200
    import zipfile
    archive = zipfile.ZipFile(io.BytesIO(export_response.data))
    assert "config/sync_manifest.json" in archive.namelist()
    assert "config/sync/course_catalog.json" in archive.namelist()
    assert "config/runtime_modes.yaml" in archive.namelist()


def test_phase5_voice_health_exposes_unready_stt_without_false_green(monkeypatch):
    from flask import Flask
    from app.routes import voice_status

    class Response:
        ok = True
        content = b"{}"

        @staticmethod
        def json():
            return {
                "status": "ok",
                "sttProvider": "local-funasr",
                "sttProviderStatus": "LOCAL_MODEL_ERROR",
                "sttError": "No module named funasr",
            }

    monkeypatch.setattr(voice_status.requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(voice_status, "_dependency_status", lambda: {
        "torch": False, "funasr": False, "modelscope": False,
    })
    app = Flask(__name__)
    app.register_blueprint(voice_status.voice_status_bp)
    response = app.test_client().get("/api/v2/voice/health")
    body = response.get_json()
    assert response.status_code == 200
    assert body["reachable"] is True
    assert body["ready"] is False
    assert body["dependencies"]["funasr"] is False
    assert "funasr" in body["error"]


def test_phase5_child_dialogue_checks_voice_health_before_listening():
    root = Path(__file__).resolve().parents[1]
    script = (root / "static/js/child_dialogue.js").read_text(encoding="utf-8")
    assert "/api/v2/voice/health" in script
    assert "语音识别不可用" in script
    assert "prerollHasVoice" in script
    assert "COOLDOWN_MS = 180" in script
