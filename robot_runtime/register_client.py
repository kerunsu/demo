"""Backend registration / heartbeat client (runs inside Robot Runtime)."""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import requests

BACKEND_URL = os.environ.get("ROBOT_RUNTIME_BACKEND_URL", "").rstrip("/")
RUNTIME_KEY = (
    os.environ.get("ROBOT_RUNTIME_KEY")
    or os.environ.get("CHILD_MEDIA_AGENT_KEY")
    or os.environ.get("ROBOT_AGENT_KEY")
    or ""
)
ADVERTISE_HOST = os.environ.get("ROBOT_RUNTIME_ADVERTISE_HOST", "").strip()
REGISTER_INTERVAL = float(os.environ.get("ROBOT_RUNTIME_REGISTER_INTERVAL", 10))

_CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EIArt" / "robot_runtime"
_CONFIG_PATH = _CONFIG_DIR / "config.json"

_state_lock = threading.Lock()
_backend_registered = False
_advertised_url: Optional[str] = None
_backend_public_url: Optional[str] = None
_last_register_error: Optional[str] = None
_last_register_at: Optional[float] = None
_protocol_compatible: Optional[bool] = None
_protocol_compatibility_reason: Optional[str] = None
_stop = threading.Event()
_thread: Optional[threading.Thread] = None
_listen_port = 19091
_instance_id = ""
_boot_id = uuid.uuid4().hex


def _runtime_build_version() -> str:
    candidates = [Path(__file__).resolve().parent / "VERSION"]
    if bool(getattr(sys, "frozen", False)):
        executable_dir = Path(sys.executable).resolve().parent
        candidates = [
            Path(getattr(sys, "_MEIPASS", executable_dir)) / "robot_runtime" / "VERSION",
            Path(getattr(sys, "_MEIPASS", executable_dir)) / "VERSION",
            executable_dir / "VERSION",
            *candidates,
        ]
    for candidate in candidates:
        try:
            value = candidate.read_text(encoding="utf-8").strip()
            if value:
                return value
        except OSError:
            continue
    return "unknown"


def _guess_lan_ip() -> str:
    if ADVERTISE_HOST:
        return ADVERTISE_HOST
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def load_persisted_config() -> Dict[str, Any]:
    """Load last UI/env-saved config. Does not override non-empty env BACKEND_URL."""
    global BACKEND_URL, RUNTIME_KEY, ADVERTISE_HOST, _instance_id
    if not _CONFIG_PATH.is_file():
        _instance_id = f"runtime-{uuid.uuid4().hex}"
        save_persisted_config(instance_id=_instance_id)
        return {}
    try:
        data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        _instance_id = f"runtime-{uuid.uuid4().hex}"
        save_persisted_config(instance_id=_instance_id)
        return {}
    _instance_id = str(data.get("instanceId") or "").strip()
    if not _instance_id:
        _instance_id = f"runtime-{uuid.uuid4().hex}"
        save_persisted_config(instance_id=_instance_id)
    if not BACKEND_URL and data.get("backendUrl"):
        BACKEND_URL = str(data["backendUrl"]).rstrip("/")
    if not RUNTIME_KEY and data.get("runtimeKey"):
        RUNTIME_KEY = str(data["runtimeKey"])
    if not ADVERTISE_HOST and data.get("advertiseHost"):
        ADVERTISE_HOST = str(data["advertiseHost"]).strip()
    return data


def save_persisted_config(
    *,
    backend_url: Optional[str] = None,
    runtime_key: Optional[str] = None,
    advertise_host: Optional[str] = None,
    media_data_dir: Optional[str] = None,
    instance_id: Optional[str] = None,
) -> Path:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    existing: Dict[str, Any] = {}
    if _CONFIG_PATH.is_file():
        try:
            existing = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    if backend_url is not None:
        existing["backendUrl"] = backend_url.rstrip("/")
    if runtime_key is not None:
        existing["runtimeKey"] = runtime_key
    if advertise_host is not None:
        existing["advertiseHost"] = advertise_host.strip()
    if media_data_dir is not None:
        existing["mediaDataDir"] = str(media_data_dir)
    if instance_id is not None:
        existing["instanceId"] = str(instance_id)
    existing["updatedAt"] = int(time.time())
    _CONFIG_PATH.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return _CONFIG_PATH


def config_dir() -> Path:
    return _CONFIG_DIR


def config_path() -> Path:
    return _CONFIG_PATH


def set_listen_port(port: int) -> None:
    global _listen_port
    _listen_port = port


def set_backend_url(url: Optional[str], *, persist: bool = False) -> None:
    global BACKEND_URL
    if url:
        BACKEND_URL = url.rstrip("/")
        if persist:
            save_persisted_config(backend_url=BACKEND_URL)


def set_runtime_key(key: Optional[str], *, persist: bool = False) -> None:
    global RUNTIME_KEY
    if key is not None:
        RUNTIME_KEY = key
        if persist:
            save_persisted_config(runtime_key=RUNTIME_KEY)


def get_registry_status() -> Dict[str, Any]:
    with _state_lock:
        return {
            "backendRegistered": _backend_registered,
            "advertisedUrl": _advertised_url,
            "backendUrl": BACKEND_URL or None,
            "backendPublicUrl": _backend_public_url,
            "lastRegisterError": _last_register_error,
            "lastRegisterAt": _last_register_at,
            "protocolVersion": "1",
            "protocolCompatible": _protocol_compatible,
            "protocolCompatibilityReason": _protocol_compatibility_reason,
            "instanceId": _instance_id or None,
            "bootId": _boot_id,
            "keyConfigured": bool(RUNTIME_KEY),
            "configPath": str(_CONFIG_PATH),
        }


def _headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if RUNTIME_KEY:
        headers["X-Robot-Runtime-Key"] = RUNTIME_KEY
        headers["X-Child-Media-Agent-Key"] = RUNTIME_KEY
    return headers


def register_once(extra: Optional[Dict[str, Any]] = None) -> bool:
    global _backend_registered, _advertised_url, _backend_public_url
    global _last_register_error, _last_register_at
    global _protocol_compatible, _protocol_compatibility_reason

    if not BACKEND_URL:
        with _state_lock:
            _backend_registered = False
            _last_register_error = "ROBOT_RUNTIME_BACKEND_URL not set"
        return False

    advertised = f"http://{_guess_lan_ip()}:{_listen_port}"
    payload = {
        "advertisedUrl": advertised,
        "port": _listen_port,
        "buildVersion": _runtime_build_version(),
        "instanceId": _instance_id or None,
        "bootId": _boot_id,
        "protocolVersion": "1",
        "capabilities": [
            "media",
            "osc",
            "device-preflight-v1",
            "multi-track-media-v1",
            "behavior-sync-v1",
        ],
        "ts": int(time.time() * 1000),
    }
    if extra:
        payload.update(extra)

    try:
        resp = requests.post(
            f"{BACKEND_URL}/api/robot/runtime/register",
            json=payload,
            headers=_headers(),
            timeout=5,
        )
        body = resp.json() if resp.content else {}
        ok = resp.status_code == 200 and body.get("ok", body.get("success", False))
        with _state_lock:
            _last_register_at = time.time()
            if ok:
                _backend_registered = True
                _advertised_url = advertised
                _backend_public_url = body.get("backendPublicUrl") or BACKEND_URL
                _last_register_error = None
                matrix = body.get("versionMatrix") or {}
                runtime_version = matrix.get("runtime") or {}
                _protocol_compatible = runtime_version.get("compatible")
                _protocol_compatibility_reason = runtime_version.get("compatibilityReason")
            else:
                _backend_registered = False
                _last_register_error = f"HTTP {resp.status_code}: {str(body)[:200]}"
                _protocol_compatible = None
                _protocol_compatibility_reason = None
        return bool(ok)
    except Exception as exc:
        with _state_lock:
            _backend_registered = False
            _last_register_error = str(exc)
            _last_register_at = time.time()
            _protocol_compatible = None
            _protocol_compatibility_reason = None
        return False


def heartbeat_once() -> bool:
    if not BACKEND_URL:
        return False
    try:
        resp = requests.post(
            f"{BACKEND_URL}/api/robot/runtime/heartbeat",
            json={"advertisedUrl": _advertised_url, "ts": int(time.time() * 1000)},
            headers=_headers(),
            timeout=5,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _loop() -> None:
    while not _stop.is_set():
        register_once()
        heartbeat_once()
        _stop.wait(REGISTER_INTERVAL)


def start_background(port: int) -> None:
    global _thread
    set_listen_port(port)
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="RobotRuntime-Register")
    _thread.start()


def stop_background() -> None:
    _stop.set()
