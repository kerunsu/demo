from __future__ import annotations

import threading
from collections import deque


def test_stopped_uplink_thread_cannot_consume_next_session_queue(monkeypatch):
    from robot_runtime.agent import MediaRecorderState

    state = MediaRecorderState()
    old_queue = deque([("video", {"seq": 1})], maxlen=10)
    new_queue = deque([("video", {"seq": 2})], maxlen=10)
    old_stop = threading.Event()
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def fake_send(kind, payload, **kwargs):
        calls.append((kind, payload, kwargs["session_id"], kwargs["backend_base"]))
        entered.set()
        assert release.wait(timeout=2)
        return True

    monkeypatch.setattr(state, "_send_one", fake_send)
    thread = threading.Thread(
        target=state._uplink_loop,
        args=("old-session", "http://old-server", old_queue, old_stop),
    )
    thread.start()
    assert entered.wait(timeout=1)

    # Simulate stop followed immediately by the next course starting.
    old_stop.set()
    old_queue.clear()
    state.session_id = "new-session"
    state._uplink_q = new_queue
    release.set()
    thread.join(timeout=2)

    assert not thread.is_alive()
    assert list(new_queue) == [("video", {"seq": 2})]
    assert calls == [("video", {"seq": 1}, "old-session", "http://old-server")]


def test_late_session_gone_does_not_stop_current_course():
    from robot_runtime.agent import MediaRecorderState

    state = MediaRecorderState()
    state.session_id = "current-session"
    state.recording = True
    state._stop_event.clear()
    old_stop = threading.Event()
    old_queue = deque([("audio", {"seq": 1})])

    state._handle_session_gone(410, "old-session", old_stop, old_queue)

    assert old_stop.is_set()
    assert list(old_queue) == []
    assert state.recording is True
    assert not state._stop_event.is_set()
    assert state.last_error is None


def test_archive_confirmation_requires_every_checksum(monkeypatch):
    from robot_runtime import agent as runtime_agent

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "archive": {
                    "completed": True,
                    "checksums": {"video": "v1", "audio": "a1"},
                }
            }

    monkeypatch.setattr(runtime_agent.requests, "get", lambda *args, **kwargs: Response())
    state = runtime_agent.MediaRecorderState()

    assert state._confirm_archive_upload(
        "http://server", "session-1", {"video": "v1", "audio": "a1"}
    )
    assert not state._confirm_archive_upload(
        "http://server", "session-1", {"video": "different"}
    )

