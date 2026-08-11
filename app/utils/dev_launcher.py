"""Build the teacher SPA for same-origin serving by Flask on port 8080."""

from __future__ import annotations

import atexit
import os
import shutil
import signal
import socket
import subprocess
import sys
from pathlib import Path
from typing import Optional

_frontend_proc: Optional[subprocess.Popen] = None
_cleanup_registered = False


def should_start_teacher_frontend() -> bool:
    """Whether startup should ensure a production teacher build exists."""
    flag = os.environ.get("START_TEACHER_FRONTEND", "1").strip().lower()
    if flag in ("0", "false", "no", "off"):
        return False
    # Werkzeug debug 热重载会跑父子两进程；只在父进程启动，避免重复与反复重启 Vite
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        return False
    return True


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _npm_executable() -> Optional[str]:
    for name in ("npm.cmd", "npm"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _port_is_listening(host: str = "127.0.0.1", port: int = 5173) -> bool:
    """Return whether an existing teacher frontend already owns the dev port."""
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _stop_teacher_frontend() -> None:
    global _frontend_proc
    proc = _frontend_proc
    if proc is None or proc.poll() is not None:
        _frontend_proc = None
        return

    try:
        if sys.platform == "win32":
            # 结束 npm 及其子进程（node/vite）
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
        _frontend_proc = None


def start_teacher_frontend(logger=None) -> bool:
    """
    Run a finite production build; Flask serves dist at /teacher/ on 8080.
    No long-lived Vite process or port 5173 is started.
    """
    if not should_start_teacher_frontend():
        return False

    frontend_dir = _repo_root() / "teacher_frontend"
    if not frontend_dir.is_dir():
        _log(logger, "warning", f"未找到教师端目录: {frontend_dir}")
        return False

    if not (frontend_dir / "node_modules").is_dir():
        _log(
            logger,
            "warning",
            "教师端依赖未安装，已跳过 Vite。"
            "请先执行: cd teacher_frontend && npm ci",
        )
        return False

    npm = _npm_executable()
    if not npm:
        _log(logger, "warning", "未找到 npm，已跳过教师端启动。请确认 Node.js 已安装并在 PATH 中。")
        return False

    try:
        completed = subprocess.run(
            [npm, "run", "build"],
            cwd=str(frontend_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=180,
            check=False,
        )
    except Exception as exc:
        _log(logger, "error", f"构建教师端失败: {exc}")
        return False
    if completed.returncode != 0:
        tail = '\n'.join((completed.stdout or '').splitlines()[-20:])
        _log(logger, "error", f"构建教师端失败 (exit={completed.returncode}):\n{tail}")
        return False

    _log(
        logger,
        "info",
        "教师端生产包已构建，由 Server 同源提供: http://<本机IP>:8080/teacher/",
    )
    return True


def _log(logger, level: str, message: str) -> None:
    if logger is not None:
        getattr(logger, level, logger.info)(message)
    else:
        print(f"[{level.upper()}] {message}")
