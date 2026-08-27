"""
独立配置文件 API：camera_analysis.yaml / report_scoring.yaml
不并入 AnalyzerConfigManager；写盘前备份 .bak。
"""
from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

from app.behavior.camera_config import (
    load_camera_analysis_config,
    save_camera_analysis_config,
    validate_camera_analysis_config,
)
from app.report.scoring import (
    load_scoring_config,
    save_scoring_config,
    validate_scoring_config,
)
from app.utils.logger import setup_logger

logger = setup_logger("server_config_files")

server_config_files_bp = Blueprint(
    "server_config_files",
    __name__,
    url_prefix="/api/server/config",
)


@server_config_files_bp.route("/camera-analysis", methods=["GET"])
def get_camera_analysis():
    try:
        cfg = load_camera_analysis_config()
        return jsonify({"success": True, "config": cfg})
    except Exception as e:
        logger.error("get camera-analysis: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@server_config_files_bp.route("/camera-analysis", methods=["PUT"])
def put_camera_analysis():
    try:
        payload = request.get_json(silent=True) or {}
        incoming = payload.get("config")
        if not isinstance(incoming, dict):
            return jsonify({"success": False, "error": "config 必须为对象"}), 400
        errors = validate_camera_analysis_config(incoming)
        if errors:
            return jsonify({"success": False, "error": "；".join(errors), "errors": errors}), 400
        try:
            saved = save_camera_analysis_config(incoming)
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        return jsonify({
            "success": True,
            "config": saved,
            "message": "已写入 camera_analysis.yaml（下次加载/下一场生效）",
        })
    except Exception as e:
        logger.error("put camera-analysis: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@server_config_files_bp.route("/report-scoring", methods=["GET"])
def get_report_scoring():
    try:
        cfg = load_scoring_config()
        return jsonify({"success": True, "config": cfg})
    except Exception as e:
        logger.error("get report-scoring: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@server_config_files_bp.route("/report-scoring", methods=["PUT"])
def put_report_scoring():
    try:
        payload = request.get_json(silent=True) or {}
        incoming = payload.get("config")
        if not isinstance(incoming, dict):
            return jsonify({"success": False, "error": "config 必须为对象"}), 400
        # 合并到现有，避免表单只提交子集时丢掉其它键
        current = load_scoring_config()
        merged = dict(current)
        for key in (
            "weights",
            "interactive_course",
            "narrative_provider",
            "dimension_weights",
            "course_weights",
            "teacher_rating",
            "grade_thresholds",
            "schema_version",
            "score_boundary",
            "course_goal_score",
        ):
            if key in incoming:
                if key in ("weights", "interactive_course", "dimension_weights", "course_weights", "teacher_rating", "grade_thresholds") and isinstance(incoming[key], dict):
                    base = dict(merged.get(key) or {})
                    base.update(incoming[key])
                    merged[key] = base
                else:
                    merged[key] = incoming[key]
        errors = validate_scoring_config(merged)
        if errors:
            return jsonify({"success": False, "error": "；".join(errors), "errors": errors}), 400
        try:
            saved = save_scoring_config(merged)
        except ValueError as e:
            return jsonify({"success": False, "error": str(e)}), 400
        return jsonify({
            "success": True,
            "config": saved,
            "message": "已写入 report_scoring.yaml（仅影响新生成报告，不回写已落盘报告）",
        })
    except Exception as e:
        logger.error("put report-scoring: %s", e, exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
