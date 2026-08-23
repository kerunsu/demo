import json
import queue
import threading
import time
import types

import app.robot.robot_service as robot_service_mod
from app.robot.mapping_resolver import MappingResolver
from app.robot.robot_service import RobotService


def _write_map(path):
    path.write_text(
        json.dumps(
            {
                "defaults": {
                    "idle": "空动作",
                    "praise": {
                        "motions": ["03-表扬"],
                        "emotion": "v2_happy.gif",
                        "sequence": {"audio": {"offsetMs": 320}},
                    },
                },
                "courses": {},
                "students": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_mapping_save_is_valid_and_leaves_no_temporary_file(tmp_path):
    map_file = tmp_path / "course_map.json"
    _write_map(map_file)
    resolver = MappingResolver(str(map_file))

    resolver.update_default_motions(
        "question",
        ["02-提问"],
        "v2_curious.gif",
        {"motionOffsetMs": 120, "audio": {"offsetMs": 450}},
    )

    saved = json.loads(map_file.read_text(encoding="utf-8"))
    assert saved["defaults"]["question"]["motions"] == ["02-提问"]
    assert saved["defaults"]["question"]["sequence"]["audio"]["offsetMs"] == 450
    assert list(tmp_path.glob(".course_map.*.tmp")) == []


def test_full_mapping_returns_snapshot_not_live_internal_state(tmp_path):
    map_file = tmp_path / "course_map.json"
    _write_map(map_file)
    resolver = MappingResolver(str(map_file))

    snapshot = resolver.get_full_mapping()
    snapshot["defaults"]["praise"]["motions"].append("不应写回")

    resolved = resolver.find_mapping(None, 1, None, "praise")
    assert resolved["motions"] == ["03-表扬"]
    assert resolved["sequence"]["audio"]["offsetMs"] == 320


def test_behavior_during_active_event_is_rejected_not_queued():
    service = object.__new__(RobotService)
    service._sequence_queue = queue.Queue(maxsize=1)
    service._idle_state_lock = threading.RLock()
    service._idle_generation = 0
    service._idle_timer = None
    service._active_sequence_deadline = 0.0
    service._behavior_busy = False
    service._busy_event_id = None

    first = {"id": "first", "durationMs": 4000}
    second = {"id": "second", "durationMs": 3000}
    assert service._enqueue_sequence(first) is True
    try:
        assert service._enqueue_sequence(second) is False

        assert first["scheduledDelayMs"] == robot_service_mod.BEHAVIOR_START_LEAD_MS
        assert first["startAtEpochMs"] >= int(time.time() * 1000)
        assert service._sequence_queue.qsize() == 1
        state = service.get_behavior_busy_state()
        assert state["busy"] is True
        assert state["eventId"] == "first"
        expected_ms = 4000 + robot_service_mod.BEHAVIOR_START_LEAD_MS
        assert expected_ms - 100 <= state["remainingMs"] <= expected_ms + 100
    finally:
        service._process_behavior_lock.release()


def test_high_priority_feedback_keeps_shared_anchor_with_shorter_lead():
    service = object.__new__(RobotService)
    service._sequence_queue = queue.Queue(maxsize=1)
    service._idle_state_lock = threading.RLock()
    service._idle_generation = 0
    service._idle_timer = None
    service._active_sequence_deadline = 0.0
    service._behavior_busy = False
    service._busy_event_id = None

    plan = {
        "id": "fast-praise",
        "durationMs": 2000,
        "startLeadMs": robot_service_mod.BEHAVIOR_FEEDBACK_START_LEAD_MS,
    }
    assert service._enqueue_sequence(plan) is True
    try:
        assert plan["scheduledDelayMs"] == robot_service_mod.BEHAVIOR_FEEDBACK_START_LEAD_MS
    finally:
        service._process_behavior_lock.release()


def test_formal_behavior_does_not_send_separate_idle_stop_over_lan():
    service = object.__new__(RobotService)
    service._idle_state_lock = threading.RLock()
    service._idle_timer = None
    service._idle_motion_active = True
    service._idle_motion_request_id = "idle-123"
    service._control_mode = "robot_runtime"
    requests = []
    service._runtime_osc_post = lambda path, payload: requests.append(
        (path, dict(payload))
    ) or True

    service._stop_idle_motion_if_needed()

    assert requests == []
    assert service._idle_motion_active is False
    assert service._idle_motion_request_id is None


def _coordination_service():
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
    return service


def test_behavior_is_atomically_reserved_before_sequence_building():
    service = _coordination_service()

    first = service.reserve_behavior(
        behavior_id="behavior-a",
        request_id="request-a",
    )
    second = service.reserve_behavior(
        behavior_id="behavior-b",
        request_id="request-b",
    )

    assert first["accepted"] is True
    assert first["behaviorId"] == "behavior-a"
    assert second["accepted"] is False
    assert second["reason"] == "behavior_busy"
    assert second["activeBehaviorId"] == "behavior-a"
    assert service.abort_behavior("behavior-a") is True


def test_reserved_behavior_waits_for_correlated_audio_terminal():
    service = _coordination_service()
    assert service.reserve_behavior(
        behavior_id="behavior-audio",
        request_id="request-audio",
        session_id="session-audio",
    )["accepted"]
    assert service._enqueue_sequence({
        "id": "behavior-audio",
        "requestId": "request-audio",
        "sessionId": "session-audio",
        "durationMs": 1000,
    })
    assert service.set_behavior_audio_expected(
        "behavior-audio",
        1,
        session_id="session-audio",
    )

    waiter = service._behavior_audio_waiters["behavior-audio"]
    assert waiter["audioDone"].is_set() is False
    resolved = service.mark_behavior_audio_complete(
        behavior_id="behavior-audio",
        request_id="request-audio",
        session_id="session-audio",
        modality="speech",
        status="ended",
        completion_key="file:praise:one.mp3",
    )
    assert resolved == "behavior-audio"
    assert waiter["audioDone"].is_set() is True
    # Worker owns final release after expression/motion also complete.
    assert service.get_behavior_busy_state()["busy"] is True


def test_aborting_unstarted_reservation_releases_immediately():
    service = _coordination_service()
    assert service.reserve_behavior(behavior_id="behavior-abort")["accepted"]
    assert service.abort_behavior("behavior-abort") is True
    assert service.get_behavior_busy_state()["busy"] is False


def test_worker_keeps_busy_until_real_audio_terminal():
    service = _coordination_service()
    service._run_sequence = types.MethodType(
        lambda self, plan: time.sleep(0.02),
        service,
    )
    service._schedule_idle_pose_if_quiet = types.MethodType(
        lambda self: None,
        service,
    )
    service._emit_behavior_completed = types.MethodType(
        lambda self, payload: None,
        service,
    )
    threading.Thread(
        target=service._sequence_loop,
        daemon=True,
    ).start()

    assert service.reserve_behavior(
        behavior_id="behavior-worker",
        session_id="session-worker",
    )["accepted"]
    assert service._enqueue_sequence({
        "id": "behavior-worker",
        "sessionId": "session-worker",
        "durationMs": 20,
    })
    assert service.set_behavior_audio_expected(
        "behavior-worker",
        1,
        session_id="session-worker",
        timeout_ms=1000,
    )
    time.sleep(0.06)
    assert service.get_behavior_busy_state()["busy"] is True

    service.mark_behavior_audio_complete(
        session_id="session-worker",
        completion_key="browser:praise:ok",
    )
    service._sequence_queue.join()
    assert service.get_behavior_busy_state()["busy"] is False


def test_processing_reservation_is_not_reclaimed_by_wall_clock():
    service = _coordination_service()
    assert service.reserve_behavior(
        behavior_id="behavior-slow-handler",
        request_id="request-slow-handler",
    )["accepted"]
    service._behavior_audio_waiters[
        "behavior-slow-handler"
    ]["reservationDeadline"] = time.monotonic() - 1

    state = service.get_behavior_busy_state()
    competing = service.reserve_behavior(
        behavior_id="behavior-competing",
        request_id="request-competing",
    )

    assert state["busy"] is True
    assert state["eventId"] == "behavior-slow-handler"
    assert competing["accepted"] is False
    assert competing["activeBehaviorId"] == "behavior-slow-handler"


def test_uncorrelated_audio_terminal_cannot_release_current_behavior():
    service = _coordination_service()
    assert service.reserve_behavior(
        behavior_id="behavior-current",
        session_id="session-current",
    )["accepted"]
    assert service._enqueue_sequence({
        "id": "behavior-current",
        "sessionId": "session-current",
        "durationMs": 100,
    })
    assert service.set_behavior_audio_expected(
        "behavior-current",
        1,
        session_id="session-current",
    )

    assert service.mark_behavior_audio_complete(
        session_id="session-current",
        completion_key="legacy:late",
    ) is None
    waiter = service._behavior_audio_waiters["behavior-current"]
    assert waiter["completedAudioCount"] == 0
    assert waiter["audioDone"].is_set() is False


def test_abort_before_dispatch_commit_skips_visual_plan():
    service = _coordination_service()
    visual_runs = []
    service._run_sequence = types.MethodType(
        lambda self, plan: visual_runs.append(plan["id"]),
        service,
    )
    service._schedule_idle_pose_if_quiet = types.MethodType(
        lambda self: None,
        service,
    )
    service._emit_behavior_completed = types.MethodType(
        lambda self, payload: None,
        service,
    )
    threading.Thread(
        target=service._sequence_loop,
        daemon=True,
    ).start()

    assert service.reserve_behavior(
        behavior_id="behavior-dispatch-failed",
    )["accepted"]
    assert service._enqueue_sequence({
        "id": "behavior-dispatch-failed",
        "durationMs": 100,
    })
    assert service.abort_behavior("behavior-dispatch-failed")
    service._sequence_queue.join()

    assert visual_runs == []
    assert service.get_behavior_busy_state()["busy"] is False


def test_dispatch_decision_timeout_aborts_without_visual(monkeypatch):
    service = _coordination_service()
    visual_runs = []
    service._run_sequence = types.MethodType(
        lambda self, plan: visual_runs.append(plan["id"]),
        service,
    )
    service._schedule_idle_pose_if_quiet = types.MethodType(
        lambda self: None,
        service,
    )
    service._emit_behavior_completed = types.MethodType(
        lambda self, payload: None,
        service,
    )
    monkeypatch.setattr(
        robot_service_mod,
        "BEHAVIOR_AUDIO_DECISION_TIMEOUT_MS",
        20,
    )
    threading.Thread(
        target=service._sequence_loop,
        daemon=True,
    ).start()

    assert service.reserve_behavior(
        behavior_id="behavior-decision-timeout",
    )["accepted"]
    assert service._enqueue_sequence({
        "id": "behavior-decision-timeout",
        "durationMs": 100,
    })
    service._sequence_queue.join()

    assert visual_runs == []
    assert service.get_behavior_busy_state()["busy"] is False


def test_audio_only_behavior_uses_same_busy_lock_until_exact_terminal():
    service = _coordination_service()
    visual_runs = []
    service._run_sequence = types.MethodType(
        lambda self, plan: visual_runs.append(plan["id"]),
        service,
    )
    service._schedule_idle_pose_if_quiet = types.MethodType(
        lambda self: None,
        service,
    )
    service._emit_behavior_completed = types.MethodType(
        lambda self, payload: None,
        service,
    )
    threading.Thread(
        target=service._sequence_loop,
        daemon=True,
    ).start()

    reserved = service.reserve_audio_only_behavior(
        behavior_id="dialogue-behavior",
        request_id="dialogue-request",
        session_id="dialogue-session",
    )
    assert reserved["accepted"] is True
    assert service.set_behavior_audio_expected(
        "dialogue-behavior",
        1,
        session_id="dialogue-session",
        timeout_ms=1000,
    )
    assert service.reserve_behavior(
        behavior_id="formal-behavior",
    )["accepted"] is False

    assert service.mark_behavior_audio_complete(
        behavior_id="dialogue-behavior",
        request_id="dialogue-request",
        session_id="dialogue-session",
        modality="speech",
        status="ended",
        completion_key="browser:dialogue:done",
    ) == "dialogue-behavior"
    service._sequence_queue.join()

    assert visual_runs == []
    assert service.get_behavior_busy_state()["busy"] is False


def test_audio_only_behavior_timeout_releases_busy_lock():
    service = _coordination_service()
    service._schedule_idle_pose_if_quiet = types.MethodType(
        lambda self: None,
        service,
    )
    service._emit_behavior_completed = types.MethodType(
        lambda self, payload: None,
        service,
    )
    threading.Thread(
        target=service._sequence_loop,
        daemon=True,
    ).start()

    assert service.reserve_audio_only_behavior(
        behavior_id="dialogue-timeout",
        session_id="dialogue-timeout-session",
    )["accepted"]
    assert service.set_behavior_audio_expected(
        "dialogue-timeout",
        1,
        session_id="dialogue-timeout-session",
        timeout_ms=30,
    )
    service._sequence_queue.join()

    assert service.get_behavior_busy_state()["busy"] is False


def test_child_animation_is_part_of_atomic_behavior_barrier():
    service = _coordination_service()
    completed = []
    service._run_sequence = types.MethodType(
        lambda self, plan: time.sleep(0.01),
        service,
    )
    service._schedule_idle_pose_if_quiet = types.MethodType(
        lambda self: None,
        service,
    )
    service._emit_behavior_completed = types.MethodType(
        lambda self, payload: completed.append(payload),
        service,
    )
    threading.Thread(target=service._sequence_loop, daemon=True).start()

    assert service.reserve_behavior(
        behavior_id="behavior-animation",
        request_id="request-animation",
        session_id="session-animation",
    )["accepted"]
    assert service._enqueue_sequence({
        "id": "behavior-animation",
        "requestId": "request-animation",
        "sessionId": "session-animation",
        "durationMs": 10,
    })
    assert service.set_behavior_animation_expected(
        "behavior-animation",
        True,
        session_id="session-animation",
        timeout_ms=1000,
    )
    assert service.set_behavior_audio_expected(
        "behavior-animation",
        0,
        session_id="session-animation",
    )
    assert service.mark_behavior_modality_ready(
        behavior_id="behavior-animation",
        request_id="request-animation",
        session_id="session-animation",
        modality="childAnimation",
    )["ready"] is True
    time.sleep(0.05)
    assert service.get_behavior_busy_state()["busy"] is True

    terminal = service.mark_behavior_animation_complete(
        behavior_id="behavior-animation",
        request_id="request-animation",
        session_id="session-animation",
        status="ended",
        modality="childAnimation",
    )
    assert terminal == {
        "behaviorId": "behavior-animation",
        "status": "ended",
        "degraded": False,
        "idempotentReplay": False,
    }
    service._sequence_queue.join()
    assert service.get_behavior_busy_state()["busy"] is False
    assert completed[-1]["animationStatus"] == "ended"
    assert completed[-1]["degraded"] is False


def test_animation_terminal_requires_exact_behavior_request_and_session():
    service = _coordination_service()
    assert service.reserve_behavior(
        behavior_id="behavior-exact",
        request_id="request-exact",
        session_id="session-exact",
    )["accepted"]
    assert service.set_behavior_animation_expected(
        "behavior-exact",
        True,
        session_id="session-exact",
    )

    assert service.mark_behavior_animation_complete(
        behavior_id="behavior-exact",
        request_id="wrong-request",
        session_id="session-exact",
        status="ended",
        modality="childAnimation",
    ) is None
    assert service.mark_behavior_animation_complete(
        behavior_id="behavior-exact",
        request_id="request-exact",
        session_id="wrong-session",
        status="ended",
        modality="childAnimation",
    ) is None
    waiter = service._behavior_audio_waiters["behavior-exact"]
    assert waiter["animationDone"].is_set() is False
    service.abort_behavior("behavior-exact")
