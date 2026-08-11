"""InteractionProfileV2 控制面和只读试解析入口。"""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from flask import Blueprint, jsonify, request

from app.computation.interaction import EventDefinition, get_event_catalog, validate_profile
from app.config import Config
from app.contracts.models import InteractionContext
from app.robot import get_robot_service
from app.robot.config import ROBOT_DATA_DIR
from app.storage.repositories.interaction_profile_store import JsonInteractionProfileStore
from app.storage.repositories.asset_index import JsonAssetIndex
from app.robot.motion_storage import load_motions
from app.storage.session_layout import atomic_write_json


interaction_profiles_bp = Blueprint("interaction_profiles", __name__, url_prefix="/api/v2/interaction")
_store = JsonInteractionProfileStore(Path(ROBOT_DATA_DIR) / "interaction_profiles.json")
_event_catalog = get_event_catalog()
_event_file = Path(ROBOT_DATA_DIR) / "event_catalog.json"
if _event_file.exists():
    try:
        raw_events = json.loads(_event_file.read_text(encoding="utf-8"))
        for raw in raw_events.get("events", []) if isinstance(raw_events, dict) else []:
            if isinstance(raw, dict):
                _event_catalog.register(EventDefinition(**raw))
    except Exception:
        # A malformed optional extension must not prevent the legacy app from booting.
        pass


def _context(payload: dict) -> InteractionContext:
    return InteractionContext(
        course_id=str(payload.get("courseId") or payload.get("course_id") or "") or None,
        course_type=payload.get("courseType") or payload.get("course_type"),
        item_id=str(payload.get("itemId") or payload.get("item_id") or "") or None,
        question_id=str(payload.get("questionId") or payload.get("question_id") or "") or None,
        event_key=payload.get("eventKey") or payload.get("event_key"),
        scene_key=payload.get("sceneKey") or payload.get("scene_key"),
        line_id=payload.get("lineId") or payload.get("line_id"),
        student_id=str(payload.get("studentId") or payload.get("student_id") or "") or None,
        profile_version=payload.get("profileVersion") or payload.get("profile_version"),
        behavior_id=payload.get("behaviorId") or payload.get("behavior_id"),
        request_id=payload.get("requestId") or payload.get("request_id"),
        current_state=payload.get("currentState") or payload.get("current_state"),
        capabilities=dict(payload.get("capabilities") or {}),
    )


def _json_profile(profile):
    return profile


def _asset_exists(field: str, asset_id: str) -> bool:
    """Check logical V2 assets while retaining bare legacy media names."""
    if field == "speech":
        kind = "audio"
    else:
        kind = "motion" if field in {"motions", "motionAssets"} else "emotion"
    index = JsonAssetIndex(Path(ROBOT_DATA_DIR) / "asset_index.json")
    if index.get(asset_id, kind=kind) is not None:
        return True
    # Existing profiles use physical legacy names. Their old libraries remain
    # authoritative until a logical AssetRef is supplied by the control API.
    if kind == "motion":
        try:
            return asset_id in (load_motions() or {})
        except Exception:
            return False
    root = Path(Config.STATIC_DIR) / "resources" / "Emotions"
    return (root / asset_id).exists() or (root / f"{asset_id}.gif").exists()


@interaction_profiles_bp.route("/events", methods=["GET"])
def list_interaction_events():
    return jsonify({"success": True, "events": [asdict(event) for event in _event_catalog.list()]})


@interaction_profiles_bp.route("/events", methods=["POST"])
def register_interaction_event():
    payload = request.get_json(silent=True) or {}
    try:
        event = EventDefinition(
            key=str(payload.get("key") or "").strip(),
            label=str(payload.get("label") or "").strip(),
            kind=str(payload.get("kind") or "instant"),
            duration_ms=payload.get("durationMs"),
            interruptible=bool(payload.get("interruptible", True)),
            priority=int(payload.get("priority", 0)),
            return_to_idle=bool(payload.get("returnToIdle", True)),
            allowed_from=tuple(payload.get("allowedFrom") or payload.get("allowed_from") or ()),
        )
        _event_catalog.register(event)
        custom = [asdict(item) for item in _event_catalog.list() if item.key not in {"idle", "sleepy", "praise", "hint", "call_child", "retry", "greeting", "greeting_response", "farewell", "farewell_response", "question.naming", "question.vocal_imitation", "question.ordering", "question.pairing", "calm_speech.2s", "calm_speech.3s"}]
        atomic_write_json(_event_file, {"schemaVersion": 1, "events": custom})
        return jsonify({"success": True, "event": asdict(event)})
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@interaction_profiles_bp.route("/profiles/<course_id>", methods=["GET"])
def get_interaction_profile(course_id: str):
    profile = _store.get(course_id, request.args.get("version"))
    if profile is None:
        return jsonify({"success": False, "error": "interaction_profile_not_found"}), 404
    return jsonify({"success": True, "profile": _json_profile(profile)})


@interaction_profiles_bp.route("/profiles/<course_id>/draft", methods=["PUT"])
def save_interaction_draft(course_id: str):
    payload = request.get_json(silent=True) or {}
    payload["courseId"] = course_id
    try:
        profile = _store.save_draft(payload)
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "profile": profile})


@interaction_profiles_bp.route("/profiles/<course_id>/publish", methods=["POST"])
def publish_interaction_profile(course_id: str):
    payload = request.get_json(silent=True) or {}
    version = payload.get("version")
    if not version:
        return jsonify({"success": False, "error": "version_required"}), 400
    try:
        candidate = _store.get(course_id, str(version))
        if candidate is None:
            raise KeyError("interaction_profile_not_found")
        errors = validate_profile(candidate, _event_catalog, asset_exists=_asset_exists)
        if errors:
            return jsonify({"success": False, "error": "interaction_profile_invalid", "details": list(errors)}), 400
        profile = _store.publish(course_id, str(version))
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    return jsonify({"success": True, "profile": profile})


@interaction_profiles_bp.route("/profiles/<course_id>/deploy", methods=["POST"])
def deploy_interaction_profile(course_id: str):
    payload = request.get_json(silent=True) or {}
    version = payload.get("version")
    stage = payload.get("stage") or payload.get("deploymentStage")
    if not version or not stage:
        return jsonify({"success": False, "error": "version_and_stage_required"}), 400
    try:
        candidate = _store.get(course_id, str(version))
        if candidate is None:
            raise KeyError("interaction_profile_not_found")
        errors = validate_profile(candidate, _event_catalog, asset_exists=_asset_exists)
        if errors:
            return jsonify({"success": False, "error": "interaction_profile_invalid", "details": list(errors)}), 400
        profile = _store.deploy(
            course_id,
            str(version),
            str(stage),
            payload.get("canaryPercent", payload.get("canary_percent", 0)),
        )
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    return jsonify({"success": True, "profile": profile})


@interaction_profiles_bp.route("/profiles/<course_id>/rollback", methods=["POST"])
def rollback_interaction_profile(course_id: str):
    payload = request.get_json(silent=True) or {}
    version = payload.get("version")
    if not version:
        return jsonify({"success": False, "error": "version_required"}), 400
    try:
        profile = _store.rollback(course_id, str(version))
    except KeyError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    return jsonify({"success": True, "profile": profile})


@interaction_profiles_bp.route("/resolve", methods=["POST"])
def resolve_interaction_preview():
    payload = request.get_json(silent=True) or {}
    context_payload = payload.get("context") if isinstance(payload.get("context"), dict) else payload
    try:
        runtime_payload = dict(context_payload)
        runtime_payload["aux"] = payload.get("aux") or {}
        plan = get_robot_service().resolve_interaction_plan(
            runtime_payload,
            store=_store,
            catalog=_event_catalog,
        )
        if plan is None:
            return jsonify({"success": False, "error": "interaction_resolver_unavailable"}), 503
        return jsonify({"success": True, "plan": asdict(plan)})
    except (AttributeError, KeyError, TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


__all__ = ["interaction_profiles_bp"]
