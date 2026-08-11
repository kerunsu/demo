"""Build and protocol version facts shared by Server and Robot Runtime APIs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional


BASE_DIR = Path(__file__).resolve().parents[1]
SERVER_PROTOCOL_VERSION = "1"
MIN_RUNTIME_PROTOCOL_VERSION = 1
MAX_RUNTIME_PROTOCOL_VERSION = 1


def _read_text(path: Path) -> Optional[str]:
    try:
        value = path.read_text(encoding="utf-8").strip()
        return value or None
    except OSError:
        return None


def _git_short_revision() -> Optional[str]:
    git_dir = BASE_DIR / ".git"
    head = _read_text(git_dir / "HEAD")
    if not head:
        return None
    if head.startswith("ref: "):
        ref = head[5:].strip()
        revision = _read_text(git_dir / ref)
        if not revision:
            packed = _read_text(git_dir / "packed-refs") or ""
            for line in packed.splitlines():
                if line and not line.startswith(("#", "^")):
                    value, _, name = line.partition(" ")
                    if name == ref:
                        revision = value
                        break
    else:
        revision = head
    return revision[:12] if revision else None


def server_build_version() -> str:
    configured = os.environ.get("EIART_SERVER_BUILD_VERSION", "").strip()
    return configured or _git_short_revision() or "development"


def frontend_build_version() -> str:
    configured = os.environ.get("EIART_FRONTEND_BUILD_VERSION", "").strip()
    if configured:
        return configured
    try:
        package = json.loads(
            (BASE_DIR / "teacher_frontend" / "package.json").read_text(encoding="utf-8")
        )
        return str(package.get("version") or "development")
    except (OSError, ValueError, TypeError):
        return "development"


def runtime_protocol_compatibility(protocol_version: Any) -> dict[str, Any]:
    raw = None if protocol_version is None else str(protocol_version).strip()
    try:
        parsed = int(raw) if raw else None
    except (TypeError, ValueError):
        parsed = None
    compatible = bool(
        parsed is not None
        and MIN_RUNTIME_PROTOCOL_VERSION <= parsed <= MAX_RUNTIME_PROTOCOL_VERSION
    )
    if compatible:
        reason = None
    elif parsed is None:
        reason = "runtime_protocol_missing"
    elif parsed < MIN_RUNTIME_PROTOCOL_VERSION:
        reason = "runtime_protocol_too_old"
    else:
        reason = "runtime_protocol_too_new"
    return {
        "protocolVersion": raw,
        "compatible": compatible,
        "compatibilityReason": reason,
        "minRuntimeProtocolVersion": str(MIN_RUNTIME_PROTOCOL_VERSION),
        "maxRuntimeProtocolVersion": str(MAX_RUNTIME_PROTOCOL_VERSION),
    }


def version_matrix(runtime: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return {
        "server": {
            "buildVersion": server_build_version(),
            "protocolVersion": SERVER_PROTOCOL_VERSION,
            "minRuntimeProtocolVersion": str(MIN_RUNTIME_PROTOCOL_VERSION),
            "maxRuntimeProtocolVersion": str(MAX_RUNTIME_PROTOCOL_VERSION),
        },
        "frontend": {"buildVersion": frontend_build_version()},
        "runtime": runtime,
    }


__all__ = [
    "MAX_RUNTIME_PROTOCOL_VERSION",
    "MIN_RUNTIME_PROTOCOL_VERSION",
    "SERVER_PROTOCOL_VERSION",
    "frontend_build_version",
    "runtime_protocol_compatibility",
    "server_build_version",
    "version_matrix",
]
