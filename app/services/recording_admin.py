"""控制台录制管理：进行中录制强制关闭 + 历史记录上锁/删除。

- 强制关闭：结束 timeline（status=aborted）+ 停止 media/analysis + 结束并移除
  runtime session，返回训练信息供调用方广播给教师端/儿童端。
- 上锁：锁状态独立存放在 .runtime/coordination/recording_locks.json，
  避免改写录制目录里的 session_meta.json（那会被回放工具当原始数据读）。
- 删除：仅允许删除已解锁的会话文件夹（整个 human_dir）。
"""

from __future__ import annotations

import json
import shutil
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.utils.logger import setup_logger

logger = setup_logger("recording_admin")

_lock = threading.RLock()

_COORDINATION_DIR = Path(".runtime") / "coordination"
_LOCK_FILE = _COORDINATION_DIR / "recording_locks.json"


def _load_locks() -> Dict[str, Any]:
    try:
        if _LOCK_FILE.is_file():
            value = json.loads(_LOCK_FILE.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
    except (OSError, ValueError) as e:
        logger.warning("读取录制锁文件失败: %s", e)
    return {}


def _save_locks(value: Dict[str, Any]) -> None:
    try:
        _COORDINATION_DIR.mkdir(parents=True, exist_ok=True)
        _LOCK_FILE.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        logger.warning("写入录制锁文件失败: %s", e)


def is_folder_locked(folder_name: str) -> bool:
    """历史会话文件夹是否已上锁（删除前必须解锁）。"""
    if not folder_name:
        return False
    with _lock:
        entry = _load_locks().get(str(folder_name)) or {}
        return bool(entry.get("locked"))


def get_locked_state() -> Dict[str, Dict[str, Any]]:
    """返回 {folder_name: {locked, lockedAt}} 全量快照，供 catalog 展示。"""
    with _lock:
        return dict(_load_locks())


def set_folder_locked(folder_name: str, locked: bool) -> Dict[str, Any]:
    """设置/解除会话文件夹的删除锁。"""
    name = str(folder_name or "").strip()
    if not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError("invalid_session_folder")
    with _lock:
        state = _load_locks()
        entry = state.get(name) or {}
        if locked:
            entry.update({
                "locked": True,
                "lockedAt": datetime.now(timezone.utc).isoformat(),
            })
        else:
            entry.update({"locked": False, "lockedAt": entry.get("lockedAt")})
        state[name] = entry
        _save_locks(state)
        logger.info("录制会话%s: folder=%s", "上锁" if locked else "解锁", name)
        return dict(state[name])


def list_active_recordings() -> List[Dict[str, Any]]:
    """进行中录制列表：session_manager 活跃会话 + timeline 注册表并集。

    返回字段：sessionId / trainingSessionId / studentId / questionId /
    humanDirName / startedAtIso。
    """
    active: List[Dict[str, Any]] = []
    from app.session import get_session_manager
    from app.services.recording_timeline import (
        get_recording_session,
        list_active_recording_sessions,
    )

    try:
        manager = get_session_manager()
        for sess in manager.list_all_sessions():
            if not sess.is_active():
                continue
            meta = sess.metadata or {}
            active.append({
                "sessionId": sess.session_id,
                "trainingSessionId": sess.training_session_id,
                "studentId": sess.student_id,
                "questionId": sess.question_id,
                "humanDirName": meta.get("human_dir_name"),
                "startedAtIso": (
                    sess.started_at.isoformat() if sess.started_at else None
                ),
            })
    except Exception as e:  # noqa: BLE001
        logger.warning("枚举 session_manager 活跃会话失败: %s", e)

    # timeline 注册表可能登记了 manager 之外的录制句柄（agent 直接开始）
    try:
        for rs in list_active_recording_sessions():
            if any(
                item.get("sessionId") == rs.media_session_id for item in active
            ):
                continue
            active.append({
                "sessionId": rs.media_session_id,
                "trainingSessionId": getattr(rs, "training_session_id", None),
                "studentId": getattr(rs, "student_id", None),
                "questionId": None,
                "humanDirName": getattr(rs, "human_dir_name", None),
                "startedAtIso": getattr(rs, "recording_started_iso", None),
            })
    except Exception as e:  # noqa: BLE001
        logger.warning("枚举 timeline 活跃录制失败: %s", e)
    return active


def force_stop_recording(session_id: str) -> Dict[str, Any]:
    """强制关闭一场进行中的录制。

    幂等：重复调用时若已不存在活跃会话则返回 ok=False（active_recording_not_found）。
    返回字段：success / sessionId / trainingSessionId / studentId /
    humanDirName / timelineStatus。
    """
    sid = str(session_id or "").strip()
    if not sid:
        return {"ok": False, "error": "session_id_required"}
    from app.session import get_session_manager
    from app.session.session_model import SessionStatus
    from app.services import get_analysis_service, get_media_service
    from app.services.recording_timeline import (
        finalize_recording_session,
        get_recording_session,
    )

    manager = get_session_manager()
    sess = manager.get_session(sid)
    timeline_rs = get_recording_session(sid)
    if sess is None and timeline_rs is None:
        return {"ok": False, "error": "active_recording_not_found"}

    training_session_id = (
        getattr(sess, "training_session_id", None)
        if sess
        else getattr(timeline_rs, "training_session_id", None)
    )
    student_id = (
        getattr(sess, "student_id", None)
        if sess
        else getattr(timeline_rs, "student_id", None)
    )
    human_dir_name = None
    if sess:
        human_dir_name = (sess.metadata or {}).get("human_dir_name")
    elif timeline_rs is not None:
        human_dir_name = getattr(timeline_rs, "human_dir_name", None)

    failures: List[str] = []

    # 1. 结束 timeline（aborted 语义：会话被外部强制终止）
    try:
        finalize_recording_session(sid, status="aborted")
        timeline_status = "aborted"
    except Exception as e:  # noqa: BLE001
        failures.append(f"finalize_timeline:{e}")
        timeline_status = "finalize_failed"

    # 2. 停止 media / analysis（与 normal finalize 相同的收尾）
    if sess is not None:
        try:
            media_service = get_media_service()
            if media_service is not None:
                media_service.stop_recording(sid)
        except Exception as e:  # noqa: BLE001
            failures.append(f"stop_media:{e}")
        try:
            analysis_service = get_analysis_service()
            if analysis_service is not None:
                analysis_service.end_session(sid)
        except Exception as e:  # noqa: BLE001
            failures.append(f"end_analysis:{e}")

    # 3. 结束并移除 runtime session（keep retryable on partial failure）
    if sess is not None:
        try:
            if sess.is_active():
                manager.end_session(sid, SessionStatus.CANCELLED)
        except Exception as e:  # noqa: BLE001
            failures.append(f"end_session:{e}")
        try:
            manager.remove_session(sid)
        except Exception as e:  # noqa: BLE001
            failures.append(f"remove_session:{e}")

    ok = not failures
    if ok:
        logger.info(
            "强制关闭录制: session=%s training=%s status=%s",
            sid, training_session_id, timeline_status,
        )
    else:
        logger.warning(
            "强制关闭录制部分失败: session=%s failures=%s",
            sid, ";".join(failures),
        )
    return {
        "ok": ok,
        "error": "recording_cleanup_partial:" + ";".join(failures) if failures else None,
        "sessionId": sid,
        "trainingSessionId": training_session_id,
        "studentId": student_id,
        "humanDirName": human_dir_name,
        "timelineStatus": timeline_status,
        "cleanupFailures": failures,
    }


def delete_session_folder(folder_name: str) -> Dict[str, Any]:
    """删除一个历史会话文件夹（已上锁的拒绝删除）。"""
    from app.storage.session_catalog import resolve_session_folder

    name = str(folder_name or "").strip()
    if is_folder_locked(name):
        return {
            "ok": False,
            "error": "recording_locked",
            "folderName": name,
        }
    try:
        folder = resolve_session_folder(name)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "folderName": name}
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc), "folderName": name}

    total = 0
    try:
        for child in folder.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            total += 1
    except OSError as exc:
        return {
            "ok": False,
            "error": "session_delete_failed",
            "detail": str(exc),
            "folderName": name,
        }
    try:
        folder.rmdir()
    except OSError as exc:
        logger.warning("删除会话目录失败: folder=%s err=%s", folder, exc)
    with _lock:
        state = _load_locks()
        state.pop(name, None)
        _save_locks(state)
    logger.info("已删除录制会话: folder=%s (%d 项)", name, total)
    return {"ok": True, "folderName": name, "removedItems": total}


__all__ = [
    "force_stop_recording",
    "list_active_recordings",
    "is_folder_locked",
    "get_locked_state",
    "set_folder_locked",
    "delete_session_folder",
]
