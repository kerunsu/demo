"""Reliable self-update helpers for packaged ``RobotRuntime.exe`` builds."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Dict, Optional
from urllib.parse import urljoin

import requests

from robot_runtime import register_client

_SIDECARS = (
    "start.bat",
    "start_robot_runtime.ps1",
    "restart.bat",
    "restart_robot_runtime.ps1",
    "README.txt",
    "VERSION",
    "Open-ChildLanMic.ps1",
)
_VERSION_STAMP_RE = re.compile(r"^(\d{8})-(\d{4})(?:-|$)")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_MAX_PACKAGE_BYTES = 512 * 1024 * 1024
_Progress = Optional[Callable[[Dict[str, Any]], None]]


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
                text = path.read_text(encoding="utf-8-sig").strip()
                if text:
                    return text
        except Exception:
            continue
    return "unknown"


def _backend_url(candidate: Optional[str] = None) -> str:
    status = register_client.get_registry_status()
    return str(
        candidate
        or register_client.BACKEND_URL
        or status.get("backendUrl")
        or status.get("backendPublicUrl")
        or ""
    ).strip().rstrip("/")


def _headers() -> Dict[str, str]:
    headers = {"User-Agent": f"EIArt-RobotRuntime/{read_runtime_version()}"}
    key = register_client.RUNTIME_KEY
    if key:
        headers["X-Robot-Runtime-Key"] = key
        headers["X-Child-Media-Agent-Key"] = key
    return headers


def _version_rank(value: Any) -> Optional[int]:
    match = _VERSION_STAMP_RE.match(str(value or "").strip())
    if not match:
        return None
    return int(match.group(1) + match.group(2))


def _is_remote_newer(local: str, remote: str) -> tuple[bool, bool]:
    if not remote or remote == local:
        return False, False
    local_rank = _version_rank(local)
    remote_rank = _version_rank(remote)
    if local_rank is not None and remote_rank is not None:
        return remote_rank > local_rank, remote_rank < local_rank
    # Historical/custom versions are not reliably sortable. Preserve the
    # compatible inequality behavior while exposing that ordering is unknown.
    return True, False


def _emit(progress: _Progress, **payload: Any) -> None:
    if progress is None:
        return
    try:
        progress(payload)
    except Exception:
        pass


def _log_path() -> Path:
    path = register_client.config_dir() / "update_runtime.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _log(message: str) -> None:
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        with _log_path().open("a", encoding="utf-8") as stream:
            stream.write(f"{timestamp} {message}\n")
    except Exception:
        pass


def read_update_log_tail(max_lines: int = 120) -> Dict[str, Any]:
    path = _log_path()
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    return {
        "ok": True,
        "path": str(path),
        "lines": lines[-max(1, min(int(max_lines), 500)):],
    }


def check_update(backend_url: Optional[str] = None) -> Dict[str, Any]:
    local = read_runtime_version()
    base = _backend_url(backend_url)
    result: Dict[str, Any] = {
        "ok": True,
        "localVersion": local,
        "remoteVersion": None,
        "available": False,
        "updateAvailable": False,
        "remoteOlder": False,
        "frozen": is_frozen(),
        "filename": None,
        "sizeBytes": 0,
        "sha256": None,
        "builtAt": None,
        "backendUrl": base or None,
        "downloadUrl": None,
        "dedicatedUpdatePackage": False,
        "error": None,
        "errorCode": None,
    }
    if not base:
        result.update({
            "ok": False,
            "errorCode": "backend_url_missing",
            "error": "后端地址未设置，请先在上方填写并点击“应用并注册”",
        })
        return result
    try:
        resp = requests.get(
            f"{base}/api/robot/runtime/version",
            headers=_headers(),
            timeout=(8, 20),
        )
        try:
            body = resp.json() if resp.content else {}
        except ValueError:
            snippet = (resp.text or "")[:160].replace("\n", " ")
            result.update({
                "ok": False,
                "errorCode": "manifest_not_json",
                "error": f"服务器返回的不是版本信息（HTTP {resp.status_code}）：{snippet}",
            })
            return result
        if resp.status_code != 200:
            result.update({
                "ok": False,
                "errorCode": "manifest_http_error",
                "error": body.get("error") or f"版本检查 HTTP {resp.status_code}",
            })
            return result

        remote = str(body.get("version") or "").strip()
        update_package_available = bool(body.get("updatePackageAvailable"))
        dedicated = bool(body.get("dedicatedUpdatePackage"))
        pkg_ok = update_package_available or bool(body.get("available"))
        if update_package_available:
            filename = body.get("updateFilename")
            size = body.get("updateSizeBytes") or 0
            sha256 = body.get("updateSha256")
            download_url = body.get("updateDownloadUrl")
        else:
            filename = body.get("filename")
            size = body.get("sizeBytes") or 0
            sha256 = body.get("sha256")
            download_url = body.get("downloadUrl")
        newer, older = _is_remote_newer(local, remote)
        result.update({
            "remoteVersion": remote or None,
            "available": pkg_ok,
            "filename": filename,
            "sizeBytes": size,
            "sha256": sha256,
            "builtAt": body.get("builtAt"),
            "downloadUrl": download_url,
            "dedicatedUpdatePackage": dedicated,
            "updateAvailable": bool(pkg_ok and remote and newer),
            "remoteOlder": bool(pkg_ok and remote and older),
        })
        if not pkg_ok:
            result["error"] = body.get("updateError") or body.get("error")
            result["errorCode"] = "package_unavailable"
        elif older:
            result["hint"] = "服务器版本早于本机，已阻止自动降级。"
        elif not is_frozen():
            result["hint"] = "当前为源码运行模式，不能在线替换进程。"
        return result
    except requests.RequestException as exc:
        result.update({
            "ok": False,
            "errorCode": "manifest_network_error",
            "error": f"无法连接服务器检查更新：{exc}",
        })
        return result
    except Exception as exc:  # noqa: BLE001
        result.update({
            "ok": False,
            "errorCode": "manifest_unexpected_error",
            "error": f"检查更新失败：{exc}",
        })
        return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_with_resume(
    url: str,
    destination: Path,
    *,
    expected_size: int,
    progress: _Progress,
) -> Optional[str]:
    part = destination.with_suffix(destination.suffix + ".part")
    destination.unlink(missing_ok=True)
    last_error = "download did not start"
    for attempt in range(1, 4):
        downloaded = part.stat().st_size if part.is_file() else 0
        if downloaded == expected_size:
            os.replace(part, destination)
            return None
        if downloaded > expected_size:
            part.unlink(missing_ok=True)
            downloaded = 0
        headers = _headers()
        if downloaded:
            headers["Range"] = f"bytes={downloaded}-"
        _emit(
            progress,
            stage="downloading",
            attempt=attempt,
            downloadedBytes=downloaded,
            totalBytes=expected_size,
        )
        try:
            with requests.get(
                url,
                headers=headers,
                stream=True,
                timeout=(10, 120),
            ) as resp:
                if resp.status_code not in {200, 206}:
                    snippet = (resp.text or "")[:200].replace("\n", " ")
                    last_error = f"download HTTP {resp.status_code}: {snippet}"
                    _log(f"download attempt={attempt} failed: {last_error}")
                    continue
                append = resp.status_code == 206 and downloaded > 0
                if append:
                    content_range = str(resp.headers.get("Content-Range") or "")
                    if not content_range.startswith(f"bytes {downloaded}-"):
                        part.unlink(missing_ok=True)
                        last_error = f"invalid Content-Range: {content_range or 'missing'}"
                        continue
                else:
                    downloaded = 0
                mode = "ab" if append else "wb"
                with part.open(mode) as stream:
                    for chunk in resp.iter_content(chunk_size=1024 * 512):
                        if not chunk:
                            continue
                        stream.write(chunk)
                        downloaded += len(chunk)
                        if downloaded > _MAX_PACKAGE_BYTES:
                            raise ValueError("download exceeds 512 MB safety limit")
                        _emit(
                            progress,
                            stage="downloading",
                            attempt=attempt,
                            downloadedBytes=downloaded,
                            totalBytes=expected_size,
                        )
                    stream.flush()
                    os.fsync(stream.fileno())
        except (requests.RequestException, OSError, ValueError) as exc:
            last_error = str(exc)
            _log(f"download attempt={attempt} interrupted at {downloaded}: {exc}")

        actual_size = part.stat().st_size if part.is_file() else 0
        if actual_size == expected_size:
            os.replace(part, destination)
            return None
        last_error = (
            f"download incomplete: expected {expected_size} bytes, got {actual_size}"
        )
        _log(f"download attempt={attempt} incomplete: {last_error}")
        if attempt < 3:
            time.sleep(min(attempt, 2))
    return last_error


def _safe_members(archive: zipfile.ZipFile) -> Dict[str, zipfile.ZipInfo]:
    selected: Dict[str, zipfile.ZipInfo] = {}
    wanted = {"RobotRuntime.exe", *_SIDECARS}
    for info in archive.infolist():
        raw = info.filename.replace("\\", "/")
        path = PurePosixPath(raw)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError(f"unsafe zip entry: {info.filename}")
        if info.is_dir() or path.name not in wanted:
            continue
        current = selected.get(path.name)
        if current is None or raw.count("/") < current.filename.count("/"):
            selected[path.name] = info
    return selected


def download_and_prepare_update(
    backend_url: Optional[str] = None,
    *,
    progress: _Progress = None,
) -> Dict[str, Any]:
    """Download, resume, verify and stage a Runtime update transaction."""
    base = _backend_url(backend_url)
    if not base:
        return {
            "ok": False,
            "errorCode": "backend_url_missing",
            "error": "后端地址未设置，请先应用并注册",
        }

    _emit(progress, stage="checking", downloadedBytes=0, totalBytes=0)
    release = check_update(base)
    if not release.get("ok"):
        return release
    if not release.get("available"):
        return {
            **release,
            "ok": False,
            "errorCode": "package_unavailable",
            "error": release.get("error") or "服务器发布包不可用或校验失败",
        }
    if release.get("remoteOlder"):
        return {
            **release,
            "ok": False,
            "errorCode": "downgrade_blocked",
            "error": "服务器版本早于本机，已阻止自动降级",
        }
    if not release.get("updateAvailable"):
        return {**release, "ok": True, "alreadyLatest": True}

    try:
        expected_size = int(release.get("sizeBytes") or 0)
    except (TypeError, ValueError):
        expected_size = 0
    expected_hash = str(release.get("sha256") or "").strip().lower()
    expected_version = str(release.get("remoteVersion") or "").strip()
    if not 0 < expected_size <= _MAX_PACKAGE_BYTES:
        return {
            "ok": False,
            "errorCode": "package_size_invalid",
            "error": f"服务器发布包大小无效：{expected_size}",
        }
    if not _SHA256_RE.fullmatch(expected_hash):
        return {
            "ok": False,
            "errorCode": "package_hash_invalid",
            "error": "服务器没有提供有效的 SHA256，拒绝更新",
        }
    raw_download_url = str(release.get("downloadUrl") or "").strip()
    if not raw_download_url:
        return {
            "ok": False,
            "errorCode": "download_url_missing",
            "error": "服务器没有提供更新下载地址",
        }
    url = urljoin(base + "/", raw_download_url)

    cfg_dir = register_client.config_dir()
    staging = cfg_dir / "update_staging"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    zip_path = staging / "release.zip"
    _log(
        f"begin local={release.get('localVersion')} remote={expected_version} "
        f"url={url} size={expected_size} dedicated={release.get('dedicatedUpdatePackage')}"
    )
    download_error = _download_with_resume(
        url,
        zip_path,
        expected_size=expected_size,
        progress=progress,
    )
    if download_error:
        return {
            "ok": False,
            "errorCode": "download_failed",
            "error": f"更新包下载失败（已自动重试 3 次）：{download_error}",
            "logPath": str(_log_path()),
        }

    _emit(
        progress,
        stage="verifying",
        downloadedBytes=expected_size,
        totalBytes=expected_size,
    )
    actual_hash = _sha256(zip_path)
    if actual_hash != expected_hash:
        error = f"SHA256 不一致：期望 {expected_hash}，实际 {actual_hash}"
        _log(error)
        return {
            "ok": False,
            "errorCode": "package_hash_mismatch",
            "error": error,
            "logPath": str(_log_path()),
        }

    prepared = staging / "prepared"
    prepared.mkdir(parents=True, exist_ok=True)
    _emit(
        progress,
        stage="extracting",
        downloadedBytes=expected_size,
        totalBytes=expected_size,
    )
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            corrupt = archive.testzip()
            if corrupt:
                raise ValueError(f"corrupt zip entry: {corrupt}")
            members = _safe_members(archive)
            if "RobotRuntime.exe" not in members:
                raise ValueError("RobotRuntime.exe not found in release zip")
            if "VERSION" not in members:
                raise ValueError("VERSION not found in release zip")
            sidecars: Dict[str, str] = {}
            for name, info in members.items():
                destination = prepared / name
                temporary = prepared / f".{name}.tmp"
                with archive.open(info, "r") as source, temporary.open("wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(temporary, destination)
                if name != "RobotRuntime.exe":
                    sidecars[name] = str(destination)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        _log(f"extract failed: {exc}")
        return {
            "ok": False,
            "errorCode": "package_extract_failed",
            "error": f"更新包解压或完整性检查失败：{exc}",
            "logPath": str(_log_path()),
        }

    new_exe = prepared / "RobotRuntime.exe"
    try:
        with new_exe.open("rb") as stream:
            exe_header = stream.read(2)
        prepared_version = (prepared / "VERSION").read_text(
            encoding="utf-8-sig"
        ).strip()
    except OSError as exc:
        return {
            "ok": False,
            "errorCode": "prepared_files_unreadable",
            "error": f"准备好的更新文件无法读取：{exc}",
        }
    if exe_header != b"MZ" or new_exe.stat().st_size < 1024 * 1024:
        return {
            "ok": False,
            "errorCode": "runtime_exe_invalid",
            "error": "更新包内 RobotRuntime.exe 不是有效的 Windows 程序",
        }
    if prepared_version != expected_version:
        return {
            "ok": False,
            "errorCode": "package_version_mismatch",
            "error": (
                f"更新包版本不一致：服务器声明 {expected_version}，"
                f"包内为 {prepared_version or 'missing'}"
            ),
        }

    _log(f"prepared version={prepared_version} exe={new_exe.stat().st_size}")
    _emit(
        progress,
        stage="prepared",
        downloadedBytes=expected_size,
        totalBytes=expected_size,
        remoteVersion=expected_version,
    )
    return {
        "ok": True,
        "exePath": str(new_exe),
        "preparedDir": str(prepared),
        "sidecars": sidecars,
        "stagingDir": str(staging),
        "remoteVersion": expected_version,
        "downloadedBytes": expected_size,
        "totalBytes": expected_size,
        "packageSha256": actual_hash,
        "dedicatedUpdatePackage": bool(release.get("dedicatedUpdatePackage")),
        "logPath": str(_log_path()),
    }


def cleanup_stale_update_files(exe_path: Optional[Path] = None) -> None:
    """Best-effort: remove ``RobotRuntime.exe.old`` after a successful update."""
    try:
        target = Path(exe_path or sys.executable).resolve()
        old = Path(str(target) + ".old")
        if old.is_file():
            old.unlink(missing_ok=True)
    except Exception:
        pass


def _ps_quote(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def launch_swap_and_exit(prepared: Dict[str, Any]) -> Dict[str, Any]:
    """Launch an external PowerShell transaction that swaps the frozen exe."""
    if not is_frozen():
        return {
            "ok": False,
            "errorCode": "source_mode_not_updatable",
            "error": "源码运行模式不能在线替换进程，请使用机器人安装包",
            "preparedDir": prepared.get("preparedDir"),
        }

    new_exe = Path(str(prepared.get("exePath") or ""))
    if not new_exe.is_file():
        return {
            "ok": False,
            "errorCode": "prepared_exe_missing",
            "error": "准备好的 RobotRuntime.exe 不存在",
        }

    target_exe = Path(sys.executable).resolve()
    target_dir = target_exe.parent
    target_old = Path(str(target_exe) + ".old")
    cfg_dir = register_client.config_dir()
    cfg_dir.mkdir(parents=True, exist_ok=True)
    script_path = cfg_dir / "update_restart.ps1"
    log_path = cfg_dir / "update_restart.log"
    pid = os.getpid()
    runtime_port = int(
        os.environ.get("ROBOT_RUNTIME_PORT")
        or os.environ.get("CHILD_MEDIA_AGENT_PORT")
        or 19091
    )

    sidecar_pairs = []
    for name in _SIDECARS:
        source_value = str(prepared.get("sidecars", {}).get(name) or "")
        if not source_value:
            continue
        source = Path(source_value)
        if source.is_file():
            sidecar_pairs.append((source, target_dir / name))

    lines = [
        "$ErrorActionPreference = 'Stop'",
        f"$LogPath = {_ps_quote(log_path)}",
        f"$NewExe = {_ps_quote(new_exe)}",
        f"$Target = {_ps_quote(target_exe)}",
        f"$TargetOld = {_ps_quote(target_old)}",
        f"$TargetDir = {_ps_quote(target_dir)}",
        f"$RuntimeUrl = 'http://127.0.0.1:{runtime_port}'",
        f"$RuntimePid = {pid}",
        "function Write-UpdateLog([string]$Message) {",
        "  Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value ((Get-Date -Format o) + ' ' + $Message)",
        "}",
        "Write-UpdateLog 'update transaction started'",
        "$Replaced = $false",
        "try {",
        "  for ($Wait = 0; $Wait -lt 45; $Wait++) {",
        "    if (-not (Get-Process -Id $RuntimePid -ErrorAction SilentlyContinue)) { break }",
        "    Start-Sleep -Seconds 1",
        "  }",
        "  if (Get-Process -Id $RuntimePid -ErrorAction SilentlyContinue) {",
        "    Write-UpdateLog 'old Runtime still alive after 45s; stopping it'",
        "    Stop-Process -Id $RuntimePid -Force -ErrorAction Stop",
        "    Start-Sleep -Seconds 2",
        "  } else { Start-Sleep -Seconds 2 }",
        "  for ($Attempt = 1; $Attempt -le 40; $Attempt++) {",
        "    try {",
        "      if (Test-Path -LiteralPath $TargetOld) { Remove-Item -LiteralPath $TargetOld -Force }",
        "      if (Test-Path -LiteralPath $Target) { Move-Item -LiteralPath $Target -Destination $TargetOld -Force }",
        "      Copy-Item -LiteralPath $NewExe -Destination $Target -Force",
        "      $Replaced = $true",
        "      Write-UpdateLog ('exe replaced on attempt ' + $Attempt)",
        "      break",
        "    } catch {",
        "      Write-UpdateLog ('replace attempt ' + $Attempt + ' failed: ' + $_.Exception.Message)",
        "      if (-not (Test-Path -LiteralPath $Target) -and (Test-Path -LiteralPath $TargetOld)) {",
        "        Move-Item -LiteralPath $TargetOld -Destination $Target -Force -ErrorAction SilentlyContinue",
        "      }",
        "      if ($Attempt -lt 40) { Start-Sleep -Seconds 1 }",
        "    }",
        "  }",
        "  if (-not $Replaced) { throw 'cannot replace RobotRuntime.exe after 40 attempts' }",
    ]
    for source, destination in sidecar_pairs:
        lines.append(
            f"  Copy-Item -LiteralPath {_ps_quote(source)} -Destination {_ps_quote(destination)} -Force"
        )
    lines.extend([
        "  Start-Process -FilePath $Target -WorkingDirectory $TargetDir -WindowStyle Hidden",
        "  $RuntimeOnline = $false",
        "  for ($ReadyAttempt = 1; $ReadyAttempt -le 60; $ReadyAttempt++) {",
        "    Start-Sleep -Milliseconds 500",
        "    try {",
        "      $Health = Invoke-RestMethod -Uri ($RuntimeUrl + '/health') -TimeoutSec 2",
        "      if ($Health.service -eq 'robot_runtime') { $RuntimeOnline = $true; break }",
        "    } catch { }",
        "  }",
        "  if (-not $RuntimeOnline) { throw 'new Runtime did not answer /health after restart' }",
        "  Write-UpdateLog 'new Runtime is online; restoring child page'",
        "  try {",
        "    Invoke-RestMethod -Method Post -Uri ($RuntimeUrl + '/ui/open-child') -ContentType 'application/json' -Body '{}' -TimeoutSec 10 | Out-Null",
        "  } catch { Write-UpdateLog ('child page restore warning: ' + $_.Exception.Message) }",
        "  if (Test-Path -LiteralPath $TargetOld) { Remove-Item -LiteralPath $TargetOld -Force -ErrorAction SilentlyContinue }",
        "  Write-UpdateLog 'update success; new Runtime started'",
        "  exit 0",
        "} catch {",
        "  Write-UpdateLog ('UPDATE FAILED: ' + $_.Exception.Message)",
        "  if (-not (Test-Path -LiteralPath $Target) -and (Test-Path -LiteralPath $TargetOld)) {",
        "    Move-Item -LiteralPath $TargetOld -Destination $Target -Force -ErrorAction SilentlyContinue",
        "  }",
        "  if (Test-Path -LiteralPath $Target) {",
        "    Start-Process -FilePath $Target -WorkingDirectory $TargetDir -WindowStyle Hidden -ErrorAction SilentlyContinue",
        "  }",
        "  exit 1",
        "}",
        "",
    ])
    # Windows PowerShell 5.1 needs a BOM to reliably parse non-ASCII paths.
    script_path.write_text("\r\n".join(lines), encoding="utf-8-sig")

    popen_kwargs: Dict[str, Any] = {
        "args": [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ],
        "cwd": str(target_dir),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if sys.platform == "win32":
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        )
    try:
        subprocess.Popen(**popen_kwargs)
    except OSError as exc:
        _log(f"cannot launch swap helper: {exc}")
        return {
            "ok": False,
            "errorCode": "swap_helper_launch_failed",
            "error": f"无法启动更新替换程序：{exc}",
            "logPath": str(log_path),
        }
    _log(f"swap helper launched pid={pid} script={script_path}")
    return {
        "ok": True,
        "restarting": True,
        "scriptPath": str(script_path),
        "logPath": str(log_path),
        "pid": pid,
        "hint": "Runtime 将自动重启；失败详情保存在 update_restart.log",
    }
