"""Reviewed deployment capabilities for the Demo machine.

The Demo build has no mechanical structure: motion output and Robot Runtime
must remain disabled.  Its browser-based expression display is an independent
screen capability and intentionally stays enabled.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


CAPABILITIES_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "demo_deployment.json"
)

SAFE_DEFAULT_CAPABILITIES = {
    "robotMotion": False,
    "robotExpression": True,
    "robotRuntime": False,
    "childAnimation": True,
    "browserSpeech": True,
}


def _normalize_capabilities(value: Any) -> dict[str, bool]:
    if not isinstance(value, Mapping):
        raise ValueError("demo_capabilities_must_be_an_object")
    normalized: dict[str, bool] = {}
    for key, safe_default in SAFE_DEFAULT_CAPABILITIES.items():
        raw = value.get(key, safe_default)
        if not isinstance(raw, bool):
            raise ValueError(f"demo_capability_must_be_boolean:{key}")
        normalized[key] = raw
    # A copied full-product file must never turn mechanical output or Robot
    # Runtime back on. Screen expressions are reviewed and allowed.
    for key in ("robotMotion", "robotRuntime"):
        if normalized[key]:
            raise ValueError(f"demo_forbidden_capability:{key}")
    if not normalized["robotExpression"]:
        raise ValueError("demo_required_capability:robotExpression")
    return normalized


def load_demo_capabilities(path: Path | None = None) -> dict[str, Any]:
    """Load reviewed capabilities; invalid/missing files fail closed."""
    source = Path(path) if path is not None else CAPABILITIES_PATH
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("schemaVersion") != 1:
            raise ValueError("unsupported_demo_deployment_schema")
        if raw.get("deployment") != "demo-machine":
            raise ValueError("invalid_demo_deployment")
        capabilities = _normalize_capabilities(raw.get("capabilities"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        capabilities = dict(SAFE_DEFAULT_CAPABILITIES)
    return {
        "schemaVersion": 1,
        "deployment": "demo-machine",
        "capabilities": capabilities,
    }


def capability_enabled(name: str, path: Path | None = None) -> bool:
    return bool(load_demo_capabilities(path)["capabilities"].get(name, False))


def robot_motion_enabled() -> bool:
    return capability_enabled("robotMotion")


def robot_expression_enabled() -> bool:
    return capability_enabled("robotExpression")


def robot_runtime_enabled() -> bool:
    return capability_enabled("robotRuntime")


def child_animation_enabled() -> bool:
    return capability_enabled("childAnimation")


__all__ = [
    "CAPABILITIES_PATH",
    "SAFE_DEFAULT_CAPABILITIES",
    "capability_enabled",
    "child_animation_enabled",
    "load_demo_capabilities",
    "robot_expression_enabled",
    "robot_motion_enabled",
    "robot_runtime_enabled",
]
