"""Read-only voice-service health for the server console and child page."""
from __future__ import annotations

import importlib.util
import os
from typing import Any

import requests
from flask import Blueprint, jsonify


voice_status_bp = Blueprint("voice_status", __name__, url_prefix="/api/v2/voice")


def _service_url() -> str:
    return (os.environ.get("VOICE_PYTHON_SERVICE_URL") or "http://127.0.0.1:8765").rstrip("/")


def _dependency_status() -> dict[str, bool]:
    return {name: importlib.util.find_spec(name) is not None for name in ("torch", "funasr", "modelscope")}


@voice_status_bp.route("/health", methods=["GET"])
def voice_health():
    url = _service_url()
    dependencies = _dependency_status()
    try:
        response = requests.get(f"{url}/health", timeout=1.5)
        payload: dict[str, Any] = response.json() if response.content else {}
        provider_status = payload.get("sttProviderStatus") or payload.get("providerStatus")
        ready = response.ok and provider_status in {"READY", "DEGRADED"}
        return jsonify({
            "success": True,
            "reachable": True,
            "ready": ready,
            "serviceUrl": url,
            "dependencies": dependencies,
            "health": payload,
            "error": None if ready else (
                payload.get("sttError") or payload.get("error") or
                f"STT 状态为 {provider_status or 'unknown'}"
            ),
        })
    except Exception as exc:
        return jsonify({
            "success": True,
            "reachable": False,
            "ready": False,
            "serviceUrl": url,
            "dependencies": dependencies,
            "health": None,
            "error": f"voice-service 不可达: {exc}",
        })

