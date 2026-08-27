"""第一阶段：关键 HTTP 路由的字段级现状 fixture。"""

import io
import os
import runpy
from types import SimpleNamespace

import pytest
from flask import Flask

from app.routes import config_content, monitor, report
from app.robot import routes as robot_routes


@pytest.fixture(scope="module")
def phase1_root_runtime():
    old = {
        key: os.environ.get(key)
        for key in ("START_TEACHER_FRONTEND", "START_VOICE_SERVICE", "DIALOGUE_ENABLED")
    }
    os.environ["START_TEACHER_FRONTEND"] = "0"
    os.environ["START_VOICE_SERVICE"] = "0"
    os.environ["DIALOGUE_ENABLED"] = "0"
    try:
        yield runpy.run_path("app.py", run_name="phase1_http_runtime")
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _blueprint_app(*blueprints):
    app = Flask("phase1-http-contracts")
    for blueprint in blueprints:
        app.register_blueprint(blueprint)
    return app.test_client()


def test_phase1_http_server_status_field_snapshot(monkeypatch, phase1_root_runtime):
    ns = phase1_root_runtime
    view_globals = ns["app"].view_functions["get_server_status"].__globals__

    class ConfigManager:
        def get_all_config(self):
            return {"global": {"mode": "mock"}}

        def get_snapshot_count(self):
            return 2

        def get_audit_logs(self, limit=1000):
            assert limit == 1000
            return [{"id": 1}]

    class Analysis:
        def get_statistics(self):
            return {"processed": 3}

        def get_all_session_states(self):
            return {"s1": {"status": "idle"}}

    class RobotModule:
        @staticmethod
        def get_robot_service():
            return SimpleNamespace(get_control_mode=lambda: "robot_runtime")

    monkeypatch.setitem(view_globals, "get_config_manager", lambda: ConfigManager())
    monkeypatch.setitem(view_globals, "analysis_service", Analysis())
    monkeypatch.setitem(view_globals, "_collect_model_status", lambda _config: {"pose": "mock"})
    monkeypatch.setitem(view_globals, "get_online_presence_snapshot", lambda: {"teachers": 1})
    monkeypatch.setitem(view_globals, "robot_service", RobotModule)
    monkeypatch.setattr(view_globals["Config"], "get_child_media_mode", staticmethod(lambda: "browser"))
    monkeypatch.setitem(view_globals, "get_media_session_meta", lambda: {"m1": {"status": "active"}})

    response = ns["app"].test_client().get("/api/server/status")
    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "statistics": {"processed": 3},
        "sessions": {"s1": {"status": "idle"}},
        "modelStatus": {"pose": "mock"},
        "globalMode": "mock",
        "snapshotCount": 2,
        "historyCount": 1,
        "onlinePresence": {"teachers": 1},
        "robotControlMode": "robot_runtime",
        "childMediaMode": "browser",
        "mediaSessionMeta": {"m1": {"status": "active"}},
        "robotRuntime": {
            "enabled": False,
            "online": False,
            "reason": "demo_capability_disabled",
        },
        "deployment": "demo-machine",
        "capabilities": {
            "robotMotion": False,
            "robotExpression": False,
            "robotRuntime": False,
            "childAnimation": True,
            "browserSpeech": True,
        },
    }


def test_phase1_http_server_status_error_snapshot(monkeypatch, phase1_root_runtime):
    view_globals = phase1_root_runtime["app"].view_functions[
        "get_server_status"
    ].__globals__

    def fail_config():
        raise RuntimeError("phase1-status-failure")

    monkeypatch.setitem(view_globals, "get_config_manager", fail_config)
    response = phase1_root_runtime["app"].test_client().get("/api/server/status")
    assert response.status_code == 500
    assert response.is_json
    assert response.get_json()["success"] is False
    assert "phase1-status-failure" in response.get_json()["error"]


def test_phase1_http_monitor_snapshot_field_snapshot(monkeypatch):
    class Manager:
        def sync(self, devices):
            assert devices == ["configured-camera"]
            return [{"deviceId": "configured-camera", "hasFrame": True}]

    monkeypatch.setattr(monitor, "get_monitor_snapshot", lambda _id: {"active": True, "id": "t1"})
    monkeypatch.setattr(monitor, "_configured_server_cameras", lambda: ["configured-camera"])
    monkeypatch.setattr(monitor, "get_configured_camera_manager", lambda: Manager())
    response = _blueprint_app(monitor.monitor_bp).get(
        "/api/monitor/snapshot?trainingSessionId=t1"
    )
    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "data": {
            "active": True,
            "id": "t1",
            "ambient": {
                "configuredCount": 1,
                "cameras": [{"deviceId": "configured-camera", "hasFrame": True}],
            },
        },
    }


def test_phase1_http_monitor_snapshot_error_snapshot(monkeypatch):
    monkeypatch.setattr(
        monitor,
        "get_monitor_snapshot",
        lambda _id: (_ for _ in ()).throw(RuntimeError("phase1-monitor-failure")),
    )
    response = _blueprint_app(monitor.monitor_bp).get("/api/monitor/snapshot")
    assert response.status_code == 500
    assert response.get_json() == {
        "success": False,
        "error": "phase1-monitor-failure",
    }


def test_phase1_http_demo_hardware_surfaces_are_disabled():
    client = _blueprint_app(robot_routes.robot_bp)
    motions = client.get("/api/robot/motions")
    emotions = client.get("/api/robot/emotions")
    assert motions.status_code == 410
    assert motions.get_json()["error"] == "demo_capability_disabled"
    assert emotions.status_code == 410
    assert emotions.get_json()["error"] == "demo_capability_disabled"

    imported = client.post("/api/robot/motions/import")
    assert imported.status_code == 410
    missing = client.post("/api/robot/motions/import", data={})
    assert missing.status_code == 410


def test_phase1_http_demo_hardware_block_is_independent_of_service_state():
    client = _blueprint_app(robot_routes.robot_bp)
    motions = client.get("/api/robot/motions")
    emotions = client.get("/api/robot/emotions")
    assert motions.status_code == 410
    assert emotions.status_code == 410
    assert client.get("/api/robot/runtime/status").status_code == 410


def test_phase1_http_report_get_generate_field_snapshots(monkeypatch):
    class Reports:
        def get_for_viewer(self, session_id, role, view):
            return {"sessionId": session_id, "role": role, "view": view}

        def generate(self, session_id, auto_finalize, soft):
            return {"sessionId": session_id, "autoFinalize": auto_finalize, "soft": soft}

    monkeypatch.setattr(report, "get_report_service", lambda: Reports())
    client = _blueprint_app(report.report_bp)
    fetched = client.get("/api/report/train-1?role=teacher&view=published")
    generated = client.post(
        "/api/report/train-1/generate",
        json={"autoFinalize": False, "soft": True},
    )
    assert fetched.status_code == 200
    assert fetched.get_json() == {
        "success": True,
        "data": {"sessionId": "train-1", "role": "teacher", "view": "published"},
    }
    assert generated.status_code == 200
    assert generated.get_json() == {
        "success": True,
        "data": {"sessionId": "train-1", "autoFinalize": False, "soft": True},
    }


def test_phase1_http_report_error_snapshots(monkeypatch):
    class UnpublishedReport:
        def get_for_viewer(self, *_args, **_kwargs):
            raise ValueError("report_not_published")

        def review_status(self, session_id):
            return {
                "trainingSessionId": session_id,
                "publicationStatus": "draft",
            }

    monkeypatch.setattr(report, "get_report_service", lambda: UnpublishedReport())
    client = _blueprint_app(report.report_bp)
    unpublished = client.get("/api/report/train-unpublished")
    assert unpublished.status_code == 409
    assert unpublished.get_json() == {
        "success": False,
        "error": "report_not_published",
        "publicationStatus": "draft",
        "review": {
            "trainingSessionId": "train-unpublished",
            "publicationStatus": "draft",
        },
    }

    class MissingReport:
        def get_for_viewer(self, *_args, **_kwargs):
            raise ValueError("report_not_found")

    monkeypatch.setattr(report, "get_report_service", lambda: MissingReport())
    missing = client.get("/api/report/train-missing")
    assert missing.status_code == 404
    assert missing.get_json() == {
        "success": False,
        "error": "report_not_found",
    }

    class NotFinalizedReport:
        def generate(self, *_args, **_kwargs):
            raise ValueError("not_finalized")

    monkeypatch.setattr(report, "get_report_service", lambda: NotFinalizedReport())
    not_finalized = client.post("/api/report/train-open/generate", json={})
    assert not_finalized.status_code == 409
    assert not_finalized.get_json() == {
        "success": False,
        "error": "not_finalized",
    }


def test_phase1_http_course_types_field_snapshot(monkeypatch):
    class Query:
        def order_by(self, field):
            assert field is CourseType.id
            return self

        def all(self):
            return [SimpleNamespace(id=1, name="pairing"), SimpleNamespace(id=2, name="ordering")]

    class CourseType:
        id = object()
        query = Query()

    monkeypatch.setattr(config_content, "CourseType", CourseType)
    response = _blueprint_app(config_content.config_content_bp).get("/api/config/course-types")
    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "types": [
                {"id": 1, "name": "pairing", "type": "pairing"},
                {"id": 2, "name": "ordering", "type": "ordering"},
        ],
    }


def test_phase1_http_course_types_framework_error_snapshot(monkeypatch):
    class QueryFailure:
        def order_by(self, _field):
            raise RuntimeError("phase1-course-types-failure")

    class CourseTypeFailure:
        id = object()
        query = QueryFailure()

    monkeypatch.setattr(config_content, "CourseType", CourseTypeFailure)
    response = _blueprint_app(config_content.config_content_bp).get(
        "/api/config/course-types"
    )
    assert response.status_code == 500
    assert response.is_json is False
    assert response.content_type.startswith("text/html")
