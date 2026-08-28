"""Hardware-free Demo course-output and screen-expression routes.

The ``/api/robot`` prefix is retained for compatibility with existing child
and teacher clients. It exposes the browser expression screen but never robot
motion or Robot Runtime.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.deployment_capabilities import load_demo_capabilities
from app.robot import get_robot_service
from app.utils.logger import setup_logger


logger = setup_logger("demo_output_routes")
robot_bp = Blueprint("robot", __name__, url_prefix="/api/robot")


EXPRESSION_AUX_TYPES = frozenset({
    "attention", "reward", "praise", "question", "hint", "silent",
})
MECHANICAL_FIELDS = frozenset({"motion", "motions", "motionOffsetMs"})


def _disabled_response(path: str):
    return jsonify({
        "success": False,
        "error": "demo_capability_disabled",
        "capability": "robotMotionOrRuntime",
    }), 410


def _binding_payload():
    """Validate one expression-only binding update from the config center."""
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        raise ValueError("JSON object required")
    mechanical = [
        key for key in MECHANICAL_FIELDS
        if key in data and data.get(key) not in (None, "", [])
    ]
    sequence = data.get("sequence") if isinstance(data.get("sequence"), dict) else {}
    if sequence.get("motionOffsetMs") not in (None, "", 0, "0"):
        mechanical.append("sequence.motionOffsetMs")
    if mechanical:
        raise ValueError("mechanical motion is disabled in Demo")
    emotions = data.get("emotions", [])
    if not isinstance(emotions, list):
        raise ValueError("emotions must be an array")
    animations = data.get("animations", [])
    if not isinstance(animations, list):
        raise ValueError("animations must be an array")
    audio = sequence.get("audio") if isinstance(sequence.get("audio"), dict) else {}
    return {
        "emotion": str(data.get("emotion") or "").strip(),
        "emotions": emotions,
        "animation": str(data.get("animation") or "").strip(),
        "animations": animations,
        "sequence": {
            "expressionMediaId": str(sequence.get("expressionMediaId") or "").strip(),
            "expressionDurationMs": _nonnegative_int(sequence.get("expressionDurationMs")),
            "audio": {"offsetMs": _nonnegative_int(audio.get("offsetMs"))},
        },
    }


def _validate_expression_aux(aux_type: str) -> str:
    value = str(aux_type or "").strip()
    if value not in EXPRESSION_AUX_TYPES:
        raise ValueError("invalid_expression_event")
    return value


def _nonnegative_int(value) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _public_binding(value):
    """Project a legacy action object onto the Demo expression schema."""
    raw = value if isinstance(value, dict) else {}
    sequence = raw.get("sequence") if isinstance(raw.get("sequence"), dict) else {}
    audio = sequence.get("audio") if isinstance(sequence.get("audio"), dict) else {}
    result = {
        "emotion": str(raw.get("emotion") or "").strip(),
        "animation": str(raw.get("animation") or "").strip(),
        "sequence": {
            "expressionMediaId": str(sequence.get("expressionMediaId") or "").strip(),
            "expressionDurationMs": _nonnegative_int(sequence.get("expressionDurationMs")),
            "audio": {"offsetMs": _nonnegative_int(audio.get("offsetMs"))},
        },
    }
    emotions = raw.get("emotions")
    if isinstance(emotions, list):
        result["emotions"] = [str(item).strip() for item in emotions if str(item).strip()]
    animations = raw.get("animations")
    if isinstance(animations, list):
        result["animations"] = [str(item).strip() for item in animations if str(item).strip()]
    return result


def _public_expression_mapping(value, active_course_ids=None):
    raw = value if isinstance(value, dict) else {}
    result = {
        "schemaVersion": raw.get("schemaVersion", 1),
        "deployment": "demo-machine",
        "defaults": {},
        "courses": {},
        "students": {},
    }
    defaults = raw.get("defaults") if isinstance(raw.get("defaults"), dict) else {}
    for aux_type, binding in defaults.items():
        if aux_type in EXPRESSION_AUX_TYPES or aux_type == "dialogue_wake_ack":
            result["defaults"][aux_type] = _public_binding(binding)
    courses = raw.get("courses") if isinstance(raw.get("courses"), dict) else {}
    for course_id, course_data in courses.items():
        if active_course_ids is not None and str(course_id) not in active_course_ids:
            continue
        if not isinstance(course_data, dict):
            continue
        target = {}
        for aux_type, binding in course_data.items():
            if aux_type in EXPRESSION_AUX_TYPES:
                target[aux_type] = _public_binding(binding)
        items = course_data.get("items") if isinstance(course_data.get("items"), dict) else {}
        public_items = {}
        for item_id, item_data in items.items():
            if not isinstance(item_data, dict):
                continue
            public_item = {
                aux_type: _public_binding(binding)
                for aux_type, binding in item_data.items()
                if aux_type in EXPRESSION_AUX_TYPES
            }
            if public_item:
                public_items[str(item_id)] = public_item
        if public_items:
            target["items"] = public_items
        if target:
            result["courses"][str(course_id)] = target
    return result


def _active_course(course_id: int):
    """Resolve one course only when it belongs to the reviewed Demo scope."""
    from app.course_scope import filter_course_payloads
    from database.models import Course

    course = Course.query.get(int(course_id))
    if course is None or not filter_course_payloads([course.to_dict()]):
        raise LookupError("demo_course_not_found")
    return course


def _active_course_ids():
    from app.course_scope import filter_course_payloads
    from database.models import Course

    return {
        str(item["id"])
        for item in filter_course_payloads(
            [course.to_dict() for course in Course.query.order_by(Course.id).all()]
        )
    }


def _active_course_item(course_id: int, item_id: int):
    from database.models import CourseItem

    _active_course(course_id)
    item = CourseItem.query.get(int(item_id))
    if item is None or int(item.course_id) != int(course_id):
        raise LookupError("demo_course_item_not_found")
    return item


@robot_bp.route("/course-event", methods=["POST"])
def trigger_course_event():
    """Coordinate audio/TTS, screen expressions and child-screen animation."""
    data = request.get_json(silent=True) or {}
    if not data.get("courseId"):
        return jsonify({"success": False, "error": "courseId required"}), 400

    sanitized = dict(data)
    for key in ("motion", "motions", "emotion", "expression", "expressionMediaId"):
        sanitized.pop(key, None)
    try:
        result = get_robot_service().trigger_course_event(sanitized)
        return jsonify(result), 200 if result.get("success") else 404
    except Exception as exc:
        logger.error("Demo course output failed: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/sequence/status/<command_id>", methods=["GET"])
def course_output_status(command_id: str):
    """Return lifecycle state for an accepted audio/child-animation plan."""
    try:
        status = get_robot_service().get_command_status(command_id)
        if status is None:
            return jsonify({
                "success": False,
                "error": "command_not_found",
                "commandId": command_id,
            }), 404
        return jsonify({"success": True, "status": status})
    except Exception as exc:
        logger.error("Failed to read Demo output status: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/control/status", methods=["GET"])
def course_output_control_status():
    """Expose reviewed Demo capabilities without hardware transport details."""
    return jsonify({
        "success": True,
        "control": {
            "mode": "screen-expression-only",
            "motionMode": "disabled",
            "expressionMode": "browser-screen",
            **load_demo_capabilities()["capabilities"],
        },
    })


@robot_bp.route("/students", methods=["GET"])
def get_students():
    """Compatibility catalog backed by the active SQLite database."""
    try:
        from database.models import Student

        students = [item.to_dict() for item in Student.query.order_by(Student.created_at.desc()).all()]
        return jsonify({"success": True, "students": students})
    except Exception as exc:
        logger.error("Failed to read students: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/courses", methods=["GET"])
def get_courses():
    """Compatibility catalog filtered to the two Demo course types."""
    try:
        from app.course_scope import filter_course_payloads
        from database.models import Course

        courses = filter_course_payloads(
            [item.to_dict() for item in Course.query.order_by(Course.id).all()]
        )
        return jsonify({"success": True, "courses": courses})
    except Exception as exc:
        logger.error("Failed to read Demo courses: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ========== Expression-only course binding API ==========

@robot_bp.route("/mapping/full", methods=["GET"])
def get_expression_mapping():
    """Return the reviewed expression/child-animation map without hardware data."""
    try:
        mapping = _public_expression_mapping(
            get_robot_service().get_full_mapping(),
            active_course_ids=_active_course_ids(),
        )
        return jsonify({"success": True, "mapping": mapping})
    except Exception as exc:
        logger.error("Failed to read expression mapping: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/mapping/defaults/<aux_type>", methods=["PUT", "DELETE"])
def default_expression_mapping(aux_type: str):
    try:
        aux_type = _validate_expression_aux(aux_type)
        service = get_robot_service()
        if request.method == "DELETE":
            service.delete_default_motions(aux_type)
            return jsonify({"success": True, "deleted": aux_type})
        binding = _binding_payload()
        service.update_default_motions(
            aux_type, [], binding["emotion"], binding["sequence"],
            binding["animation"], binding["emotions"], binding["animations"],
        )
        return jsonify({"success": True, "auxType": aux_type, **binding})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to update default expression mapping: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route(
    "/mapping/course/<int:course_id>/<aux_type>",
    methods=["PUT", "DELETE"],
)
def course_expression_mapping(course_id: int, aux_type: str):
    try:
        _active_course(course_id)
        aux_type = _validate_expression_aux(aux_type)
        service = get_robot_service()
        if request.method == "DELETE":
            service.delete_course_motions(course_id, aux_type)
            return jsonify({"success": True, "deleted": aux_type})
        binding = _binding_payload()
        service.update_course_motions(
            course_id, aux_type, [], binding["emotion"], binding["sequence"],
            binding["animation"], binding["emotions"], binding["animations"],
        )
        return jsonify({
            "success": True,
            "courseId": course_id,
            "auxType": aux_type,
            **binding,
        })
    except LookupError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to update course expression mapping: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route(
    "/mapping/course/<int:course_id>/item/<int:item_id>/<aux_type>",
    methods=["PUT", "DELETE"],
)
def course_item_expression_mapping(course_id: int, item_id: int, aux_type: str):
    try:
        _active_course_item(course_id, item_id)
        aux_type = _validate_expression_aux(aux_type)
        service = get_robot_service()
        if request.method == "DELETE":
            service.delete_course_item_motions(course_id, item_id, aux_type)
            return jsonify({"success": True, "deleted": aux_type})
        binding = _binding_payload()
        service.update_course_item_motions(
            course_id, item_id, aux_type, [], binding["emotion"],
            binding["sequence"], binding["animation"], binding["emotions"],
            binding["animations"],
        )
        return jsonify({
            "success": True,
            "courseId": course_id,
            "itemId": item_id,
            "auxType": aux_type,
            **binding,
        })
    except LookupError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to update course-item expression mapping: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/sequence/preview", methods=["POST"])
def preview_expression_binding():
    """Preview one expression sequence while rejecting every motion field."""
    try:
        binding = _binding_payload()
        data = request.get_json(silent=True) or {}
        result = get_robot_service().preview_behavior_sequence({
            **binding,
            "motions": [],
            "auxType": _validate_expression_aux(data.get("auxType")),
            "courseId": data.get("courseId"),
            "itemId": data.get("itemId"),
        })
        result.pop("motion", None)
        actual_plan = result.get("actualPlan")
        if isinstance(actual_plan, dict):
            actual_plan.pop("motion", None)
            actual_plan.pop("motionOffsetMs", None)
        return jsonify(result), 200 if result.get("success") else 409
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to preview expression binding: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


# ========== Browser expression display API (no mechanical output) ==========

@robot_bp.route("/emotions", methods=["GET"])
def get_emotions():
    try:
        return jsonify({"success": True, **get_robot_service().get_emotions_payload()})
    except Exception as exc:
        logger.error("Failed to list screen expressions: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/emotions/default", methods=["GET", "PUT"])
def default_emotion():
    try:
        service = get_robot_service()
        if request.method == "GET":
            return jsonify({"success": True, "emotion": service.get_default_emotion()})
        data = request.get_json(silent=True) or {}
        emotion = data.get("emotion")
        if not emotion:
            return jsonify({"success": False, "error": "emotion required"}), 400
        return jsonify({"success": True, "emotion": service.set_default_emotion(emotion)})
    except FileNotFoundError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to read or update default expression: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/emotions/global-filter", methods=["GET", "PUT"])
def emotion_global_filter():
    try:
        service = get_robot_service()
        if request.method == "GET":
            return jsonify({"success": True, "globalFilter": service.get_global_emotion_filter()})
        result = service.set_global_emotion_filter(request.get_json(silent=True))
        service.trigger_emotion(
            service.get_default_emotion(), settingsOnly=True, globalFilter=result
        )
        return jsonify({"success": True, "globalFilter": result})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to update expression global filter: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/emotions/idle-pool", methods=["GET", "PUT"])
def emotion_idle_pool():
    try:
        service = get_robot_service()
        if request.method == "GET":
            return jsonify({"success": True, "emotions": service.get_idle_emotions()})
        data = request.get_json(silent=True) or {}
        emotions = service.set_idle_emotions(data.get("emotions"))
        return jsonify({"success": True, "emotions": emotions, "default": emotions[0]})
    except FileNotFoundError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to update idle expression pool: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/emotions/dialogue-reply-rules", methods=["GET", "PUT"])
def dialogue_reply_expression_rules():
    try:
        service = get_robot_service()
        if request.method == "GET":
            return jsonify({"success": True, "config": service.get_dialogue_reply_expressions()})
        config = service.set_dialogue_reply_expressions(request.get_json(silent=True) or {})
        return jsonify({"success": True, "config": config})
    except FileNotFoundError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to update dialogue expression rules: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/emotions/<name>/style", methods=["GET", "PUT"])
def emotion_style(name: str):
    try:
        service = get_robot_service()
        if name not in service.get_available_emotions():
            return jsonify({"success": False, "error": "Emotion not found"}), 404
        if request.method == "GET":
            return jsonify({"success": True, "style": service.get_emotion_style(name)})
        result = service.set_emotion_style(name, request.get_json(silent=True))
        service.trigger_emotion(name, settingsOnly=True, style=result)
        return jsonify({"success": True, "style": result})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to update expression style: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/emotions/upload", methods=["POST"])
def upload_emotion():
    try:
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return jsonify({"success": False, "error": "file required"}), 400
        result = get_robot_service().upload_emotion(upload.filename, upload.read())
        return jsonify({
            "success": True,
            "emotion": result["name"],
            "optimization": result,
        }), 201
    except FileExistsError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to upload screen expression: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/emotions/<name>", methods=["DELETE"])
def delete_emotion(name: str):
    try:
        force = request.args.get("force", "").lower() in ("1", "true", "yes")
        if request.is_json:
            force = force or bool((request.get_json(silent=True) or {}).get("force"))
        get_robot_service().delete_emotion(name, force=force)
        return jsonify({"success": True, "deleted": name})
    except PermissionError as exc:
        from app.robot.emotion_assets import find_emotion_references

        return jsonify({
            "success": False,
            "error": str(exc),
            "referencedBy": find_emotion_references(name),
            "hint": "加 ?force=1 强制删除",
        }), 409
    except FileNotFoundError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to delete screen expression: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/emotions/trigger", methods=["POST"])
def trigger_emotion():
    try:
        emotion = (request.get_json(silent=True) or {}).get("emotion")
        if not emotion:
            return jsonify({"success": False, "error": "emotion required"}), 400
        if get_robot_service().trigger_emotion(emotion):
            return jsonify({"success": True, "message": f'Emotion "{emotion}" triggered'})
        return jsonify({"success": False, "error": "Failed to trigger emotion"}), 500
    except Exception as exc:
        logger.error("Failed to trigger screen expression: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/animations", methods=["GET"])
def get_animations():
    """List child-screen encouragement animations (not robot expressions)."""
    try:
        return jsonify({"success": True, **get_robot_service().get_animations_payload()})
    except Exception as exc:
        logger.error("Failed to list child-screen animations: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/animations/upload", methods=["POST"])
def upload_animation():
    try:
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return jsonify({"success": False, "error": "file required"}), 400
        result = get_robot_service().upload_animation(upload.filename, upload.read())
        return jsonify({
            "success": True,
            "animation": result["name"],
            "optimization": result,
        }), 201
    except FileExistsError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to upload child-screen animation: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/animations/<path:name>/rename", methods=["PUT"])
def rename_animation(name: str):
    try:
        data = request.get_json(silent=True) or {}
        new_name = data.get("newName")
        if not isinstance(new_name, str) or not new_name.strip():
            return jsonify({"success": False, "error": "newName required"}), 400
        result = get_robot_service().rename_animation(name, new_name)
        return jsonify({"success": True, **result})
    except FileExistsError as exc:
        return jsonify({"success": False, "error": str(exc)}), 409
    except FileNotFoundError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to rename child-screen animation: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/animations/<path:name>", methods=["DELETE"])
def delete_animation(name: str):
    try:
        force = request.args.get("force", "").lower() in ("1", "true", "yes")
        get_robot_service().delete_animation(name, force=force)
        return jsonify({"success": True, "deleted": name})
    except PermissionError as exc:
        from app.robot.animation_assets import find_animation_references

        return jsonify({
            "success": False,
            "error": str(exc),
            "referencedBy": find_animation_references(name),
        }), 409
    except FileNotFoundError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("Failed to delete child-screen animation: %s", exc)
        return jsonify({"success": False, "error": str(exc)}), 500


@robot_bp.route("/<path:disabled_path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def reject_hardware_surface(disabled_path: str):
    """Fail closed for all remaining legacy motion, mapping and Runtime paths."""
    return _disabled_response(disabled_path)


__all__ = ["robot_bp"]
