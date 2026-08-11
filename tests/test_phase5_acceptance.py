"""第五阶段交付门禁：只验证新增的只读质量视图和批量 ZIP 契约。"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from flask import Flask

from app.routes import asset_library as asset_routes
from app.robot.batch_asset_import import BatchAssetImporter
from app.storage.session_quality import inspect_session_directory


def _motion(name: str) -> bytes:
    return json.dumps({
        "format": "dollser-motion",
        "version": 2,
        "name": name,
        "commands": [{"axis": "pitch", "angle": 90, "time": 0, "moveMs": 100}],
    }).encode("utf-8")


def test_phase5_session_quality_is_read_only_and_reports_legacy_tracks(tmp_path: Path):
    session = tmp_path / "session"
    session.mkdir()
    (session / "video.avi").write_bytes(b"video")
    (session / "audio.wav").write_bytes(b"audio")
    (session / "video.environment.ambient-a.avi").write_bytes(b"ambient")
    (session / "session_meta.json").write_text(json.dumps({
        "durationSec": 3.5,
        "tracks": [{
            "trackId": "ambient-a",
            "kind": "video",
            "role": "environment_secondary",
            "deviceId": "cam-a",
            "required": True,
            "filename": "video.environment.ambient-a.avi",
            "offsetMs": 12,
            "droppedFrames": 2,
            "degradationReasons": ["late_first_frame"],
        }],
    }), encoding="utf-8")
    (session / "timeline.csv").write_text(
        "seg_index,seg_kind,t_start_sec,t_end_sec\n0,course,0,3.5\n",
        encoding="utf-8",
    )
    before = sorted(path.name for path in session.iterdir())

    report = inspect_session_directory(session, include_hash=True)

    assert report["status"] == "valid"
    assert report["storage"]["readOnlyInspection"] is True
    assert report["files"]["video.avi"]["sizeBytes"] == 5
    assert report["files"]["video.avi"]["sha256"]
    assert report["tracks"][0]["trackId"] == "ambient-a"
    assert report["tracks"][0]["droppedFrames"] == 2
    assert "late_first_frame" in report["quality"]["degradationReasons"]
    assert sorted(path.name for path in session.iterdir()) == before


def test_phase5_batch_zip_is_bounded_and_returns_item_progress(tmp_path: Path, monkeypatch):
    import app.robot.batch_asset_import as batch_module
    import app.robot.motion_storage as motion_storage

    motion_file = tmp_path / "motions.json"
    monkeypatch.setattr(batch_module, "MOTIONS_FILE", str(motion_file))
    monkeypatch.setattr(motion_storage, "MOTIONS_FILE", str(motion_file))
    importer = BatchAssetImporter(
        max_item_bytes=4096,
        max_total_bytes=8192,
        asset_index_path=str(tmp_path / "asset-index.json"),
    )
    monkeypatch.setattr(asset_routes, "get_batch_asset_importer", lambda: importer)

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("one.json", _motion("one"))
        bundle.writestr("../escape.json", _motion("escape"))
    archive.seek(0)

    app = Flask(__name__)
    app.register_blueprint(asset_routes.asset_library_bp)
    response = app.test_client().post(
        "/api/v2/assets/batch-import",
        data={"kind": "motions", "files": [(archive, "motions.zip")]},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    stage = response.get_json()["stage"]
    assert stage["progress"] == {"total": 2, "processed": 2, "ready": 1, "failed": 1}
    assert {item["status"] for item in stage["items"]} == {"ready", "failed"}
    assert any(item.get("error") == "unsafe_asset_filename" for item in stage["items"])

    committed = app.test_client().post(
        f"/api/v2/assets/batch-import/{stage['stagingId']}/commit",
        json={"conflict": "skip"},
    )
    assert committed.status_code == 200
    assert committed.get_json()["progress"]["failed"] == 1


def test_phase5_batch_import_default_multipart_contract_remains_compatible(tmp_path: Path, monkeypatch):
    import app.robot.batch_asset_import as batch_module
    import app.robot.motion_storage as motion_storage

    motion_file = tmp_path / "motions.json"
    monkeypatch.setattr(batch_module, "MOTIONS_FILE", str(motion_file))
    monkeypatch.setattr(motion_storage, "MOTIONS_FILE", str(motion_file))
    importer = BatchAssetImporter(asset_index_path=str(tmp_path / "asset-index.json"))
    monkeypatch.setattr(asset_routes, "get_batch_asset_importer", lambda: importer)
    app = Flask(__name__)
    app.register_blueprint(asset_routes.asset_library_bp)

    response = app.test_client().post(
        "/api/v2/assets/batch-import",
        data={"kind": "motions", "files": [(io.BytesIO(_motion("plain")), "plain.json")]},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["stage"]["items"][0]["filename"] == "plain.json"
    assert "content" not in body["stage"]["items"][0]


def test_phase5_media_status_quality_is_opt_in(monkeypatch):
    from app.routes import media_upload as media_routes

    monkeypatch.setattr(media_routes, "get_media_session_meta", lambda _session_id: {"source": "fake"})
    app = Flask(__name__)
    app.register_blueprint(media_routes.media_bp)
    client = app.test_client()

    legacy = client.get("/api/media/phase5/status")
    assert legacy.status_code == 200
    assert legacy.get_json() == {"ok": True, "sessionId": "phase5", "meta": {"source": "fake"}}

    quality = client.get("/api/media/phase5/status?includeQuality=1")
    assert quality.status_code == 200
    assert quality.get_json()["quality"]["storage"]["exists"] is False

    traversal = client.get("/api/media/../database/status?includeQuality=1")
    assert traversal.status_code in {404, 308}
