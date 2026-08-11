"""运行时模式：儿童媒体 + 机械臂控制。落盘 config/runtime_modes.yaml，重启可恢复。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from app.config import BASE_DIR

_RUNTIME_PATH = BASE_DIR / "config" / "runtime_modes.yaml"

DEFAULT_CHILD_MEDIA_MODE = "agent"
DEFAULT_ROBOT_CONTROL_MODE = "robot_runtime"
DEFAULT_DIALOGUE_WAKE_WORD_ENABLED = False
VALID_CHILD = ("browser", "agent")
VALID_ROBOT = ("server_osc", "child_agent", "robot_runtime")


def runtime_modes_path() -> Path:
    return _RUNTIME_PATH


def _normalize_child(mode: Any) -> str:
    m = str(mode or "").strip().lower()
    return m if m in VALID_CHILD else DEFAULT_CHILD_MEDIA_MODE


def _normalize_robot(mode: Any) -> str:
    m = str(mode or "").strip().lower()
    return m if m in VALID_ROBOT else DEFAULT_ROBOT_CONTROL_MODE


def _normalize_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in ("1", "true", "yes", "on", "enabled")


def load_runtime_modes() -> Dict[str, Any]:
    """
    优先级：runtime_modes.yaml > 环境变量 > 代码默认（agent / robot_runtime）。
    """
    import os

    child = DEFAULT_CHILD_MEDIA_MODE
    robot = DEFAULT_ROBOT_CONTROL_MODE
    wake_word_enabled = DEFAULT_DIALOGUE_WAKE_WORD_ENABLED

    env_child = os.environ.get("CHILD_MEDIA_MODE")
    env_robot = os.environ.get("ROBOT_CONTROL_MODE")
    env_wake_word = os.environ.get("DIALOGUE_WAKE_WORD_ENABLED")
    if env_child:
        child = _normalize_child(env_child)
    if env_robot:
        robot = _normalize_robot(env_robot)
    if env_wake_word is not None:
        wake_word_enabled = _normalize_bool(env_wake_word)

    path = _RUNTIME_PATH
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                if "child_media_mode" in data:
                    child = _normalize_child(data.get("child_media_mode"))
                if "robot_control_mode" in data:
                    robot = _normalize_robot(data.get("robot_control_mode"))
                if "dialogue_wake_word_enabled" in data:
                    wake_word_enabled = _normalize_bool(data.get("dialogue_wake_word_enabled"))
        except Exception:
            pass

    return {
        "child_media_mode": child,
        "robot_control_mode": robot,
        "dialogue_wake_word_enabled": wake_word_enabled,
    }


def save_runtime_modes(
    *,
    child_media_mode: Optional[str] = None,
    robot_control_mode: Optional[str] = None,
    dialogue_wake_word_enabled: Optional[bool] = None,
) -> Dict[str, Any]:
    """合并写入 yaml；返回完整配置。"""
    current = load_runtime_modes()
    if child_media_mode is not None:
        current["child_media_mode"] = _normalize_child(child_media_mode)
    if robot_control_mode is not None:
        current["robot_control_mode"] = _normalize_robot(robot_control_mode)
    if dialogue_wake_word_enabled is not None:
        current["dialogue_wake_word_enabled"] = _normalize_bool(dialogue_wake_word_enabled)

    path = _RUNTIME_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "child_media_mode": current["child_media_mode"],
        "robot_control_mode": current["robot_control_mode"],
        "dialogue_wake_word_enabled": bool(current.get("dialogue_wake_word_enabled", False)),
    }
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return payload


def apply_to_process(modes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把模式应用到进程内 Config / RobotService。"""
    modes = modes or load_runtime_modes()
    child = _normalize_child(modes.get("child_media_mode"))
    robot = _normalize_robot(modes.get("robot_control_mode"))
    wake_word_enabled = _normalize_bool(modes.get("dialogue_wake_word_enabled"))

    from app.config import Config

    Config.CHILD_MEDIA_MODE = child
    Config.DIALOGUE_WAKE_WORD_ENABLED = wake_word_enabled

    try:
        from app.robot import robot_service as rs_mod

        service = rs_mod.get_robot_service()
        service.set_control_mode(robot, persist=False)
    except Exception:
        pass

    return {
        "child_media_mode": child,
        "robot_control_mode": robot,
        "dialogue_wake_word_enabled": wake_word_enabled,
    }
