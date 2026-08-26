import threading
import time


def _long_frames():
    return [
        {"time": 0, "pose": {"pitch": 200}, "moveMs": 600},
        {"time": 5000, "pose": {"pitch": 200}, "moveMs": 600},
    ]


def test_idle_return_has_a_short_interruptible_default_buffer():
    from app.robot.config import IDLE_POSE_DELAY

    assert 0.4 <= IDLE_POSE_DELAY <= 1.0


def test_runtime_motion_replacement_does_not_wait_for_idle_worker(monkeypatch):
    from robot_runtime import osc_bridge

    monkeypatch.setattr(osc_bridge, "send_pose", lambda *_args, **_kwargs: None)
    state = osc_bridge.PlaybackState()
    state.start("idle-transition", _long_frames())
    time.sleep(0.02)

    started = time.perf_counter()
    state.start("teacher-action", _long_frames())
    elapsed = time.perf_counter() - started

    assert elapsed < 0.1
    assert state.current_request_id == "teacher-action"
    assert state.stop(expected_request_id="teacher-action") is True


def test_server_osc_motion_replacement_is_non_blocking(monkeypatch):
    from app.robot import motion_player as player_module

    monkeypatch.setattr(player_module, "get_scaled_motion_frames", lambda _name: _long_frames())
    player = object.__new__(player_module.MotionPlayer)
    player._osc_client = object()
    player._osc_ip = "127.0.0.1"
    player._osc_port = 12000
    player._is_playing = False
    player._stop_event = threading.Event()
    player._playback_thread = None
    player._lock = threading.Lock()
    player.send_frame = lambda *_args, **_kwargs: None

    assert player.play("空动作") is True
    time.sleep(0.02)
    started = time.perf_counter()
    assert player.play("教师动作") is True
    elapsed = time.perf_counter() - started

    assert elapsed < 0.1
    assert player.is_playing is True
    player.stop()
