"""第一阶段：Runtime 补传、归档元数据和路径注册的现状契约。"""

import hashlib
import io
import json

from flask import Flask

from app.routes import media_upload
from app.services import recording_timeline as timeline


def _media_client(monkeypatch, tmp_path):
    app = Flask("phase1-media-upload")
    app.register_blueprint(media_upload.media_bp)
    monkeypatch.setattr(media_upload.Config, "RECORDINGS_DIR", tmp_path)
    return app.test_client()


def _upload_payload(video_bytes, audio_bytes, **fields):
    data = {
        "video": (io.BytesIO(video_bytes), "video-upload.avi"),
        "audio": (io.BytesIO(audio_bytes), "audio-upload.wav"),
    }
    data.update(fields)
    return data


def test_phase1_upload_checksum_archive_and_registry_contract(monkeypatch, tmp_path):
    session_id = "phase1-late-runtime-upload"
    human_dir = "phase1-student-6-20260806-1"
    video = b"fake-video-bytes"
    audio = b"fake-audio-bytes"
    timeline.register_recording_dir(session_id, human_dir)
    client = _media_client(monkeypatch, tmp_path)

    try:
        response = client.post(
            f"/api/media/{session_id}/upload",
            data=_upload_payload(
                video,
                audio,
                sha256_video=hashlib.sha256(video).hexdigest(),
                sha256_audio=hashlib.sha256(audio).hexdigest(),
                duration="12.5",
            ),
            content_type="multipart/form-data",
        )

        assert response.status_code == 200
        body = response.get_json()
        assert body["ok"] is True
        assert body["sessionId"] == session_id
        assert body["source"] == "agent_local"
        assert set(body["saved"]) == {"video", "audio"}
        assert body["checksums"] == {
            "video": hashlib.sha256(video).hexdigest(),
            "audio": hashlib.sha256(audio).hexdigest(),
        }

        session_dir = tmp_path / "sessions" / human_dir
        archive = json.loads(
            (session_dir / "archive_meta.json").read_text(encoding="utf-8")
        )
        assert archive == {
            "source": "agent_local",
            "sessionId": session_id,
            "duration": "12.5",
            "checksums": body["checksums"],
            "saved": body["saved"],
        }
        assert (session_dir / "video.avi").read_bytes() == video
        assert (session_dir / "audio.wav").read_bytes() == audio
        assert timeline.resolve_recording_dir(session_id) == session_dir

        # Current implementation accepts a late agent upload even after the
        # active in-memory recording is absent; this is a compatibility fact.
        timeline.finalize_recording_session(session_id, status="finalized")
        late = client.post(
            f"/api/media/{session_id}/upload",
            data={"video": (io.BytesIO(b"late-video"), "late.avi")},
            content_type="multipart/form-data",
        )
        assert late.status_code == 200
        assert late.get_json()["ok"] is True
        assert (session_dir / "video.realtime.avi").read_bytes() == video
        assert (session_dir / "video.avi").read_bytes() == b"late-video"
    finally:
        timeline.unregister_recording_dir(session_id)


def test_phase1_upload_checksum_mismatch_is_logged_but_not_rejected(
    monkeypatch, tmp_path
):
    session_id = "phase1-checksum-mismatch"
    timeline.register_recording_dir(session_id, "checksum-mismatch-1")
    client = _media_client(monkeypatch, tmp_path)
    try:
        response = client.post(
            f"/api/media/{session_id}/upload",
            data={
                "video": (io.BytesIO(b"actual"), "video.avi"),
                "sha256_video": "not-the-real-sha256",
            },
            content_type="multipart/form-data",
        )
        assert response.status_code == 200
        assert response.get_json()["ok"] is True
        assert response.get_json()["checksums"]["video"] == hashlib.sha256(
            b"actual"
        ).hexdigest()
    finally:
        timeline.unregister_recording_dir(session_id)


def test_phase1_upload_duplicate_is_repeatable_and_finalize_is_idempotent(
    monkeypatch, tmp_path
):
    session_id = "phase1-duplicate-upload"
    timeline.register_recording_dir(session_id, "duplicate-upload-1")
    client = _media_client(monkeypatch, tmp_path)
    try:
        payload = {"video": (io.BytesIO(b"same-video"), "video.avi")}
        first = client.post(
            f"/api/media/{session_id}/upload",
            data=payload,
            content_type="multipart/form-data",
        )
        second = client.post(
            f"/api/media/{session_id}/upload",
            data={"video": (io.BytesIO(b"same-video"), "video.avi")},
            content_type="multipart/form-data",
        )
        assert first.status_code == second.status_code == 200
        assert first.get_json()["checksums"] == second.get_json()["checksums"]
        assert (tmp_path / "sessions" / "duplicate-upload-1" / "video.realtime.avi").read_bytes() == b"same-video"

        # finalize_recording_session is a no-op for an already finalized or
        # unknown active registry entry, and the late upload remains usable.
        assert timeline.finalize_recording_session(session_id, status="finalized") is None
        assert timeline.finalize_recording_session(session_id, status="finalized") is None
        late = client.post(
            f"/api/media/{session_id}/upload",
            data={"audio": (io.BytesIO(b"late-audio"), "audio.wav")},
            content_type="multipart/form-data",
        )
        assert late.status_code == 200
        assert late.get_json()["ok"] is True
    finally:
        timeline.unregister_recording_dir(session_id)


def test_phase1_status_can_acknowledge_archive_after_server_memory_loss(
    monkeypatch, tmp_path
):
    session_id = "phase1-persisted-archive-ack"
    human_dir = "persisted-archive-ack-1"
    session_dir = tmp_path / "sessions" / human_dir
    session_dir.mkdir(parents=True)
    (session_dir / "archive_meta.json").write_text(
        json.dumps({
            "source": "agent_local",
            "sessionId": session_id,
            "checksums": {"video": "video-sha", "audio": "audio-sha"},
            "saved": {"video": "server-private-path"},
        }),
        encoding="utf-8",
    )
    (session_dir / "session_meta.json").write_text(
        json.dumps({"mediaSessionId": session_id, "humanDirName": human_dir}),
        encoding="utf-8",
    )
    timeline.unregister_recording_dir(session_id)
    client = _media_client(monkeypatch, tmp_path)
    try:
        response = client.get(
            f"/api/media/{session_id}/status?includeArchive=1"
        )
        assert response.status_code == 200
        archive = response.get_json()["archive"]
        assert archive == {
            "completed": True,
            "source": "agent_local",
            "checksums": {"video": "video-sha", "audio": "audio-sha"},
            "tracks": [],
        }
        assert "server-private-path" not in response.get_data(as_text=True)
    finally:
        timeline.unregister_recording_dir(session_id)
