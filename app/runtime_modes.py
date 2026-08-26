"""运行时模式：儿童媒体 + 机械臂控制。落盘 config/runtime_modes.yaml，重启可恢复。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional
import os
import tempfile

import yaml

from app.config import BASE_DIR

_RUNTIME_PATH = BASE_DIR / "config" / "runtime_modes.yaml"

DEFAULT_CHILD_MEDIA_MODE = "agent"
DEFAULT_ROBOT_CONTROL_MODE = "robot_runtime"
DEFAULT_DIALOGUE_WAKE_WORD_ENABLED = False
DEFAULT_BROWSER_SPEECH_RATE = 0.88
MIN_BROWSER_SPEECH_RATE = 0.5
MAX_BROWSER_SPEECH_RATE = 2.0
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


def normalize_browser_speech_rate(value: Any, *, strict: bool = False) -> float:
    try:
        rate = float(value)
    except (TypeError, ValueError):
        if strict:
            raise ValueError("语速必须是 0.5 到 2.0 之间的数字")
        return DEFAULT_BROWSER_SPEECH_RATE
    if not MIN_BROWSER_SPEECH_RATE <= rate <= MAX_BROWSER_SPEECH_RATE:
        if strict:
            raise ValueError("语速必须在 0.5 到 2.0 之间")
        return DEFAULT_BROWSER_SPEECH_RATE
    return round(rate, 2)


def load_runtime_modes() -> Dict[str, Any]:
    """
    优先级：runtime_modes.yaml > 环境变量 > 代码默认（agent / robot_runtime）。
    """
    child = DEFAULT_CHILD_MEDIA_MODE
    robot = DEFAULT_ROBOT_CONTROL_MODE
    wake_word_enabled = DEFAULT_DIALOGUE_WAKE_WORD_ENABLED
    browser_speech_rate = DEFAULT_BROWSER_SPEECH_RATE

    env_child = os.environ.get("CHILD_MEDIA_MODE")
    env_robot = os.environ.get("ROBOT_CONTROL_MODE")
    env_wake_word = os.environ.get("DIALOGUE_WAKE_WORD_ENABLED")
    env_speech_rate = os.environ.get("BROWSER_SPEECH_RATE")
    if env_child:
        child = _normalize_child(env_child)
    if env_robot:
        robot = _normalize_robot(env_robot)
    if env_wake_word is not None:
        wake_word_enabled = _normalize_bool(env_wake_word)
    if env_speech_rate is not None:
        browser_speech_rate = normalize_browser_speech_rate(env_speech_rate)

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
                if "browser_speech_rate" in data:
                    browser_speech_rate = normalize_browser_speech_rate(data.get("browser_speech_rate"))
        except Exception:
            pass

    return {
        "child_media_mode": child,
        "robot_control_mode": robot,
        "dialogue_wake_word_enabled": wake_word_enabled,
        "browser_speech_rate": browser_speech_rate,
    }


def save_runtime_modes(
    *,
    child_media_mode: Optional[str] = None,
    robot_control_mode: Optional[str] = None,
    dialogue_wake_word_enabled: Optional[bool] = None,
    browser_speech_rate: Optional[float] = None,
) -> Dict[str, Any]:
    """合并写入 yaml；返回完整配置。"""
    current = load_runtime_modes()
    if child_media_mode is not None:
        current["child_media_mode"] = _normalize_child(child_media_mode)
    if robot_control_mode is not None:
        current["robot_control_mode"] = _normalize_robot(robot_control_mode)
    if dialogue_wake_word_enabled is not None:
        current["dialogue_wake_word_enabled"] = _normalize_bool(dialogue_wake_word_enabled)
    if browser_speech_rate is not None:
        current["browser_speech_rate"] = normalize_browser_speech_rate(
            browser_speech_rate,
            strict=True,
        )

    path = _RUNTIME_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "child_media_mode": current["child_media_mode"],
        "robot_control_mode": current["robot_control_mode"],
        "dialogue_wake_word_enabled": bool(current.get("dialogue_wake_word_enabled", False)),
        "browser_speech_rate": normalize_browser_speech_rate(current.get("browser_speech_rate")),
    }
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise
    return payload


def apply_to_process(modes: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """把模式应用到进程内 Config / RobotService。"""
    modes = modes or load_runtime_modes()
    child = _normalize_child(modes.get("child_media_mode"))
    robot = _normalize_robot(modes.get("robot_control_mode"))
    wake_word_enabled = _normalize_bool(modes.get("dialogue_wake_word_enabled"))
    browser_speech_rate = normalize_browser_speech_rate(modes.get("browser_speech_rate"))

    from app.config import Config

    Config.CHILD_MEDIA_MODE = child
    Config.DIALOGUE_WAKE_WORD_ENABLED = wake_word_enabled
    Config.BROWSER_SPEECH_RATE = browser_speech_rate

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
        "browser_speech_rate": browser_speech_rate,
    }
