"""Server 控制端必须展示后端实际执行状态，不能把入队当成功。"""

import queue
import threading
from pathlib import Path

from flask import Flask

from app.robot.robot_service import RobotService


ROOT = Path(__file__).resolve().parents[1]


class _FakeMutex:
    def __init__(self):
        self.locked = False

    def acquire(self, blocking=False):
        if self.locked:
            return False
        self.locked = True
        return True

    def release(self):
        self.locked = False


def _ledger_service():
    service = object.__new__(RobotService)
    service._sequence_queue = queue.Queue(maxsize=1)
    service._idle_state_lock = threading.RLock()
    service._idle_generation = 0
    service._idle_timer = None
    service._active_sequence_deadline = 0.0
    service._active_sequence_id = None
    service._behavior_busy = False
    service._busy_event_id = None
    service._behavior_audio_waiters = {}
    service._process_behavior_lock = _FakeMutex()
    service._control_mode = "server_osc"
    return service


def test_scheduler_freezes_exact_command_plan_and_component_truth():
    service = _ledger_service()
    plan = {
        "id": "control-preview-1",
        "source": "server_control_preview",
        "motion": "wave",
        "emotion": "happy.mp4",
        "durationMs": 1200,
    }

    assert service._enqueue_sequence(plan) is True
    status = service.get_command_status("control-preview-1")

    assert status["phase"] == "queued"
    assert status["source"] == "server_control_preview"
    assert status["motion"] == "wave"
    assert status["emotion"] == "happy.mp4"
    assert status["components"]["motion"]["status"] == "queued"
    assert status["components"]["expression"]["status"] == "queued"
    assert status["startAtEpochMs"] == plan["startAtEpochMs"]


def test_expression_terminal_is_correlated_to_known_command_only():
    service = _ledger_service()
    service._record_command({
        "id": "expression-1",
        "emotion": "happy.mp4",
        "durationMs": 100,
    })
    service._update_command_status("expression-1", phase="degraded")

    assert service.mark_expression_terminal(
        "missing", status="ended"
    ) is None
    result = service.mark_expression_terminal(
        "expression-1", status="ended", reason="video_ended"
    )

    assert result["components"]["expression"]["status"] == "completed"
    assert result["phase"] == "completed"


def test_control_snapshot_does_not_report_legacy_runtime_as_motion_ready(monkeypatch):
    from app.robot import runtime_registry
    from app.sockets import events as socket_events

    service = _ledger_service()
    service._control_mode = "robot_runtime"
    monkeypatch.setattr(socket_events, "get_online_presence_snapshot", lambda: {})
    monkeypatch.setattr(runtime_registry, "get_runtime_status", lambda: {
        "onlineCount": 1,
        "primary": {
            "online": True,
            "compatible": False,
            "compatibilityReason": "runtime_protocol_missing",
            "capabilities": ["device-preflight-v1"],
            "buildVersion": None,
        },
    })

    targets = service.get_control_snapshot()["targets"]
    assert targets["robotRuntimeOnline"] is True
    assert targets["robotRuntimeCompatible"] is False
    assert targets["motionReady"] is False
    assert targets["motionVerification"] == "runtime_incompatible"
    assert "请升级机器人端" in targets["motionDetail"]


def test_control_snapshot_requires_behavior_sync_capability(monkeypatch):
    from app.robot import runtime_registry
    from app.sockets import events as socket_events

    service = _ledger_service()
    service._control_mode = "robot_runtime"
    monkeypatch.setattr(socket_events, "get_online_presence_snapshot", lambda: {})
    monkeypatch.setattr(runtime_registry, "get_runtime_status", lambda: {
        "onlineCount": 1,
        "primary": {
            "online": True,
            "compatible": True,
            "compatibilityReason": None,
            "capabilities": ["behavior-sync-v1"],
            "buildVersion": "runtime-new",
        },
    })

    targets = service.get_control_snapshot()["targets"]
    assert targets["motionReady"] is True
    assert targets["motionVerification"] == "runtime_http_ack"
    assert targets["robotRuntimeBuildVersion"] == "runtime-new"


def test_operator_stop_marks_active_command_cancelled(monkeypatch):
    service = _ledger_service()
    assert service._enqueue_sequence({
        "id": "stop-me",
        "motion": "wave",
        "emotion": "happy.mp4",
        "durationMs": 1000,
    })
    monkeypatch.setattr(service, "stop_playback", lambda: True)
    monkeypatch.setattr(service, "trigger_emotion", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(service, "get_default_emotion", lambda: "idle.mp4")

    result = service.cancel_active_behavior()

    assert result["success"] is True
    assert result["activeBehaviorId"] == "stop-me"
    assert result["behaviorCancelled"] is True
    assert service.get_command_status("stop-me")["phase"] == "cancelled"


def test_preview_rejects_offline_targets_instead_of_false_success():
    service = _ledger_service()
    service._mapping_resolver = type(
        "Resolver",
        (),
        {"select_motion": staticmethod(lambda motions: motions[0] if motions else None)},
    )()
    service.get_default_emotion = lambda: "idle.mp4"
    service.get_control_snapshot = lambda: {
        "controlMode": "robot_runtime",
        "targets": {
            "motionReady": False,
            "motionDetail": "Robot Runtime 离线",
            "motionVerification": "runtime_http_ack",
            "robotDisplayOnline": False,
        },
    }

    result = service.preview_behavior_sequence({
        "motions": ["wave"],
        "emotion": "happy.mp4",
        "sequence": {},
        "auxType": "question",
    })

    assert result["success"] is False
    assert result["error"] == "control_target_not_ready"
    assert {item["code"] for item in result["missingTargets"]} == {
        "motion_target_offline", "robot_display_offline"
    }
    assert service._sequence_queue.empty()


def test_control_status_http_contract(monkeypatch):
    from app.robot import routes

    class Service:
        @staticmethod
        def get_control_snapshot():
            return {"controlMode": "robot_runtime", "targets": {"motionReady": True}}

        @staticmethod
        def get_command_status(command_id):
            if command_id == "known":
                return {"commandId": "known", "phase": "running"}
            return None

    monkeypatch.setattr(routes, "get_robot_service", lambda: Service())
    app = Flask("server-control-truth")
    app.register_blueprint(routes.robot_bp)
    client = app.test_client()

    control = client.get("/api/robot/control/status")
    assert control.status_code == 200
    assert control.get_json()["control"]["targets"]["motionReady"] is True
    assert client.get("/api/robot/sequence/status/known").get_json()["status"]["phase"] == "running"
    assert client.get("/api/robot/sequence/status/missing").status_code == 404


def test_operational_stop_controls_return_dispatch_truth(monkeypatch):
    from app.routes import control_overview
    import app.audio
    import app.robot

    class Robot:
        @staticmethod
        def cancel_active_behavior():
            return {
                "success": True,
                "activeBehaviorId": "active-1",
                "behaviorCancelled": True,
                "motionStopSent": True,
                "expressionResetSent": True,
                "controlMode": "robot_runtime",
            }

    class Audio:
        calls = []

        @classmethod
        def stop_audio(cls, session_id, immediate=True):
            cls.calls.append((session_id, immediate))
            return True

    monkeypatch.setattr(app.robot, "get_robot_service", lambda: Robot())
    monkeypatch.setattr(app.audio, "get_audio_controller", lambda: Audio())
    app = Flask("server-operational-controls")
    app.register_blueprint(control_overview.control_overview_bp)
    client = app.test_client()

    stopped = client.post("/api/v2/control/actions/stop-robot", json={})
    assert stopped.status_code == 200
    assert stopped.get_json()["behaviorCancelled"] is True
    missing = client.post("/api/v2/control/actions/stop-audio", json={})
    assert missing.status_code == 400
    audio = client.post(
        "/api/v2/control/actions/stop-audio",
        json={"sessionId": "session-1"},
    )
    assert audio.status_code == 200
    assert audio.get_json()["verification"] == "socket_dispatch"
    assert Audio.calls == [("session-1", True)]


def test_audio_stop_is_scoped_to_exact_child_room():
    from app.audio.controller import AudioController

    class Socket:
        def __init__(self):
            self.calls = []

        def emit(self, event, payload, **kwargs):
            self.calls.append((event, payload, kwargs))

    socket = Socket()
    controller = AudioController(socket)

    assert controller.stop_audio("session-exact", immediate=True) is True
    assert len(socket.calls) == 1
    assert socket.calls[0][0] == "stop_audio"
    assert socket.calls[0][2]["room"] == "session_session-exact_child"


def test_server_control_frontend_tracks_terminal_instead_of_trusting_http_200():
    template = (ROOT / "templates/server/config.html").read_text(encoding="utf-8")
    behavior = (ROOT / "static/js/config_behavior_sequence.js").read_text(encoding="utf-8")
    mapping = (ROOT / "static/robot/js/robot_mapping.js").read_text(encoding="utf-8")
    monitor = (ROOT / "static/js/server_monitor.js").read_text(encoding="utf-8")
    display = (ROOT / "static/robot/js/emotion_display.js").read_text(encoding="utf-8")

    assert 'id="behavior-test-status"' in template
    assert "testAction('question', this)" in template
    assert "/robot/emotion" in template
    assert "pollCommandStatus" in behavior
    assert "TERMINAL_PHASES" in behavior
    assert "/api/robot/control/status" in behavior
    assert "data.statusUrl" in behavior
    assert "testBehaviorSequence(auxType, config, triggerButton)" in mapping
    assert "fetchWithLegacyFallback('/api/config/courses', '/api/robot/courses', 'courses')" in mapping
    assert "fetchWithLegacyFallback('/api/students', '/api/robot/students', 'students')" not in mapping
    assert "/mapping/course/${courseId}/item/${itemId}/${auxType}" in mapping
    assert "return ['silent', ...ENGAGEMENT_AUX_TYPES, ...SOCIAL_AUX_TYPES.slice(0, 2)]" in mapping
    assert "return ['silent', ...ENGAGEMENT_AUX_TYPES, ...SOCIAL_AUX_TYPES.slice(2)]" in mapping
    assert "robot.lastCommand" in monitor
    assert "/api/v2/control/actions/stop-robot" in monitor
    assert "/api/v2/control/actions/stop-audio" in monitor
    assert 'id="mon-control-feedback"' in (ROOT / "templates/server.html").read_text(encoding="utf-8")
    assert "role: 'robot_display'" in display
