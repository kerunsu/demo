"""随 Flask 一并启动本地 FunASR voice-service（8765）。"""

from __future__ import annotations

import atexit
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional, TextIO
from urllib.parse import urlparse

_voice_proc: Optional[subprocess.Popen] = None
_log_handle: Optional[TextIO] = None
_cleanup_registered = False
_we_started = False
_startup_thread: Optional[threading.Thread] = None
_startup_lock = threading.Lock()
_FUNASR_MODEL_ENV_KEYS = {
    "VOICE_SERVICE_FUNASR_MODEL",
    "VOICE_SERVICE_FUNASR_VAD_MODEL",
    "VOICE_SERVICE_FUNASR_PUNC_MODEL",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _workspace_root() -> Path:
    return _repo_root().parent


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "on")


def _dialogue_enabled() -> bool:
    return _env_flag("DIALOGUE_ENABLED", True)


def should_start_voice_service() -> bool:
    """对话开启时默认拉起；可用 START_VOICE_SERVICE=0 关闭。"""
    if not _dialogue_enabled():
        return False
    if not _env_flag("START_VOICE_SERVICE", True):
        return False
    # Werkzeug debug 热重载：只在父进程启动，避免双开
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        return False
    return True


def _service_host_port() -> tuple[str, int]:
    url = (os.environ.get("VOICE_PYTHON_SERVICE_URL") or "http://127.0.0.1:8765").strip()
    parsed = urlparse(url)
    host = parsed.hostname or os.environ.get("VOICE_SERVICE_HOST") or "127.0.0.1"
    port = parsed.port or int(os.environ.get("VOICE_SERVICE_PORT") or "8765")
    return host, int(port)


def _port_listening(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _default_expert_python() -> Optional[Path]:
    candidate = (
        _workspace_root()
        / "ExpertAnnotator_ASD-main"
        / "asd_llm_agent"
        / ".venv"
        / "Scripts"
        / "python.exe"
    )
    if candidate.is_file():
        return candidate
    # non-Windows layout
    candidate2 = (
        _workspace_root()
        / "ExpertAnnotator_ASD-main"
        / "asd_llm_agent"
        / ".venv"
        / "bin"
        / "python"
    )
    if candidate2.is_file():
        return candidate2
    return None


def resolve_voice_python() -> str:
    override = (os.environ.get("VOICE_SERVICE_PYTHON") or "").strip()
    if override:
        return override
    expert = _default_expert_python()
    if expert is not None:
        return str(expert)
    return sys.executable


def _modelscope_iic() -> Path:
    return Path.home() / ".cache" / "modelscope" / "hub" / "models" / "iic"


def _resolve_funasr_env() -> dict[str, str]:
    """Prefer local modelscope cache paths when present."""
    env: dict[str, str] = {}
    iic = _modelscope_iic()
    asr = iic / "speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
    vad = iic / "speech_fsmn_vad_zh-cn-16k-common-pytorch"
    punc = iic / "punc_ct-transformer_cn-en-common-vocab471067-large"

    if not (os.environ.get("VOICE_SERVICE_FUNASR_MODEL") or "").strip():
        env["VOICE_SERVICE_FUNASR_MODEL"] = str(asr) if asr.is_dir() else "paraformer-zh"
    if not (os.environ.get("VOICE_SERVICE_FUNASR_VAD_MODEL") or "").strip():
        env["VOICE_SERVICE_FUNASR_VAD_MODEL"] = str(vad) if vad.is_dir() else "fsmn-vad"
    if not (os.environ.get("VOICE_SERVICE_FUNASR_PUNC_MODEL") or "").strip():
        env["VOICE_SERVICE_FUNASR_PUNC_MODEL"] = str(punc) if punc.is_dir() else "ct-punc"
    return env


def build_voice_service_env() -> dict[str, str]:
    host, port = _service_host_port()
    env = os.environ.copy()
    env.setdefault("VOICE_SERVICE_STT_PROVIDER", "local-funasr")
    env.setdefault("VOICE_SERVICE_TTS_PROVIDER", "mock")
    env.setdefault("VOICE_SERVICE_HOST", host)
    env.setdefault("VOICE_SERVICE_PORT", str(port))
    env.update(_resolve_funasr_env())
    return env


def _script_path() -> Path:
    return _repo_root() / "tools" / "voice-service" / "voice_service.py"


def _voice_requirements_path() -> Path:
    return _repo_root() / "tools" / "voice-service" / "requirements.txt"


def _model_prepare_script_path() -> Path:
    return _repo_root() / "tools" / "voice-service" / "prepare_models.py"


def _voice_model_manifest_path() -> Path:
    return _repo_root() / ".runtime" / "models" / "voice" / "model_paths.json"


def _read_voice_model_paths() -> dict[str, str]:
    try:
        payload = json.loads(_voice_model_manifest_path().read_text(encoding="utf-8"))
        paths = payload.get("paths") if isinstance(payload, dict) else None
        if (
            isinstance(paths, dict)
            and _FUNASR_MODEL_ENV_KEYS.issubset(paths)
            and all(Path(paths[key]).is_dir() for key in _FUNASR_MODEL_ENV_KEYS)
        ):
            return {str(key): str(value) for key, value in paths.items()}
    except (OSError, ValueError, TypeError):
        pass
    return {}


def _run_checked(command: list[str], *, env: dict[str, str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        cwd=str(_repo_root()),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _prepare_voice_models(python_exe: str, env: dict[str, str], logger=None) -> bool:
    if env.get("VOICE_SERVICE_STT_PROVIDER", "").lower() != "local-funasr":
        return True
    explicit = {
        key: str(os.environ.get(key) or "").strip()
        for key in _FUNASR_MODEL_ENV_KEYS
    }
    explicit = {key: value for key, value in explicit.items() if value}
    if explicit and set(explicit) == _FUNASR_MODEL_ENV_KEYS and all(
        Path(value).expanduser().is_dir() for value in explicit.values()
    ):
        env.update(explicit)
        return True
    if not explicit:
        cached = _read_voice_model_paths()
        if cached:
            env.update(cached)
            return True
    if not _env_flag("VOICE_SERVICE_AUTO_DOWNLOAD", True):
        _log(logger, "error", "FunASR models are missing and VOICE_SERVICE_AUTO_DOWNLOAD=0")
        return False

    try:
        dependency_check = _run_checked(
            [python_exe, "-c", "import torch, funasr, modelscope"],
            env=env,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        _log(logger, "error", f"Unable to check voice model dependencies: {exc}")
        return False
    if dependency_check.returncode != 0:
        if not _env_flag("VOICE_SERVICE_AUTO_INSTALL", True):
            _log(logger, "error", "Voice model dependencies are missing and VOICE_SERVICE_AUTO_INSTALL=0")
            return False
        requirements = _voice_requirements_path()
        _log(logger, "info", f"Installing voice model dependencies from {requirements}")
        try:
            install = _run_checked(
                [python_exe, "-m", "pip", "install", "-r", str(requirements)],
                env=env,
                timeout=int(os.environ.get("VOICE_SERVICE_DEPENDENCY_INSTALL_TIMEOUT", "1800")),
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            _log(logger, "error", f"Voice model dependency installation failed: {exc}")
            return False
        if install.returncode != 0:
            detail = (install.stderr or install.stdout or "unknown pip failure")[-2000:]
            _log(logger, "error", f"Voice model dependency installation failed: {detail}")
            return False

    prepare_script = _model_prepare_script_path()
    attempts = max(1, int(os.environ.get("VOICE_SERVICE_MODEL_DOWNLOAD_RETRIES", "2")))
    timeout = int(os.environ.get("VOICE_SERVICE_MODEL_DOWNLOAD_TIMEOUT", "1800"))
    for attempt in range(1, attempts + 1):
        _log(logger, "info", f"Preparing local FunASR models ({attempt}/{attempts}); first startup may take several minutes")
        try:
            result = _run_checked([python_exe, str(prepare_script)], env=env, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            _log(
                logger,
                "warning" if attempt < attempts else "error",
                f"FunASR model preparation failed: {exc}",
            )
            continue
        if result.returncode == 0:
            cached = _read_voice_model_paths()
            if cached:
                env.update(cached)
                _log(logger, "info", f"Local FunASR models ready: {_voice_model_manifest_path()}")
                return True
        detail = (result.stderr or result.stdout or "model preparation failed")[-2000:]
        _log(logger, "warning" if attempt < attempts else "error", f"FunASR model preparation failed: {detail}")
    return False


def _stop_voice_service() -> None:
    global _voice_proc, _log_handle, _we_started
    if not _we_started:
        # 未由本进程拉起的实例不杀（可能是外部已有服务）
        _close_log()
        return

    proc = _voice_proc
    if proc is None or proc.poll() is not None:
        _voice_proc = None
        _we_started = False
        _close_log()
        return

    try:
        if sys.platform == "win32":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
    except Exception:
        pass
    finally:
        _voice_proc = None
        _we_started = False
        _close_log()


def _close_log() -> None:
    global _log_handle
    handle = _log_handle
    _log_handle = None
    if handle is not None:
        try:
            handle.close()
        except Exception:
            pass


def _wait_listening(host: str, port: int, timeout_s: float = 8.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _port_listening(host, port):
            return True
        time.sleep(0.25)
    return False


def _start_voice_service_sync(logger=None) -> bool:
    """
    若 8765 未占用则后台拉起 voice_service.py。
    成功或已有服务返回 True；跳过/失败返回 False（不阻塞后端）。
    """
    global _voice_proc, _log_handle, _cleanup_registered, _we_started

    if not should_start_voice_service():
        return False

    host, port = _service_host_port()
    if _port_listening(host, port):
        _log(
            logger,
            "info",
            f"Voice service 已在监听 {host}:{port}，跳过启动",
        )
        return True

    if _voice_proc is not None and _voice_proc.poll() is None:
        return True

    script = _script_path()
    if not script.is_file():
        _log(logger, "warning", f"未找到 voice-service 脚本: {script}")
        return False

    python_exe = resolve_voice_python()
    log_dir = _repo_root() / ".runtime" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "voice-service.log"

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    try:
        _log_handle = open(log_path, "a", encoding="utf-8", buffering=1)
        _log_handle.write(
            f"\n===== voice-service start {time.strftime('%Y-%m-%d %H:%M:%S')} "
            f"python={python_exe} =====\n"
        )
        service_env = build_voice_service_env()
        if not _prepare_voice_models(python_exe, service_env, logger):
            _log(logger, "error", "Voice service was not started because its local models are unavailable")
            _close_log()
            return False
        _voice_proc = subprocess.Popen(
            [python_exe, str(script)],
            cwd=str(_repo_root()),
            stdout=_log_handle,
            stderr=subprocess.STDOUT,
            env=service_env,
            creationflags=creationflags,
        )
        _we_started = True
    except Exception as exc:
        _log(logger, "error", f"启动 voice-service 失败: {exc}")
        _voice_proc = None
        _we_started = False
        _close_log()
        return False

    if not _cleanup_registered:
        atexit.register(_stop_voice_service)
        _cleanup_registered = True

    ready = _wait_listening(host, port, timeout_s=12.0)
    if ready:
        _log(
            logger,
            "info",
            f"Voice service 已启动 (pid={_voice_proc.pid}) → http://{host}:{port}/health "
            f"（日志 {log_path}；关闭: START_VOICE_SERVICE=0）",
        )
        return True

    # 进程可能还在加载，端口稍后才开
    if _voice_proc.poll() is None:
        _log(
            logger,
            "warning",
            f"Voice service 已拉起 (pid={_voice_proc.pid})，但 12s 内未监听 "
            f"{host}:{port}；请查看 {log_path}",
        )
        return True

    _log(
        logger,
        "error",
        f"Voice service 启动后立即退出 (code={_voice_proc.returncode})；见 {log_path}",
    )
    _voice_proc = None
    _we_started = False
    _close_log()
    return False


def _voice_service_thread_main(logger=None) -> None:
    global _startup_thread
    try:
        _start_voice_service_sync(logger)
    finally:
        with _startup_lock:
            _startup_thread = None


def start_voice_service(logger=None) -> bool:
    """Schedule model preparation and voice-service startup without blocking Flask."""
    global _startup_thread

    if not should_start_voice_service():
        return False

    host, port = _service_host_port()
    if _port_listening(host, port):
        _log(logger, "info", f"Voice service is already listening on {host}:{port}")
        return True

    with _startup_lock:
        if _voice_proc is not None and _voice_proc.poll() is None:
            return True
        if _startup_thread is not None and _startup_thread.is_alive():
            return True
        _startup_thread = threading.Thread(
            target=_voice_service_thread_main,
            args=(logger,),
            name="voice-service-startup",
            daemon=True,
        )
        _startup_thread.start()

    _log(logger, "info", "Voice service preparation scheduled in background; Flask startup will continue")
    return True


def _log(logger, level: str, message: str) -> None:
    if logger is not None:
        getattr(logger, level, logger.info)(message)
    else:
        print(f"[{level.upper()}] {message}")
