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
    monkeypatch.setitem(view_globals, "get_runtime_status", lambda: {"online": False})

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
        "robotRuntime": {"online": False},
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
    class Ambient:
        def set_forced(self, value):
            self.forced = value

        def status(self):
            return {"active": True, "forced": self.forced}

    ambient = Ambient()
    monkeypatch.setattr(monitor, "get_monitor_snapshot", lambda _id: {"active": True, "id": "t1"})
    monkeypatch.setattr(monitor, "get_ambient_camera", lambda: ambient)
    response = _blueprint_app(monitor.monitor_bp).get(
        "/api/monitor/snapshot?trainingSessionId=t1"
    )
    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "data": {"active": True, "id": "t1", "ambient": {"active": True, "forced": True}},
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


def test_phase1_http_robot_motion_and_emotion_field_snapshots(monkeypatch):
    class Robot:
        def get_motion_list(self):
            return [{"name": "wave", "frameCount": 2}]

        def get_emotions_payload(self):
            return {"emotions": ["happy.gif"], "default": "happy.gif"}

    monkeypatch.setattr(robot_routes, "get_robot_service", lambda: Robot())
    client = _blueprint_app(robot_routes.robot_bp)
    motions = client.get("/api/robot/motions")
    emotions = client.get("/api/robot/emotions")
    assert motions.status_code == 200
    assert motions.get_json() == {"success": True, "motions": [{"name": "wave", "frameCount": 2}]}
    assert emotions.status_code == 200
    assert emotions.get_json() == {
        "success": True,
        "emotions": ["happy.gif"],
        "default": "happy.gif",
    }

    monkeypatch.setattr(robot_routes, "import_dollser_motion_file", lambda _path, _name: "imported-wave")
    imported = client.post(
        "/api/robot/motions/import",
        data={"file": (io.BytesIO(b'{"frames": []}'), "wave.json")},
        content_type="multipart/form-data",
    )
    assert imported.status_code == 200
    assert imported.get_json() == {
        "success": True,
        "message": 'Motion "imported-wave" imported',
        "motionName": "imported-wave",
    }
    missing = client.post("/api/robot/motions/import", data={})
    assert missing.status_code == 400
    assert missing.get_json() == {"success": False, "error": "file required"}


def test_phase1_http_robot_motion_and_emotion_error_snapshots(monkeypatch):
    class RobotFailures:
        def get_motion_list(self):
            raise RuntimeError("phase1-motion-failure")

        def get_emotions_payload(self):
            raise RuntimeError("phase1-emotion-failure")

    monkeypatch.setattr(robot_routes, "get_robot_service", lambda: RobotFailures())
    client = _blueprint_app(robot_routes.robot_bp)

    motions = client.get("/api/robot/motions")
    emotions = client.get("/api/robot/emotions")
    assert motions.status_code == 500
    assert motions.get_json() == {
        "success": False,
        "error": "phase1-motion-failure",
    }
    assert emotions.status_code == 500
    assert emotions.get_json() == {
        "success": False,
        "error": "phase1-emotion-failure",
    }

    monkeypatch.setattr(
        robot_routes,
        "import_dollser_motion_file",
        lambda *_args: (_ for _ in ()).throw(ValueError("invalid-motion-file")),
    )
    malformed = client.post(
        "/api/robot/motions/import",
        data={"file": (io.BytesIO(b"not-json"), "bad.json")},
        content_type="multipart/form-data",
    )
    assert malformed.status_code == 400
    assert malformed.get_json() == {
        "success": False,
        "error": "invalid-motion-file",
    }


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
            return [SimpleNamespace(id=1, name="命名"), SimpleNamespace(id=2, name="pairing")]

    class CourseType:
        id = object()
        query = Query()

    monkeypatch.setattr(config_content, "CourseType", CourseType)
    response = _blueprint_app(config_content.config_content_bp).get("/api/config/course-types")
    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "types": [
            {"id": 1, "name": "命名", "type": "naming"},
            {"id": 2, "name": "pairing", "type": "pairing"},
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
