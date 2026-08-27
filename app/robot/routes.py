"""Hardware-free Demo course-output routes.

The ``/api/robot`` prefix is retained for compatibility with existing child
and teacher clients. It does not expose robot motion, Robot Runtime, or the
full product's expression system in this repository.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.deployment_capabilities import load_demo_capabilities
from app.robot import get_robot_service
from app.utils.logger import setup_logger


logger = setup_logger("demo_output_routes")
robot_bp = Blueprint("robot", __name__, url_prefix="/api/robot")


def _disabled_response(path: str):
    capability = "robotExpression" if path.startswith("emotions") else "robotMotionOrRuntime"
    return jsonify({
        "success": False,
        "error": "demo_capability_disabled",
        "capability": capability,
    }), 410


@robot_bp.route("/course-event", methods=["POST"])
def trigger_course_event():
    """Coordinate allowed audio/TTS and child-screen animation output."""
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
            "mode": "disabled",
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
    """Compatibility catalog filtered to the three Demo course types."""
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
    """Fail closed for legacy motion, expression, mapping and Runtime paths."""
    return _disabled_response(disabled_path)


__all__ = ["robot_bp"]
