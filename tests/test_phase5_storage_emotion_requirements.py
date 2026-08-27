import json
import hashlib
import io
from pathlib import Path

import pytest
import yaml


def test_phase5_demo_does_not_publish_expression_asset_controls():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "doll/data/emotions_meta.json").exists()
    emotion_dir = root / "static/resources/Emotions"
    assert not emotion_dir.exists() or not any(emotion_dir.iterdir())
    assert not (root / "static/js/config_content_expressions.js").exists()
    assert not (root / "static/js/config_dialogue_expressions.js").exists()

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


def test_phase5_device_check_requires_browser_permission_without_runtime(monkeypatch):
    from flask import Flask
    from app.routes import control_overview

    class EmptyRegistry:
        @staticmethod
        def list_devices():
            return []

    monkeypatch.setattr(control_overview, "get_device_registry", lambda: EmptyRegistry())
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
    assert body["error"] == "browser_permission_required"
    assert all(item["error"] == "browser_permission_required" for item in body["checks"])


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


def test_phase5_demo_has_no_full_version_expression_page_or_assets():
    root = Path(__file__).resolve().parents[1]
    assert not (root / "templates/robot/emotion.html").exists()
    assert not (root / "static/robot/js/emotion_display.js").exists()
    emotion_dir = root / "static/resources/Emotions"
    assert not emotion_dir.exists() or not any(emotion_dir.iterdir())


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
    monkeypatch.setattr(media_upload.Config, "MEDIA_UPLOAD_SHARED_KEY", "")
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


def test_phase5_child_dialogue_uses_browser_speech_only():
    root = Path(__file__).resolve().parents[1]
    script = (root / "static/js/child_dialogue.js").read_text(encoding="utf-8")
    assert "SpeechRecognition" in script
    assert "startBrowserSpeechRecognition" in script
    assert 'emitDialogueText(text, "browser-speech-recognition")' in script
    assert "child_dialogue_audio" not in script
    assert "/api/v2/voice/health" not in script
    assert "FunASR" not in script
    assert "COOLDOWN_MS = 180" in script


def test_child_dialogue_preserves_browser_transcript_during_tts():
    root = Path(__file__).resolve().parents[1]
    script = (root / "static/js/child_dialogue.js").read_text(encoding="utf-8")
    assert "const COOLDOWN_MS = 180;" in script
    assert "pendingTtsTranscript" in script
    assert "isLikelyTtsEcho" in script
    assert "isBrowserSpeechBusy?.()" in script
    resume_body = script.split("function resumeAsrAfterTts()", 1)[1].split(
        "function maybeResumeListening()", 1
    )[0]
    assert 'emitDialogueText(pendingTranscript, "browser-speech-recognition")' in resume_body


def test_production_start_does_not_launch_local_voice_service():
    root = Path(__file__).resolve().parents[1]
    app_source = (root / "app.py").read_text(encoding="utf-8")
    socket_source = (root / "app/dialogue/sockets.py").read_text(encoding="utf-8")
    pipeline_source = (root / "app/core/pipelines/audio_pipeline.py").read_text(encoding="utf-8")
    analyzer_config = yaml.safe_load(
        (root / "config/analyzers.yaml").read_text(encoding="utf-8")
    )
    assert "start_voice_service(logger)" not in app_source
    assert "from app.dialogue.stt import transcribe_audio_base64" not in socket_source
    assert '"browser_speech_required"' in socket_source
    assert "self._speech_enabled = False" in pipeline_source
    assert analyzer_config["analyzers"]["speech"]["enabled"] is False
    assert analyzer_config["matchers"]["speech"]["enabled"] is False
