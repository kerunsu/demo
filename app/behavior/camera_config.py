"""摄像头分析配置加载 / 保存"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.config import BASE_DIR

_DEFAULT = {
    "enabled": True,
    "fps": 1,
    "width": 160,
    "height": 120,
    "prefer_browser_for_report": False,
    "prefer_browser_when_media_mode_browser": True,
    "attention_incomplete_factor": 0.7,
    "emotion_min_samples": 2,
}

_CAMERA_PATH = BASE_DIR / "config" / "camera_analysis.yaml"


def camera_config_path() -> Path:
    return _CAMERA_PATH


def load_camera_analysis_config() -> Dict[str, Any]:
    path = _CAMERA_PATH
    cfg = dict(_DEFAULT)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if isinstance(data, dict):
                cfg.update(data)
        except Exception:
            pass
    return cfg


def validate_camera_analysis_config(cfg: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if "enabled" in cfg and not isinstance(cfg["enabled"], bool):
        errors.append("enabled 必须为布尔值")
    for key in ("fps", "width", "height", "emotion_min_samples"):
        if key in cfg:
            try:
                v = float(cfg[key])
                if v <= 0:
                    errors.append(f"{key} 必须 > 0")
            except (TypeError, ValueError):
                errors.append(f"{key} 必须为数字")
    if "attention_incomplete_factor" in cfg:
        try:
            v = float(cfg["attention_incomplete_factor"])
            if v < 0 or v > 1:
                errors.append("attention_incomplete_factor 须在 0–1")
        except (TypeError, ValueError):
            errors.append("attention_incomplete_factor 必须为数字")
    for key in ("prefer_browser_for_report", "prefer_browser_when_media_mode_browser"):
        if key in cfg and not isinstance(cfg[key], bool):
            errors.append(f"{key} 必须为布尔值")
    return errors


def save_camera_analysis_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """校验后写盘；先备份 .bak。返回合并默认后的完整配置。"""
    merged = dict(_DEFAULT)
    merged.update({k: cfg[k] for k in _DEFAULT if k in cfg})
    merged["enabled"] = bool(merged["enabled"])
    merged["fps"] = int(merged["fps"])
    merged["width"] = int(merged["width"])
    merged["height"] = int(merged["height"])
    merged["prefer_browser_for_report"] = bool(merged["prefer_browser_for_report"])
    merged["prefer_browser_when_media_mode_browser"] = bool(
        merged["prefer_browser_when_media_mode_browser"]
    )
    merged["attention_incomplete_factor"] = float(merged["attention_incomplete_factor"])
    merged["emotion_min_samples"] = int(merged["emotion_min_samples"])

    errors = validate_camera_analysis_config(merged)
    if errors:
        raise ValueError("；".join(errors))

    path = _CAMERA_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(merged, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
    return merged


def should_prefer_browser_for_report(cfg: Optional[Dict[str, Any]] = None) -> bool:
    """
    是否优先浏览器注意力/情绪样本。

    - 全局 prefer_browser_for_report=true：始终优先（旧行为，不推荐生产）
    - 否则仅当 CHILD_MEDIA_MODE=browser 且 prefer_browser_when_media_mode_browser=true
    - agent（robot_runtime）生产路径：返回 False，使用服务端观测
    """
    cam = cfg if cfg is not None else load_camera_analysis_config()
    if bool(cam.get("prefer_browser_for_report", False)):
        return True
    if not bool(cam.get("prefer_browser_when_media_mode_browser", True)):
        return False
    try:
        from app.config import Config
        return Config.get_child_media_mode() == "browser"
    except Exception:
        return False


def should_run_browser_camera_analysis(cfg: Optional[Dict[str, Any]] = None) -> bool:
    """儿童页是否应启动 C2 浏览器摄像头分析（仅 browser 采流模式）。"""
    cam = cfg if cfg is not None else load_camera_analysis_config()
    if not bool(cam.get("enabled", True)):
        return False
    try:
        from app.config import Config
        return Config.get_child_media_mode() == "browser"
    except Exception:
        return True
