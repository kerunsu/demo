"""Reviewed, fail-closed deployment capabilities for the Demo machine.

The Demo build shares the teaching, speech, analysis, and reporting stack with
the full product, but it has no mechanical structure and does not consume the
full product's robot-expression protocol.  This checked-in fact source keeps
those differences explicit and reproducible after a fresh clone.
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
    "robotExpression": False,
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
    # This repository is the hardware-free Demo product. A copied full-product
    # file must never be able to turn robot output back on through this JSON.
    for key in ("robotMotion", "robotExpression", "robotRuntime"):
        if normalized[key]:
            raise ValueError(f"demo_forbidden_capability:{key}")
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
