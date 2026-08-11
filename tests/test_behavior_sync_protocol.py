from __future__ import annotations

import queue
import threading
import time
import types
from collections import OrderedDict

import robot_runtime.agent as runtime_agent
import app.robot.robot_service as robot_service_module
from app.robot.robot_service import RobotService


def _envelope(**overrides):
    payload = {
        "protocolVersion": "1",
        "sessionId": "session-sync",
        "requestId": "request-sync",
        "behaviorId": "behavior-sync",
        "startAtServerMs": 2_000_000_000_000,
        "modality": "motion",
    }
    payload.update(overrides)
    return payload


def test_runtime_prepare_commit_preserves_exact_envelope(monkeypatch):
    monkeypatch.setattr(runtime_agent, "AGENT_KEY", "")
    monkeypatch.setattr(runtime_agent, "_prepared_motion", None)
    monkeypatch.setattr(runtime_agent, "_active_motion_envelope", None)
    starts = []
    events = []

    def fake_start(request_id, frames, **kwargs):
        starts.append((request_id, frames, kwargs["start_at_epoch_ms"]))
        kwargs["on_event"]("started", None)
        kwargs["on_event"]("ended", None)

    monkeypatch.setattr(runtime_agent.playback_state, "start", fake_start)
    monkeypatch.setattr(
        runtime_agent,
        "_emit_motion_event",
        lambda envelope, status, reason: events.append((dict(envelope), status, reason)),
    )
    client = runtime_agent.app.test_client()
    payload = {**_envelope(), "motionName": "wave", "frames": [{"time": 0, "pose": {}}]}

    prepared = client.post("/behavior/prepare", json=payload)
    assert prepared.status_code == 200
    assert prepared.get_json()["ready"] is True
    duplicate = client.post("/behavior/prepare", json=payload)
    assert duplicate.get_json()["idempotentReplay"] is True

    stale = client.post(
        "/behavior/commit",
        json={**_envelope(requestId="wrong"), "startAtRuntimeMs": 2_000_000_000_020},
    )
    assert stale.status_code == 409
    assert starts == []

    committed = client.post(
        "/behavior/commit",
        json={**_envelope(), "startAtRuntimeMs": 2_000_000_000_020},
    )
    assert committed.status_code == 200
    assert committed.get_json()["committed"] is True
    assert starts == [("request-sync", [{"pose": {}, "time": 0}], 2_000_000_000_020)]
    assert [(event[1], event[0]["requestId"]) for event in events] == [
        ("started", "request-sync"),
        ("ended", "request-sync"),
    ]


def test_runtime_rejects_incomplete_behavior_envelope(monkeypatch):
    monkeypatch.setattr(runtime_agent, "AGENT_KEY", "")
    monkeypatch.setattr(runtime_agent, "_prepared_motion", None)
    response = runtime_agent.app.test_client().post(
        "/behavior/prepare",
        json={**_envelope(sessionId=""), "frames": [{"time": 0, "pose": {}}]},
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "behavior_identity_incomplete"


def test_new_session_supersedes_abandoned_prepared_motion(monkeypatch):
    monkeypatch.setattr(runtime_agent, "AGENT_KEY", "")
    monkeypatch.setattr(runtime_agent, "_active_motion_envelope", None)
    old = _envelope(
        sessionId="old-session",
        requestId="old-request",
        behaviorId="old-behavior",
    )
    monkeypatch.setattr(runtime_agent, "_prepared_motion", {
        "envelope": old,
        "frames": [{"time": 0, "pose": {}}],
        "preparedAtRuntimeMs": int(time.time() * 1000),
    })
    new_payload = {
        **_envelope(
            sessionId="new-session",
            requestId="new-request",
            behaviorId="new-behavior",
        ),
        "frames": [{"time": 0, "pose": {}}],
    }

    response = runtime_agent.app.test_client().post(
        "/behavior/prepare", json=new_payload
    )
    assert response.status_code == 200
    assert runtime_agent._prepared_motion["envelope"]["behaviorId"] == "new-behavior"


def test_expired_prepare_cannot_block_next_behavior_in_same_session(monkeypatch):
    monkeypatch.setattr(runtime_agent, "AGENT_KEY", "")
    monkeypatch.setattr(runtime_agent, "_active_motion_envelope", None)
    expired = _envelope(requestId="expired-request", behaviorId="expired-behavior")
    monkeypatch.setattr(runtime_agent, "_prepared_motion", {
        "envelope": expired,
        "frames": [{"time": 0, "pose": {}}],
        "preparedAtRuntimeMs": (
            int(time.time() * 1000) - runtime_agent.PREPARED_MOTION_TTL_MS - 1
        ),
    })
    next_payload = {
        **_envelope(requestId="next-request", behaviorId="next-behavior"),
        "frames": [{"time": 0, "pose": {}}],
    }

    response = runtime_agent.app.test_client().post(
        "/behavior/prepare", json=next_payload
    )
    assert response.status_code == 200
    assert runtime_agent._prepared_motion["envelope"]["behaviorId"] == "next-behavior"


def test_runtime_cancel_requires_exact_active_envelope(monkeypatch):
    monkeypatch.setattr(runtime_agent, "AGENT_KEY", "")
    monkeypatch.setattr(runtime_agent, "_prepared_motion", None)
    monkeypatch.setattr(runtime_agent, "_active_motion_envelope", _envelope())
    stops = []
    monkeypatch.setattr(runtime_agent.playback_state, "stop", lambda: stops.append(True))
    client = runtime_agent.app.test_client()

    stale = client.post(
        "/behavior/cancel",
        json=_envelope(requestId="stale-request"),
    )
    assert stale.status_code == 409
    assert stops == []
    assert runtime_agent._active_motion_envelope == _envelope()

    exact = client.post("/behavior/cancel", json=_envelope())
    assert exact.status_code == 200
    assert exact.get_json()["cancelled"] is True
    assert stops == [True]
    assert runtime_agent._active_motion_envelope is None


def test_runtime_conditional_stop_cannot_stop_newer_request(monkeypatch):
    monkeypatch.setattr(runtime_agent, "AGENT_KEY", "")
    current = {"request_id": "formal-request"}
    calls = []

    class FakePlayback:
        @property
        def current_request_id(self):
            return current["request_id"]

        def stop(self, expected_request_id=None):
            calls.append(expected_request_id)
            if expected_request_id and expected_request_id != current["request_id"]:
                return False
            current["request_id"] = None
            return True

    monkeypatch.setattr(runtime_agent, "playback_state", FakePlayback())
    response = runtime_agent.app.test_client().post(
        "/osc/stop",
        json={"requestId": "old-idle", "onlyIfCurrent": True},
    )

    assert response.status_code == 200
    assert response.get_json()["stopped"] is False
    assert response.get_json()["currentRequestId"] == "formal-request"
    assert calls == ["old-idle"]


def _service():
    service = object.__new__(RobotService)
    service._sequence_queue = queue.Queue(maxsize=1)
    service._idle_state_lock = threading.RLock()
    service._idle_generation = 0
    service._idle_timer = None
    service._active_sequence_id = None
    service._active_sequence_deadline = 0.0
    service._behavior_busy = False
    service._busy_event_id = None
    service._behavior_audio_waiters = {}
    service._command_status = OrderedDict()
    service._command_status_lock = threading.RLock()
    service._control_mode = "robot_runtime"
    return service


def test_server_prepares_and_commits_same_motion_identity(monkeypatch):
    service = _service()
    assert service.reserve_behavior(
        behavior_id="behavior-sync",
        request_id="request-sync",
        session_id="session-sync",
    )["accepted"]
    service._behavior_audio_waiters["behavior-sync"]["motionExpected"] = False
    monkeypatch.setattr(
        robot_service_module,
        "get_primary_runtime",
        lambda: {
            "advertisedUrl": "http://runtime.invalid",
            "capabilities": ["behavior-sync-v1"],
        },
    )
    monkeypatch.setattr(
        robot_service_module,
        "get_scaled_motion_frames",
        lambda _name: [{"time": 0, "moveMs": 20, "pose": {}}],
    )
    requests = []

    def post(path, payload):
        requests.append((path, dict(payload)))
        if path == "/behavior/prepare":
            return {"ok": True, "ready": True, "runtimeEpochMs": 1_000_000}
        return {"ok": True, "committed": True}

    service._runtime_json_post = post
    start_at_server_ms = int(time.time() * 1000) + 5_000
    plan = {
        "id": "behavior-sync",
        "protocolVersion": "1",
        "sessionId": "session-sync",
        "requestId": "request-sync",
        "startAtEpochMs": start_at_server_ms,
        "motionOffsetMs": 50,
        "motion": "wave",
    }
    assert service._prepare_runtime_motion(plan) is True
    assert service._commit_runtime_motion(plan) is True
    prepare_payload = requests[0][1]
    commit_payload = requests[1][1]
    for field in ("protocolVersion", "sessionId", "requestId", "behaviorId", "modality"):
        assert commit_payload[field] == prepare_payload[field]
    assert prepare_payload["startAtServerMs"] == start_at_server_ms + 50
    assert "frames" in prepare_payload
    assert "frames" not in commit_payload
    service.abort_behavior("behavior-sync")


def test_server_abort_fans_out_one_exact_cancel(monkeypatch):
    service = _service()
    assert service.reserve_behavior(
        behavior_id="behavior-sync",
        request_id="request-sync",
        session_id="session-sync",
    )["accepted"]
    waiter = service._behavior_audio_waiters["behavior-sync"]
    waiter["startAtServerMs"] = 2_000_000
    waiter["runtimePrepareAttempted"] = True
    waiter["runtimeMotionEnvelope"] = _envelope(startAtServerMs=2_000_050)

    socket_events = []
    runtime_requests = []

    class Socket:
        @staticmethod
        def emit(event, payload, **kwargs):
            socket_events.append((event, dict(payload), kwargs))

    monkeypatch.setattr(robot_service_module, "_socketio", Socket())
    service._runtime_json_post = lambda path, payload: (
        runtime_requests.append((path, dict(payload)))
        or {"ok": True, "cancelled": True}
    )

    assert service.abort_behavior("behavior-sync") is True
    event, payload, kwargs = socket_events[0]
    assert event == "behavior_cancel"
    assert kwargs == {}
    assert payload["sessionId"] == "session-sync"
    assert payload["requestId"] == "request-sync"
    assert payload["behaviorId"] == "behavior-sync"
    assert runtime_requests == [
        ("/behavior/cancel", _envelope(startAtServerMs=2_000_050))
    ]


def test_motion_terminal_requires_exact_three_ids_and_is_idempotent():
    service = _service()
    assert service.reserve_behavior(
        behavior_id="behavior-sync",
        request_id="request-sync",
        session_id="session-sync",
    )["accepted"]
    waiter = service._behavior_audio_waiters["behavior-sync"]
    waiter["motionExpected"] = True
    assert service.mark_behavior_motion_event(
        behavior_id="behavior-sync",
        request_id="stale-request",
        session_id="session-sync",
        modality="motion",
        status="ended",
    ) is None
    assert waiter["motionDone"].is_set() is False
    terminal = service.mark_behavior_motion_event(
        behavior_id="behavior-sync",
        request_id="request-sync",
        session_id="session-sync",
        modality="motion",
        status="ended",
    )
    assert terminal["idempotentReplay"] is False
    replay = service.mark_behavior_motion_event(
        behavior_id="behavior-sync",
        request_id="request-sync",
        session_id="session-sync",
        modality="motion",
        status="ended",
    )
    assert replay["idempotentReplay"] is True
    service.abort_behavior("behavior-sync")


def test_speech_and_expression_terminals_reject_incomplete_envelopes():
    service = _service()
    assert service.reserve_behavior(
        behavior_id="behavior-sync",
        request_id="request-sync",
        session_id="session-sync",
    )["accepted"]
    service._record_command({
        "id": "behavior-sync",
        "protocolVersion": "1",
        "requestId": "request-sync",
        "sessionId": "session-sync",
        "emotion": "happy.gif",
        "motion": None,
        "durationMs": 100,
    })
    waiter = service._behavior_audio_waiters["behavior-sync"]
    waiter["expressionExpected"] = True
    waiter["requiredModalities"] = frozenset({"expression", "speech"})
    waiter["modalitiesFrozen"] = True
    assert service.set_behavior_audio_expected(
        "behavior-sync", 1, session_id="session-sync"
    )
    assert service.mark_behavior_audio_complete(
        behavior_id="behavior-sync",
        session_id="session-sync",
        completion_key="missing-envelope",
    ) is None
    assert service.mark_behavior_audio_complete(
        behavior_id="behavior-sync",
        request_id="request-sync",
        session_id="session-sync",
        modality="speech",
        status="ended",
        completion_key="exact-envelope",
    ) == "behavior-sync"

    assert service.mark_expression_terminal(
        "behavior-sync",
        request_id="stale-request",
        session_id="session-sync",
        modality="expression",
        status="ended",
    ) is None
    exact = service.mark_expression_terminal(
        "behavior-sync",
        request_id="request-sync",
        session_id="session-sync",
        modality="expression",
        status="ended",
    )
    assert exact["components"]["expression"]["status"] == "completed"
    service.abort_behavior("behavior-sync")


def test_client_ready_ack_requires_exact_envelope_and_dedupes_speech_keys():
    service = _service()
    assert service.reserve_behavior(
        behavior_id="behavior-sync",
        request_id="request-sync",
        session_id="session-sync",
    )["accepted"]
    waiter = service._behavior_audio_waiters["behavior-sync"]
    waiter["sequenceEnqueued"] = True
    waiter["expressionExpected"] = True
    assert service.set_behavior_animation_expected(
        "behavior-sync", True, session_id="session-sync"
    )
    assert service.set_behavior_audio_expected(
        "behavior-sync", 2, session_id="session-sync"
    )

    assert service.mark_behavior_modality_ready(
        behavior_id="behavior-sync",
        request_id="stale-request",
        session_id="session-sync",
        modality="expression",
    ) is None
    assert service.mark_behavior_modality_ready(
        behavior_id="behavior-sync",
        request_id="request-sync",
        session_id="session-sync",
        modality="expression",
    )["allRequiredReady"] is False
    assert service.mark_behavior_modality_ready(
        behavior_id="behavior-sync",
        request_id="request-sync",
        session_id="session-sync",
        modality="childAnimation",
    )["allRequiredReady"] is False
    first = service.mark_behavior_modality_ready(
        behavior_id="behavior-sync",
        request_id="request-sync",
        session_id="session-sync",
        modality="speech",
        readiness_key="speech-1",
    )
    replay = service.mark_behavior_modality_ready(
        behavior_id="behavior-sync",
        request_id="request-sync",
        session_id="session-sync",
        modality="speech",
        readiness_key="speech-1",
    )
    assert first["speechReadyCount"] == replay["speechReadyCount"] == 1
    final = service.mark_behavior_modality_ready(
        behavior_id="behavior-sync",
        request_id="request-sync",
        session_id="session-sync",
        modality="speech",
        readiness_key="speech-2",
    )
    assert final["allRequiredReady"] is True
    assert waiter["modalityReady"].is_set() is True

    waiter["sequenceEnqueued"] = False
    service.abort_behavior("behavior-sync")


def test_commit_does_not_cancel_when_expression_ready_ack_is_late():
    service = _service()
    assert service.reserve_behavior(
        behavior_id="ready-behavior",
        request_id="ready-request",
        session_id="ready-session",
    )["accepted"]
    plan = {
        "id": "ready-behavior",
        "protocolVersion": "1",
        "requestId": "ready-request",
        "sessionId": "ready-session",
        "emotion": "happy.gif",
        "expressionDurationMs": 100,
        "durationMs": 100,
        "motion": None,
    }
    assert service._enqueue_sequence(plan)
    assert service.set_behavior_animation_expected(
        "ready-behavior", False, session_id="ready-session"
    )
    assert service.set_behavior_audio_expected(
        "ready-behavior", 0, session_id="ready-session"
    )
    staged = []
    service.trigger_emotion = types.MethodType(
        lambda self, emotion, **payload: staged.append((emotion, payload)) or True,
        service,
    )

    # A late client ACK must not cancel an already accepted server-side
    # behavior. The expression is still tracked as best-effort telemetry.
    assert service._wait_for_behavior_commit(plan) is True
    assert staged[0][1]["startAtServerMs"] == plan["startAtEpochMs"]
    assert service._behavior_audio_waiters["ready-behavior"]["visualStarted"] is True
    assert service._behavior_audio_waiters["ready-behavior"]["readinessDegraded"] is True

    service._behavior_audio_waiters["ready-behavior"]["sequenceEnqueued"] = False
    service.abort_behavior("ready-behavior")


def test_online_child_relay_bypasses_unreachable_runtime_prepare():
    service = _service()
    assert service.reserve_behavior(
        behavior_id="relay-behavior",
        request_id="relay-request",
        session_id="relay-session",
    )["accepted"]
    plan = {
        "id": "relay-behavior",
        "protocolVersion": "1",
        "requestId": "relay-request",
        "sessionId": "relay-session",
        "emotion": "happy.gif",
        "expressionDurationMs": 100,
        "durationMs": 100,
        "motion": "wave",
        "motionOffsetMs": 0,
    }
    assert service._enqueue_sequence(plan)
    assert service.set_behavior_animation_expected(
        "relay-behavior", False, session_id="relay-session"
    )
    assert service.set_behavior_audio_expected(
        "relay-behavior", 0, session_id="relay-session"
    )
    service._behavior_audio_waiters["relay-behavior"]["readyModalities"].add(
        "expression"
    )
    service.trigger_emotion = types.MethodType(
        lambda self, emotion, **payload: True,
        service,
    )
    service._child_agent_online = lambda: True
    service._prepare_runtime_motion = types.MethodType(
        lambda self, prepared_plan: (_ for _ in ()).throw(
            AssertionError("LAN Runtime prepare must be bypassed")
        ),
        service,
    )

    assert service._wait_for_behavior_commit(plan) is True
    assert plan["motionViaChildRelay"] is True
    status = service.get_command_status("relay-behavior")
    assert status["components"]["motion"]["status"] == "relay_ready"

    service._behavior_audio_waiters["relay-behavior"]["sequenceEnqueued"] = False
    service.abort_behavior("relay-behavior")


def test_runtime_commit_failure_falls_back_without_aborting_other_modalities():
    service = _service()
    waiter = service._new_behavior_waiter(
        "fallback-behavior",
        request_id="fallback-request",
        session_id="fallback-session",
    )
    waiter["sequenceEnqueued"] = True
    waiter["runtimeMotionPrepared"] = True
    waiter["motionExpected"] = True
    service._behavior_audio_waiters["fallback-behavior"] = waiter
    service._record_command({
        "id": "fallback-behavior",
        "requestId": "fallback-request",
        "sessionId": "fallback-session",
        "motion": "wave",
        "emotion": None,
        "durationMs": 0,
    })
    relayed = []
    service._commit_runtime_motion = types.MethodType(
        lambda self, prepared_plan: False,
        service,
    )
    service.play_motion = types.MethodType(
        lambda self, motion, on_complete=None: relayed.append(motion) or True,
        service,
    )
    service._stop_idle_motion_if_needed = types.MethodType(lambda self: None, service)
    service._behavior_cancelled = types.MethodType(lambda self, behavior_id: False, service)
    plan = {
        "id": "fallback-behavior",
        "runtimeMotionPrepared": True,
        "startAtMonotonic": time.monotonic(),
        "startAtEpochMs": int(time.time() * 1000),
        "emotion": None,
        "expressionDispatched": False,
        "expressionDurationMs": 0,
        "durationMs": 0,
        "motion": "wave",
        "motionOffsetMs": 0,
        "motionEndMs": 0,
        "audioOffsetMs": 0,
    }

    service._run_sequence(plan)

    assert relayed == ["wave"]
    assert waiter["aborted"] is False
