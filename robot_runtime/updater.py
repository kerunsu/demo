"""Self-update helpers for RobotRuntime.exe (frozen builds)."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional

import requests

from robot_runtime import register_client

_SIDECARS = ("start.bat", "README.txt", "VERSION", "Open-ChildLanMic.ps1")


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def read_runtime_version() -> str:
    candidates = []
    if is_frozen():
        meipass = Path(getattr(sys, "_MEIPASS", "."))
        candidates.append(meipass / "robot_runtime" / "VERSION")
        candidates.append(meipass / "VERSION")
        candidates.append(Path(sys.executable).resolve().parent / "VERSION")
    else:
        candidates.append(Path(__file__).resolve().parent / "VERSION")
    for path in candidates:
        try:
            if path.is_file():
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    return text
        except Exception:
            continue
    return "unknown"


def check_update(backend_url: Optional[str] = None) -> Dict[str, Any]:
    local = read_runtime_version()
    base = (backend_url or register_client.BACKEND_URL or "").rstrip("/")
    result: Dict[str, Any] = {
        "ok": True,
        "localVersion": local,
        "remoteVersion": None,
        "available": False,
        "updateAvailable": False,
        "frozen": is_frozen(),
        "filename": None,
        "sizeBytes": 0,
        "sha256": None,
        "builtAt": None,
        "backendUrl": base or None,
        "error": None,
    }
    if not base:
        result["ok"] = False
        result["error"] = "backend URL not set"
        return result
    try:
        resp = requests.get(f"{base}/api/robot/runtime/version", timeout=15)
        body = resp.json() if resp.content else {}
        if resp.status_code != 200:
            result["ok"] = False
            result["error"] = f"HTTP {resp.status_code}"
            return result
        remote = body.get("version")
        pkg_ok = bool(body.get("available"))
        result["remoteVersion"] = remote
        result["available"] = pkg_ok
        result["filename"] = body.get("filename")
        result["sizeBytes"] = body.get("sizeBytes") or 0
        result["sha256"] = body.get("sha256")
        result["builtAt"] = body.get("builtAt")
        if pkg_ok and remote and str(remote) != str(local):
            # 仅当远程版本与本地不同时提示可更新。
            # 注意：manifest 必须指向真正最新包；错误的旧 version 会导致“回退式更新”。
            result["updateAvailable"] = True
            # 把远端内嵌的 builtAt 一并暴露，便于 /ui 人工核对是否真比本地新
            result["hint"] = (
                "若更新后功能变旧，请检查服务器 releases/robot/manifest.json "
                "是否仍指向过期 zip。"
            )
        return result
    except Exception as exc:
        result["ok"] = False
        result["error"] = str(exc)
        return result


def _find_in_tree(root: Path, name: str) -> Optional[Path]:
    direct = root / name
    if direct.is_file():
        return direct
    for path in root.rglob(name):
        if path.is_file():
            return path
    return None


def download_and_prepare_update(backend_url: Optional[str] = None) -> Dict[str, Any]:
    """Download release zip, extract, locate RobotRuntime.exe + sidecars."""
    base = (backend_url or register_client.BACKEND_URL or "").rstrip("/")
    if not base:
        return {"ok": False, "error": "backend URL not set"}

    cfg_dir = register_client.config_dir()
    staging = cfg_dir / "update_staging"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    zip_path = staging / "release.zip"
    url = f"{base}/api/robot/runtime/download"
    headers = {}
    key = register_client.RUNTIME_KEY
    if key:
        headers["X-Robot-Runtime-Key"] = key
        headers["X-Child-Media-Agent-Key"] = key

    try:
        with requests.get(url, headers=headers, stream=True, timeout=300) as resp:
            if resp.status_code != 200:
                return {
                    "ok": False,
                    "error": f"download HTTP {resp.status_code}: {(resp.text or '')[:200]}",
                }
            with open(zip_path, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        fh.write(chunk)
    except Exception as exc:
        return {"ok": False, "error": f"download failed: {exc}"}

    extract_dir = staging / "extracted"
    extract_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)
    except Exception as exc:
        return {"ok": False, "error": f"unzip failed: {exc}"}

    new_exe = _find_in_tree(extract_dir, "RobotRuntime.exe")
    if not new_exe:
        return {"ok": False, "error": "RobotRuntime.exe not found in release zip"}

    prepared = staging / "prepared"
    if prepared.exists():
        shutil.rmtree(prepared, ignore_errors=True)
    prepared.mkdir(parents=True, exist_ok=True)
    shutil.copy2(new_exe, prepared / "RobotRuntime.exe")
    sidecars = {}
    for name in _SIDECARS:
        src = _find_in_tree(extract_dir, name)
        if src:
            dest = prepared / name
            shutil.copy2(src, dest)
            sidecars[name] = str(dest)

    return {
        "ok": True,
        "exePath": str(prepared / "RobotRuntime.exe"),
        "preparedDir": str(prepared),
        "sidecars": sidecars,
        "stagingDir": str(staging),
    }


def cleanup_stale_update_files(exe_path: Optional[Path] = None) -> None:
    """Best-effort: remove RobotRuntime.exe.old left by previous self-update."""
    try:
        target = Path(exe_path or sys.executable).resolve()
        old = Path(str(target) + ".old")
        if old.is_file():
            old.unlink(missing_ok=True)
    except Exception:
        pass


def launch_swap_and_exit(prepared: Dict[str, Any]) -> Dict[str, Any]:
    """
    Write update_restart.bat, start it, then exit current process (frozen only).

    Windows cannot overwrite a just-exited (or still-mapped) exe reliably with a
    single ``copy /Y``. Sidecars succeed because they are unlocked; the exe copy
    often fails silently when stdout is redirected to NUL — then the bat restarts
    the *old* binary. Fix: rename-old → copy-new with retries + log file.
    """
    if not is_frozen():
        return {
            "ok": False,
            "error": "auto-update only supported for RobotRuntime.exe (frozen). "
            "Source mode: re-run scripts/pack_robot_release.ps1 and replace files manually.",
            "preparedDir": prepared.get("preparedDir"),
        }

    new_exe = Path(prepared["exePath"])
    if not new_exe.is_file():
        return {"ok": False, "error": "prepared exe missing"}

    target_exe = Path(sys.executable).resolve()
    target_dir = target_exe.parent
    target_old = Path(str(target_exe) + ".old")
    cfg_dir = register_client.config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    bat_path = cfg_dir / "update_restart.bat"
    log_path = cfg_dir / "update_restart.log"
    pid = os.getpid()
    port = int(os.environ.get("ROBOT_RUNTIME_PORT") or os.environ.get("CHILD_MEDIA_AGENT_PORT") or 19091)

    sidecar_lines: list[str] = []
    for name in _SIDECARS:
        src = Path(prepared.get("sidecars", {}).get(name, ""))
        if src.is_file():
            dest = target_dir / name
            sidecar_lines.append(
                f'copy /Y "{src}" "{dest}" >>"%LOG%" 2>&1'
            )

    # Keep bat ASCII-friendly (cmd.exe). Paths may contain non-ASCII; quote them.
    bat_lines = [
        "@echo off",
        "setlocal EnableExtensions EnableDelayedExpansion",
        f'set "LOG={log_path}"',
        f'set "NEW_EXE={new_exe}"',
        f'set "TARGET={target_exe}"',
        f'set "TARGET_OLD={target_old}"',
        f'set "PID={pid}"',
        f'set "PORT={port}"',
        'echo.>>"%LOG%"',
        'echo ===== EIArt update %date% %time% =====>>"%LOG%"',
        'echo waiting for PID %PID% ...>>"%LOG%"',
        "set /a WAIT=0",
        ":waitloop",
        'tasklist /FI "PID eq %PID%" 2>NUL | find "%PID%" >NUL',
        "if not errorlevel 1 (",
        "  set /a WAIT+=1",
        "  if !WAIT! GEQ 45 (",
        '    echo PID still alive after 45s, taskkill /F>>"%LOG%"',
        "    taskkill /F /PID %PID% >NUL 2>&1",
        "    timeout /t 2 /nobreak >NUL",
        "    goto doreplace",
        "  )",
        "  timeout /t 1 /nobreak >NUL",
        "  goto waitloop",
        ")",
        'echo PID exited, extra settle 2s>>"%LOG%"',
        "timeout /t 2 /nobreak >NUL",
        ":doreplace",
        "set /a TRY=0",
        ":retry",
        "set /a TRY+=1",
        'echo replace try !TRY!/40>>"%LOG%"',
        'if exist "%TARGET_OLD%" del /F /Q "%TARGET_OLD%" >>"%LOG%" 2>&1',
        'if exist "%TARGET%" (',
        '  move /Y "%TARGET%" "%TARGET_OLD%" >>"%LOG%" 2>&1',
        "  if errorlevel 1 (",
        '    echo rename old exe failed>>"%LOG%"',
        "    if !TRY! LSS 40 (",
        "      timeout /t 1 /nobreak >NUL",
        "      goto retry",
        "    )",
        "    goto fail",
        "  )",
        ")",
        'copy /Y "%NEW_EXE%" "%TARGET%" >>"%LOG%" 2>&1',
        "if errorlevel 1 (",
        '  echo copy new exe failed, rollback>>"%LOG%"',
        '  if exist "%TARGET_OLD%" move /Y "%TARGET_OLD%" "%TARGET%" >>"%LOG%" 2>&1',
        "  if !TRY! LSS 40 (",
        "    timeout /t 1 /nobreak >NUL",
        "    goto retry",
        "  )",
        "  goto fail",
        ")",
        'echo exe replaced OK>>"%LOG%"',
        *sidecar_lines,
        'echo starting new Runtime>>"%LOG%"',
        'start "" "%TARGET%"',
        f'start "" cmd /c "timeout /t 3 /nobreak >NUL && start http://127.0.0.1:{port}/ui"',
        'del /F /Q "%TARGET_OLD%" >>"%LOG%" 2>&1',
        'echo update success>>"%LOG%"',
        "endlocal",
        "exit /b 0",
        ":fail",
        'echo UPDATE FAILED — see this log.>>"%LOG%"',
        'if not exist "%TARGET%" if exist "%TARGET_OLD%" move /Y "%TARGET_OLD%" "%TARGET%" >>"%LOG%" 2>&1',
        'if exist "%TARGET%" start "" "%TARGET%"',
        "endlocal",
        "exit /b 1",
        "",
    ]
    bat_path.write_text("\r\n".join(bat_lines), encoding="utf-8")

    # CREATE_NEW_CONSOLE 与 DETACHED_PROCESS 不能同时用，否则 WinError 87
    popen_kwargs: Dict[str, Any] = {
        "args": ["cmd.exe", "/c", str(bat_path)],
        "cwd": str(target_dir),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    subprocess.Popen(**popen_kwargs)
    return {
        "ok": True,
        "restarting": True,
        "batPath": str(bat_path),
        "logPath": str(log_path),
        "pid": pid,
        "hint": "若重启后版本未变，请查看 update_restart.log（通常在 %LOCALAPPDATA%\\EIArt\\robot_runtime\\）",
    }
