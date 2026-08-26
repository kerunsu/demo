"""Readable recording layout and no-empty-directory regressions."""

from __future__ import annotations

import json
import io
import uuid

import pytest
from flask import Flask

from app.behavior.models import TrainingSessionRecord
from app.behavior.store import BehaviorStore
from app.config import Config
from app.contracts.models import SessionRef
from app.routes import media_upload
from app.report import service as report_service_module
from app.session.session_manager import SessionManager
from app.services import recording_timeline
from app.storage.repositories.metadata_repository import FileMetadataRepository
from app.storage.session_layout import SessionLayout, atomic_write_json


def test_missing_behavior_reads_do_not_create_uuid_directories(tmp_path):
    root = tmp_path / "behavior"
    store = BehaviorStore(root)
    missing = str(uuid.uuid4())

    assert store.get_training(missing) is None
    assert store.get_summary(missing) is None
    assert store.get_report(missing) is None
    assert store.get_manual_report(missing) is None
    assert store.get_published_report(missing) is None
    store.clear_manual_report(missing)

    assert list(root.iterdir()) == []


def test_behavior_uses_readable_name_and_resolves_training_id_after_restart(tmp_path):
    root = tmp_path / "behavior"
    training_id = str(uuid.uuid4())
    human_dir = "测试生-6-20260824-1"
    store = BehaviorStore(root)
    record = TrainingSessionRecord(
        training_session_id=training_id,
        student_id=7,
        metadata={
            "human_dir_name": human_dir,
            "directory_schema": "readable-session-v1",
        },
    )

    store.save_training(record)
    store.save_report(training_id, {"trainingSessionId": training_id})

    assert (root / human_dir / "training.json").is_file()
    assert not (root / training_id).exists()
    restarted = BehaviorStore(root)
    assert restarted.get_training(training_id).student_id == 7
    assert restarted.get_report(training_id)["trainingSessionId"] == training_id


def test_behavior_binding_rejects_a_readable_name_owned_by_another_training(tmp_path):
    root = tmp_path / "behavior"
    occupied = root / "冲突生-6-20260824-1"
    occupied.mkdir(parents=True)
    (occupied / "training.json").write_text(
        json.dumps({"training_session_id": "training-owner"}),
        encoding="utf-8",
    )
    store = BehaviorStore(root)

    with pytest.raises(ValueError, match="behavior_directory_already_exists"):
        store.bind_directory("training-other", occupied.name)


def test_pending_report_scan_uses_training_id_inside_readable_directory(
    monkeypatch, tmp_path
):
    store = BehaviorStore(tmp_path / "behavior")
    training_id = "training-pending-readable"
    store.save_training(TrainingSessionRecord(
        training_session_id=training_id,
        student_id=12,
        metadata={"human_dir_name": "报告生-8-20260824-1"},
    ))
    store.save_report(training_id, {
        "trainingSessionId": training_id,
        "studentId": 12,
        "publicationStatus": "pending_review",
    })
    monkeypatch.setattr(report_service_module, "get_behavior_store", lambda: store)

    pending = report_service_module.ReportService().list_pending_reviews()

    assert pending[0]["trainingSessionId"] == training_id


def test_layout_binding_and_config_lookup_are_side_effect_free(monkeypatch, tmp_path):
    recordings = tmp_path / "recordings"
    results = tmp_path / "results"
    monkeypatch.setattr(Config, "RECORDINGS_DIR", recordings)
    monkeypatch.setattr(Config, "RESULTS_DIR", results)

    layout = SessionLayout(recordings / "sessions")
    session_ref = SessionRef(media_session_id="media-normalized")
    bound = layout.bind(session_ref, "测试生-8-20260824-1")
    assert not bound.exists()

    metadata = FileMetadataRepository(layout)
    metadata.write(session_ref, {"mediaSessionId": "media-normalized"})
    assert bound.is_dir()

    missing_id = str(uuid.uuid4())
    missing_path = Config.get_recording_path(missing_id)
    assert missing_path == recordings / missing_id
    assert not missing_path.exists()


def test_session_creation_binds_readable_paths_without_creating_directories(
    monkeypatch, tmp_path
):
    recordings = tmp_path / "recordings"
    results = tmp_path / "results"
    monkeypatch.setattr(Config, "RECORDINGS_DIR", recordings)
    monkeypatch.setattr(Config, "RESULTS_DIR", results)
    manager = SessionManager()
    human_dir = "路径生-5-20260824-1"

    session = manager.create_session(
        student_id=5,
        training_session_id="training-readable",
        metadata={"human_dir_name": human_dir},
    )
    try:
        expected = recordings / "sessions" / human_dir
        assert session.video_file_path == str(expected / "video.avi")
        assert session.audio_file_path == str(expected / "audio.wav")
        assert not expected.exists()
        assert not (recordings / session.session_id).exists()
        assert not (results / session.session_id).exists()
    finally:
        recording_timeline.unregister_recording_dir(session.session_id)


def test_session_meta_v2_preserves_extended_tracks_on_finalize(monkeypatch, tmp_path):
    sessions = tmp_path / "sessions"
    monkeypatch.setattr(recording_timeline, "sessions_root", lambda: sessions)
    human_dir = "元数据生-9-20260824-1"
    media_id = "media-meta-v2"
    recording = recording_timeline.begin_recording_session(
        media_session_id=media_id,
        training_session_id="training-meta-v2",
        student_id=9,
        human_dir_name=human_dir,
        n=1,
    )
    meta_path = sessions / human_dir / "session_meta.json"
    initial = json.loads(meta_path.read_text(encoding="utf-8"))
    assert initial["schemaVersion"] == 2
    assert initial["behaviorDirName"] == human_dir
    assert {track["trackId"] for track in initial["tracks"]} == {
        "child_video",
        "child_audio",
    }

    initial["tracks"].append({
        "trackId": "room_camera",
        "kind": "video",
        "role": "primary_environment",
        "filename": "video.environment.avi",
        "quality": {"late": False},
    })
    atomic_write_json(meta_path, initial)
    recording_timeline.finalize_recording_session(
        media_id, status="finalized", duration_sec=12.5
    )

    finalized = json.loads(meta_path.read_text(encoding="utf-8"))
    room_track = next(
        track for track in finalized["tracks"]
        if track["trackId"] == "room_camera"
    )
    assert room_track["quality"] == {"late": False}
    assert finalized["durationSec"] == 12.5
    assert finalized["status"] == "finalized"
    assert not list(recording.dir_path.glob("*.tmp"))


def test_readable_sequence_is_unique_across_sessions_and_behavior(monkeypatch, tmp_path):
    sessions = tmp_path / "sessions"
    behavior = tmp_path / "behavior"
    (sessions / "同名生-6-20260824-1").mkdir(parents=True)
    (behavior / "同名生-6-20260824-2").mkdir(parents=True)
    monkeypatch.setattr(recording_timeline, "sessions_root", lambda: sessions)

    name, number = recording_timeline.allocate_human_dir_name(
        student_id=6,
        student_name="同名生",
        student_age=6,
        date_str="20260824",
        additional_roots=[behavior],
    )

    assert name == "同名生-6-20260824-3"
    assert number == 3


def test_late_runtime_upload_can_restore_readable_binding(monkeypatch, tmp_path):
    session_id = "late-readable-upload"
    human_dir = "补传生-7-20260824-1"
    monkeypatch.setattr(Config, "RECORDINGS_DIR", tmp_path)
    recording_timeline.unregister_recording_dir(session_id)
    app = Flask("late-readable-upload")
    app.register_blueprint(media_upload.media_bp)
    client = app.test_client()
    try:
        response = client.post(
            f"/api/media/{session_id}/upload",
            data={
                "humanDirName": human_dir,
                "video": (io.BytesIO(b"video"), "video.avi"),
            },
            content_type="multipart/form-data",
        )

        assert response.status_code == 200
        assert (tmp_path / "sessions" / human_dir / "video.avi").is_file()
        assert not (tmp_path / session_id).exists()
    finally:
        recording_timeline.unregister_recording_dir(session_id)


def test_invalid_runtime_archive_does_not_leave_readable_empty_directory(
    monkeypatch, tmp_path
):
    session_id = "invalid-readable-upload"
    human_dir = "失败补传生-7-20260824-1"
    monkeypatch.setattr(Config, "RECORDINGS_DIR", tmp_path)
    recording_timeline.unregister_recording_dir(session_id)
    app = Flask("invalid-readable-upload")
    app.register_blueprint(media_upload.media_bp)
    client = app.test_client()
    try:
        response = client.post(
            f"/api/media/{session_id}/upload",
            data={
                "humanDirName": human_dir,
                "trackManifest": json.dumps([{
                    "trackId": "room-camera",
                    "kind": "video",
                    "filename": "video.environment.avi",
                }]),
            },
            content_type="multipart/form-data",
        )

        assert response.status_code == 400
        assert not (tmp_path / "sessions" / human_dir).exists()
    finally:
        recording_timeline.unregister_recording_dir(session_id)
