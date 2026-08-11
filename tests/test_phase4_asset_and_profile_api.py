"""第四阶段控制端新增 API 的最小真实 Flask 契约。"""

from __future__ import annotations

import io
import json
from pathlib import Path

from flask import Flask

from app.computation.interaction import EventCatalog
from app.routes import asset_library as asset_routes
from app.routes import interaction_profiles as profile_routes
from app.robot.batch_asset_import import BatchAssetImporter
from app.storage.repositories.interaction_profile_store import JsonInteractionProfileStore


def _motion(name: str = "one") -> bytes:
    return json.dumps({
        "format": "dollser-motion",
        "version": 2,
        "name": name,
        "commands": [{"axis": "pitch", "angle": 90, "time": 0, "moveMs": 100}],
    }).encode("utf-8")


def test_phase4_batch_asset_api_supports_zero_one_many_preview_commit_retry_and_rollback(tmp_path: Path, monkeypatch):
    import app.robot.batch_asset_import as batch_module
    import app.robot.motion_storage as motion_storage

    motion_file = tmp_path / "motions.json"
    monkeypatch.setattr(batch_module, "MOTIONS_FILE", str(motion_file))
    monkeypatch.setattr(motion_storage, "MOTIONS_FILE", str(motion_file))
    importer = BatchAssetImporter(asset_index_path=str(tmp_path / "asset-index.json"))
    monkeypatch.setattr(asset_routes, "get_batch_asset_importer", lambda: importer)

    app = Flask(__name__)
    app.register_blueprint(asset_routes.asset_library_bp)
    client = app.test_client()

    empty = client.post("/api/v2/assets/batch-import", data={"kind": "motions"})
    assert empty.status_code == 400
    assert empty.get_json()["success"] is False

    staged = client.post(
        "/api/v2/assets/batch-import",
        data={
            "kind": "motions",
            "files": [
                (io.BytesIO(_motion("one")), "one.json"),
                (io.BytesIO(_motion("two")), "two.json"),
            ],
        },
        content_type="multipart/form-data",
    )
    assert staged.status_code == 200
    stage = staged.get_json()["stage"]
    assert len(stage["items"]) == 2
    assert all("content" not in item for item in stage["items"])

    preview = client.get(f"/api/v2/assets/batch-import/{stage['stagingId']}")
    assert preview.status_code == 200
    committed = client.post(f"/api/v2/assets/batch-import/{stage['stagingId']}/commit", json={})
    assert committed.status_code == 200
    assert committed.get_json()["success"] is True
    retry = client.post(f"/api/v2/assets/batch-import/{stage['stagingId']}/commit", json={})
    assert retry.status_code == 200
    assert retry.get_json() == committed.get_json()

    staged_one = client.post(
        "/api/v2/assets/batch-import",
        data={"kind": "motions", "files": [(io.BytesIO(_motion("three")), "three.json")]},
        content_type="multipart/form-data",
    ).get_json()["stage"]
    rolled_back = client.post(f"/api/v2/assets/batch-import/{staged_one['stagingId']}/rollback")
    assert rolled_back.status_code == 200
    assert rolled_back.get_json()["status"] == "rolled_back"


def test_phase4_interaction_profile_api_keeps_drafts_off_runtime_and_validates_publish(tmp_path: Path, monkeypatch):
    store = JsonInteractionProfileStore(tmp_path / "profiles.json")
    catalog = EventCatalog()
    monkeypatch.setattr(profile_routes, "_store", store)
    monkeypatch.setattr(profile_routes, "_event_catalog", catalog)
    monkeypatch.setattr(profile_routes, "_event_file", tmp_path / "events.json")

    app = Flask(__name__)
    app.register_blueprint(profile_routes.interaction_profiles_bp)
    client = app.test_client()

    events = client.get("/api/v2/interaction/events")
    assert events.status_code == 200
    assert len(events.get_json()["events"]) == 16

    draft = client.put(
        "/api/v2/interaction/profiles/course-1/draft",
        json={
            "courseType": "naming",
            "version": "v1",
            "events": {"question.naming": {"binding": {"mode": "replace", "motions": ["m"]}}},
        },
    )
    assert draft.status_code == 200
    assert client.get("/api/v2/interaction/profiles/course-1").status_code == 404
    published = client.post("/api/v2/interaction/profiles/course-1/publish", json={"version": "v1"})
    assert published.status_code == 200
    assert published.get_json()["profile"]["status"] == "published"

    bad_draft = client.put(
        "/api/v2/interaction/profiles/course-1/draft",
        json={"version": "v2", "events": {"not.registered": {"binding": {"mode": "replace"}}}},
    )
    assert bad_draft.status_code == 200
    bad_publish = client.post("/api/v2/interaction/profiles/course-1/publish", json={"version": "v2"})
    assert bad_publish.status_code == 400
    assert "event_not_registered:not.registered" in bad_publish.get_json()["details"]
