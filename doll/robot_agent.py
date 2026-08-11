"""
[DEPRECATED] 旧 Robot Agent（仅 OSC）。

跨机课堂请改用统一 Robot Runtime（媒体 + OSC）：
  set ROBOT_RUNTIME_BACKEND_URL=http://<后端IP>:8080
  python -m robot_runtime.agent

本文件保留 OSC-only 行为以便紧急回退；默认端口仍为 19090。
新部署请使用 19091 的 robot_runtime。
"""
import os
import sys
import threading
import time
from typing import Any, Dict, List

from flask import Flask, jsonify, request
from flask_cors import CORS
from pythonosc import udp_client

print(
    "[DEPRECATED] doll/robot_agent.py — prefer: python -m robot_runtime.agent",
    file=sys.stderr,
)

AGENT_HOST = os.environ.get("ROBOT_AGENT_HOST", "127.0.0.1")
AGENT_PORT = int(os.environ.get("ROBOT_AGENT_PORT", 19090))

DOLLSER_OSC_IP = os.environ.get("DOLLSER_OSC_IP", "127.0.0.1")
DOLLSER_OSC_PORT = int(os.environ.get("DOLLSER_OSC_PORT", 12000))
DEFAULT_MOVE_MS = int(os.environ.get("ROBOT_AGENT_DEFAULT_MOVE_MS", 100))

AGENT_KEY = os.environ.get("ROBOT_AGENT_KEY", "")

app = Flask(__name__)
CORS(
    app,
    resources={r"/*": {"origins": "*"}},
    allow_headers=["Content-Type", "X-Robot-Agent-Key", "X-Robot-Runtime-Key"],
    methods=["GET", "POST", "OPTIONS"],
)
osc_client = udp_client.SimpleUDPClient(DOLLSER_OSC_IP, DOLLSER_OSC_PORT)


class PlaybackState:
    def __init__(self):
        self._thread: threading.Thread = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self.current_request_id = None

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            t = self._thread
        if t and t.is_alive():
            t.join(timeout=0.5)
        with self._lock:
            self._thread = None
            self.current_request_id = None
            self._stop_event = threading.Event()

    def start(self, request_id: str, frames: List[Dict[str, Any]]) -> None:
        self.stop()

        def _run():
            start = time.time() * 1000
            for frame in frames:
                if self._stop_event.is_set():
                    return
                frame_time = int(max(0, frame.get("time", 0)))
                now = int(time.time() * 1000 - start)
                if frame_time > now:
                    time.sleep((frame_time - now) / 1000.0)
                if self._stop_event.is_set():
                    return
                send_pose(
                    frame.get("pose", {}),
                    int(frame.get("moveMs", DEFAULT_MOVE_MS)),
                )
            with self._lock:
                self.current_request_id = None

        thread = threading.Thread(
            target=_run,
            daemon=True,
            name=f"RobotAgent-{request_id}",
        )
        with self._lock:
            self.current_request_id = request_id
            self._thread = thread
        thread.start()


playback_state = PlaybackState()


def check_agent_key() -> bool:
    if not AGENT_KEY:
        return True
    provided = (
        request.headers.get("X-Robot-Agent-Key")
        or request.headers.get("X-Robot-Runtime-Key")
        or ""
    )
    return provided == AGENT_KEY


def normalize_pose(pose: Dict[str, Any]) -> Dict[str, int]:
    if not isinstance(pose, dict):
        pose = {}
    return {
        "pitch": int(pose.get("pitch", 180)),
        "yaw": int(pose.get("yaw", 180)),
        "armL": int(pose.get("armL", 90)),
        "armR": int(pose.get("armR", 90)),
    }


def send_pose(pose: Dict[str, Any], move_ms: int) -> None:
    safe = normalize_pose(pose)
    move_ms = int(max(0, move_ms))
    osc_client.send_message("/pitch", [safe["pitch"], move_ms])
    osc_client.send_message("/yaw", [safe["yaw"], move_ms])
    osc_client.send_message("/arml", [safe["armL"], move_ms])
    osc_client.send_message("/armr", [safe["armR"], move_ms])


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "deprecated": True,
        "prefer": "python -m robot_runtime.agent",
        "oscTarget": f"{DOLLSER_OSC_IP}:{DOLLSER_OSC_PORT}",
        "agentHost": AGENT_HOST,
        "agentPort": AGENT_PORT,
        "playing": playback_state.current_request_id is not None,
    })


@app.post("/osc/frame")
def osc_frame():
    if not check_agent_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    pose = data.get("pose", {})
    move_ms = int(data.get("moveMs", DEFAULT_MOVE_MS))
    send_pose(pose, move_ms)
    app.logger.info("[RobotAgent] frame requestId=%s moveMs=%s", data.get("requestId"), move_ms)
    return jsonify({"ok": True, "requestId": data.get("requestId")})


@app.post("/osc/play")
def osc_play():
    if not check_agent_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    frames = data.get("frames", [])
    if not isinstance(frames, list) or not frames:
        return jsonify({"ok": False, "error": "frames required"}), 400

    request_id = str(data.get("requestId") or int(time.time() * 1000))
    playback_state.start(request_id, frames)
    app.logger.info("[RobotAgent] play requestId=%s frames=%s", request_id, len(frames))
    return jsonify({
        "ok": True,
        "requestId": request_id,
        "accepted": True,
        "frameCount": len(frames),
    })


@app.post("/osc/stop")
def osc_stop():
    if not check_agent_key():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    data = request.get_json(silent=True) or {}
    playback_state.stop()
    app.logger.info("[RobotAgent] stop requestId=%s", data.get("requestId"))
    return jsonify({"ok": True, "requestId": data.get("requestId")})


if __name__ == "__main__":
    print(f"[RobotAgent DEPRECATED] listen on http://{AGENT_HOST}:{AGENT_PORT}")
    print(f"[RobotAgent] OSC target {DOLLSER_OSC_IP}:{DOLLSER_OSC_PORT}")
    print("[RobotAgent] Prefer: python -m robot_runtime.agent")
    app.run(host=AGENT_HOST, port=AGENT_PORT, debug=False)
