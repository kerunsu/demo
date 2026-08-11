"""报告 API（含审核推送 / 人工编辑）"""
from flask import Blueprint, jsonify, request

from app.report import get_report_service
from app.utils.logger import setup_logger

logger = setup_logger("report_routes")

report_bp = Blueprint("report", __name__, url_prefix="/api/report")


@report_bp.route("/<training_session_id>/generate", methods=["POST"])
def generate_report(training_session_id: str):
    try:
        body = request.get_json(silent=True) or {}
        auto_finalize = body.get("autoFinalize", True)
        soft = body.get("soft", True)
        report = get_report_service().generate(
            training_session_id,
            auto_finalize=bool(auto_finalize),
            soft=bool(soft),
        )
        return jsonify({"success": True, "data": report})
    except ValueError as e:
        code = str(e)
        status = 409 if "not_finalized" in code else 400
        return jsonify({"success": False, "error": code}), status
    except Exception as e:
        logger.error("生成报告失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@report_bp.route("/<training_session_id>/refresh", methods=["POST"])
def refresh_report(training_session_id: str):
    try:
        report = get_report_service().refresh(training_session_id)
        return jsonify({"success": True, "data": report})
    except Exception as e:
        logger.error("刷新报告失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@report_bp.route("/<training_session_id>", methods=["GET"])
def get_report(training_session_id: str):
    try:
        role = request.args.get("role", "teacher")
        view = request.args.get("view", "auto")
        # 兼容旧行为：generate=1 且 server 角色可触发生成
        if request.args.get("generate") == "1" and role == "server":
            get_report_service().generate(training_session_id, auto_finalize=True, soft=True)
        report = get_report_service().get_for_viewer(
            training_session_id, role=role, view=view
        )
        return jsonify({"success": True, "data": report})
    except ValueError as e:
        code = str(e)
        if code == "report_not_published":
            status = get_report_service().review_status(training_session_id)
            return jsonify({
                "success": False,
                "error": code,
                "publicationStatus": status.get("publicationStatus"),
                "review": status,
            }), 409
        if code == "report_not_found":
            return jsonify({"success": False, "error": code}), 404
        return jsonify({"success": False, "error": code}), 400
    except Exception as e:
        logger.error("获取报告失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@report_bp.route("/<training_session_id>/review-status", methods=["GET"])
def review_status(training_session_id: str):
    try:
        data = get_report_service().review_status(training_session_id)
        return jsonify({"success": True, "data": data})
    except Exception as e:
        logger.error("获取审核状态失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@report_bp.route("/pending-reviews", methods=["GET"])
def pending_reviews():
    try:
        limit = request.args.get("limit", 20, type=int)
        items = get_report_service().list_pending_reviews(limit=limit or 20)
        return jsonify({"success": True, "items": items})
    except Exception as e:
        logger.error("列出待审核报告失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@report_bp.route("/<training_session_id>/publish", methods=["POST"])
def publish_report(training_session_id: str):
    try:
        data = get_report_service().publish(training_session_id)
        return jsonify({"success": True, "data": data})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error("推送报告失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@report_bp.route("/<training_session_id>/manual", methods=["PUT"])
def save_manual_report(training_session_id: str):
    try:
        body = request.get_json(silent=True) or {}
        data = get_report_service().save_manual(training_session_id, body)
        return jsonify({"success": True, "data": data})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except Exception as e:
        logger.error("保存人工报告失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@report_bp.route("/<training_session_id>/revert", methods=["POST"])
def revert_manual_report(training_session_id: str):
    try:
        data = get_report_service().revert_manual(training_session_id)
        return jsonify({"success": True, "data": data})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 404
    except Exception as e:
        logger.error("撤回人工报告失败: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
