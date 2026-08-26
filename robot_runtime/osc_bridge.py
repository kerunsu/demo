"""OSC playback bridge for DollSer (merged from doll/robot_agent.py)."""
from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from pythonosc import udp_client

DOLLSER_OSC_IP = os.environ.get("DOLLSER_OSC_IP", "127.0.0.1")
DOLLSER_OSC_PORT = int(os.environ.get("DOLLSER_OSC_PORT", 12000))
DEFAULT_MOVE_MS = int(os.environ.get("ROBOT_AGENT_DEFAULT_MOVE_MS", 100))
EMPTY_ACTION_FALLBACK = {"pitch": 200, "yaw": 160, "armL": 320, "armR": 50}

_osc_client = udp_client.SimpleUDPClient(DOLLSER_OSC_IP, DOLLSER_OSC_PORT)
_last_osc_error: Optional[str] = None


class PlaybackState:
    def __init__(self) -> None:
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._transition_lock = threading.Lock()
        self.current_request_id: Optional[str] = None

    def _stop_transition(self, expected_request_id: Optional[str] = None) -> bool:
        with self._lock:
            if (
                expected_request_id is not None
                and self.current_request_id != expected_request_id
            ):
                return False
            self._stop_event.set()
            t = self._thread
            if self._thread is t:
                self._thread = None
                self.current_request_id = None
                self._stop_event = threading.Event()
        # Do not join here.  Starting a formal action must pre-empt an idle
        # transition immediately; the old worker owns its stop event and will
        # exit without being able to clear the new worker's state.
        return True

    def stop(self, expected_request_id: Optional[str] = None) -> bool:
        """Stop all playback or only the exact request currently active."""
        with self._transition_lock:
            return self._stop_transition(expected_request_id)

    def start(
        self,
        request_id: str,
        frames: List[Dict[str, Any]],
        *,
        start_at_epoch_ms: Optional[int] = None,
        on_event: Optional[Callable[[str, Optional[str]], None]] = None,
        neutral_pose: Optional[Dict[str, Any]] = None,
    ) -> None:
        with self._transition_lock:
            self._stop_transition()
            stop_event = threading.Event()

            def _run() -> None:
                global _last_osc_error
                terminal_status = "ended"
                terminal_reason: Optional[str] = None
                try:
                    if start_at_epoch_ms:
                        remaining = (int(start_at_epoch_ms) - int(time.time() * 1000)) / 1000.0
                        if remaining > 0 and stop_event.wait(remaining):
                            terminal_status = "stopped"
                            terminal_reason = "cancelled_before_anchor"
                            return
                    if on_event:
                        on_event("started", None)
                    start = time.time() * 1000
                    for frame in frames:
                        if stop_event.is_set():
                            terminal_status = "stopped"
                            terminal_reason = "cancelled"
                            return
                        frame_time = int(max(0, frame.get("time", 0)))
                        now = int(time.time() * 1000 - start)
                        if frame_time > now and stop_event.wait((frame_time - now) / 1000.0):
                            terminal_status = "stopped"
                            terminal_reason = "cancelled"
                            return
                        if stop_event.is_set():
                            terminal_status = "stopped"
                            terminal_reason = "cancelled"
                            return
                        send_pose(
                            frame.get("pose", {}),
                            int(frame.get("moveMs", DEFAULT_MOVE_MS)),
                            neutral_pose=neutral_pose,
                        )
                except Exception as exc:
                    _last_osc_error = str(exc)
                    terminal_status = "failed"
                    terminal_reason = str(exc)
                finally:
                    with self._lock:
                        if self._thread is thread:
                            self.current_request_id = None
                            self._thread = None
                    if on_event:
                        on_event(terminal_status, terminal_reason)

            thread = threading.Thread(
                target=_run, daemon=True, name=f"RobotRuntime-OSC-{request_id}"
            )
            with self._lock:
                self._stop_event = stop_event
                self.current_request_id = request_id
                self._thread = thread
            thread.start()


playback_state = PlaybackState()


def normalize_pose(
    pose: Dict[str, Any], neutral_pose: Optional[Dict[str, Any]] = None
) -> Dict[str, int]:
    if not isinstance(pose, dict):
        pose = {}
    neutral = dict(EMPTY_ACTION_FALLBACK)
    if isinstance(neutral_pose, dict):
        for axis in neutral:
            try:
                neutral[axis] = int(neutral_pose.get(axis, neutral[axis]))
            except (TypeError, ValueError):
                pass
    return {
        axis: int(pose.get(axis, neutral[axis])) for axis in neutral
    }


def send_pose(
    pose: Dict[str, Any], move_ms: int, *, neutral_pose: Optional[Dict[str, Any]] = None
) -> None:
    global _last_osc_error
    try:
        safe = normalize_pose(pose, neutral_pose)
        move_ms = int(max(0, move_ms))
        _osc_client.send_message("/pitch", [safe["pitch"], move_ms])
        _osc_client.send_message("/yaw", [safe["yaw"], move_ms])
        _osc_client.send_message("/arml", [safe["armL"], move_ms])
        _osc_client.send_message("/armr", [safe["armR"], move_ms])
        _last_osc_error = None
    except Exception as exc:
        _last_osc_error = str(exc)
        raise


def osc_status() -> Dict[str, Any]:
    return {
        "oscTarget": f"{DOLLSER_OSC_IP}:{DOLLSER_OSC_PORT}",
        "dollSerConfigured": True,
        "playing": playback_state.current_request_id is not None,
        "currentRequestId": playback_state.current_request_id,
        "lastOscError": _last_osc_error,
    }
