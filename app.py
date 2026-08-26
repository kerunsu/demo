import os
from pathlib import Path

from dotenv import load_dotenv

# Acquire before importing analyzers, opening the database or starting helper
# services.  Previously two `python app.py` processes could initialize in
# parallel and split Socket.IO sessions across independent memory registries.
_server_instance_lock = None
if __name__ == "__main__":
    from app.utils.single_instance import (
        InstanceAlreadyRunning,
        acquire_server_instance_lock,
    )

    try:
        _server_instance_lock = acquire_server_instance_lock(Path(__file__).resolve().parent)
    except InstanceAlreadyRunning as exc:
        # 已有一个实例在跑：给用户可操作的提示，而不是只退一个状态码。
        # 双击 app.py 的窗口会一闪而过，这里等待回车让提示停留（脚本调用时用
        # SERVER_NO_WAIT=1 跳过）。
        print(f"[server] {exc}")
        pid_file = Path(__file__).resolve().parent / ".runtime" / "coordination" / "server_instance.lock.pid"
        try:
            existing_pid = int(pid_file.read_text(encoding="ascii").strip() or 0) or None
        except (OSError, ValueError):
            existing_pid = None
        if existing_pid:
            print(f"[server] 正在运行的后端实例 PID: {existing_pid}")
        print("[server] 无需重复启动，直接使用 http://127.0.0.1:8080/ 即可。")
        print("[server] 停止服务：双击 stop_server.bat，或运行  server.ps1 stop")
        print("[server] 重启服务：双击 restart_server.bat，或运行  server.ps1 restart")
        if os.environ.get("SERVER_NO_WAIT") != "1":
            try:
                input("[server] 按回车键关闭此窗口...")
            except EOFError:
                pass
        raise SystemExit(73)

# Config 和其他应用模块会在 import 时读取环境变量，因此必须先加载 .env。
# 主动加载也能避免 Flask 在 Windows/VS Code 终端中打印 dotenv 提示时
# 触发无效控制台句柄（Windows error 6）。
load_dotenv(Path(__file__).resolve().with_name('.env'))

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    session,
    send_from_directory,
)
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from database.models import (
    db,
    Teacher,
    Student,
    CourseType,
    AbilityType,
    TrainingSession,
    TrainingDetail,
    AbilityItem,
    TrainingReportSummary,
    Course,
)
from datetime import datetime
from sqlalchemy import desc
from sqlalchemy.orm import joinedload
import json
import mimetypes
import os
from typing import Dict, Any, List

mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('application/wasm', '.wasm')

# 导入新架构模块
from app.config import Config
from app.course_scope import filter_course_payloads
from app.session import get_session_manager
from app.utils.logger import setup_logger
from app.sockets import register_socket_events
from app.sockets.events import get_online_presence_snapshot
from app.services import get_media_service, get_analysis_service, get_feedback_service
from app.core.trigger import get_trigger_system
from app.core.auto_register import auto_register  # 新框架：自动注册分析器
from app.core.config_manager import get_config_manager
from app.dialogue import init_dialogue_service
from app.dialogue.sockets import register_dialogue_events
from app.facade import create_application_container
from app.facade.routes.server_status import execute_server_status
from app.facade.sockets import register_legacy_socket_events
from app.facade.use_cases.server_status import ServerStatusInputs

# 导入机械臂控制模块
from app.robot.routes import robot_bp
from app.robot import robot_service
from app.robot.runtime_registry import get_runtime_status

# 儿童端 Media Agent 上行 / 补传
from app.routes.media_upload import media_bp, get_media_session_meta
from app.routes.capture_devices import capture_devices_bp
from app.routes.asset_library import asset_library_bp
from app.routes.interaction_profiles import interaction_profiles_bp
from app.routes.control_overview import control_overview_bp
from app.routes.config_sync import config_sync_bp
from app.routes.voice_status import voice_status_bp
from app.routes.interaction_timeline import interaction_timeline_bp

# 导入语音系统模块
from app.audio import init_audio_emitter, init_audio_controller
from app.sockets.audio_events import register_audio_events

# 初始化日志
logger = setup_logger('app')

app = Flask(__name__)
# 第二阶段 composition root 骨架。旧基础设施仍由本文件按原顺序装配；容器
# 本身无线程、设备、文件或数据库副作用，只保存可替换的应用层用例。
facade_container = create_application_container()
app.extensions["facade_container"] = facade_container
app.config['SECRET_KEY'] = Config.SECRET_KEY
# 开发时模板改完即可生效，避免旧进程/缓存继续吐旧 child.html
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True
# Course media is immutable during a teaching day. Keep it on each classroom
# device so switching students/sessions reuses the local browser disk cache.
# Expression URLs carry a file version, so changed videos get a fresh URL.
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 24 * 60 * 60

# 配置CORS，允许前端跨域请求
CORS(app, supports_credentials=True, resources={
    r"/api/*": {"origins": "*"},
    r"/courses": {"origins": "*"}
})

# 配置SQLite数据库（使用Config中的配置）
app.config['SQLALCHEMY_DATABASE_URI'] = Config.SQLALCHEMY_DATABASE_URI
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = Config.SQLALCHEMY_TRACK_MODIFICATIONS
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = Config.SQLALCHEMY_ENGINE_OPTIONS

# 初始化数据库
db.init_app(app)

socketio = SocketIO(app, cors_allowed_origins="*")

# 注册机械臂控制模块 Blueprint
app.register_blueprint(robot_bp)
logger.info("机械臂控制模块已注册 (Blueprint: /api/robot)")

# 运行时模式：yaml > env > 默认 agent / robot_runtime
try:
    from app.runtime_modes import apply_to_process, load_runtime_modes
    _modes = apply_to_process(load_runtime_modes())
    logger.info(
        "运行时模式已加载: child_media=%s robot_control=%s",
        _modes.get("child_media_mode"),
        _modes.get("robot_control_mode"),
    )
except Exception as e:
    logger.warning("运行时模式加载失败（将用代码默认）: %s", e)

# 注册儿童端媒体上行 / 补传 Blueprint
app.register_blueprint(media_bp)
logger.info("媒体上行模块已注册 (Blueprint: /api/media)")

# 第三阶段：0..N 采集设备控制面；旧 ambient API 保持兼容
app.register_blueprint(capture_devices_bp)
logger.info("采集设备注册表 API 已注册 (Blueprint: /api/v2/capture)")
app.register_blueprint(asset_library_bp)
logger.info("动作/表情批量素材 API 已注册 (Blueprint: /api/v2/assets)")
app.register_blueprint(interaction_profiles_bp)
logger.info("InteractionProfileV2 API 已注册 (Blueprint: /api/v2/interaction)")
app.register_blueprint(control_overview_bp)
app.register_blueprint(config_sync_bp)
app.register_blueprint(voice_status_bp)
app.register_blueprint(interaction_timeline_bp)
logger.info("设备与录制总览 API 已注册 (Blueprint: /api/v2/control)")

# 注册报告 API
from app.routes.report import report_bp
app.register_blueprint(report_bp)
logger.info("报告模块已注册 (Blueprint: /api/report)")

# 注册监控 Snapshot API
from app.routes.monitor import monitor_bp
app.register_blueprint(monitor_bp)
logger.info("监控模块已注册 (Blueprint: /api/monitor)")

# 注册配置中心 · 交互内容 API
from app.routes.config_content import config_content_bp, ensure_speech_target_column
app.register_blueprint(config_content_bp)
logger.info("交互内容配置模块已注册 (Blueprint: /api/config)")

from app.routes.server_config_files import server_config_files_bp
app.register_blueprint(server_config_files_bp)
logger.info("camera/report 配置文件 API 已注册")

from app.report.archive_sync import ensure_training_archive_schema

with app.app_context():
    try:
        ensure_speech_target_column()
    except Exception as e:
        logger.warning("speech_target 列迁移跳过: %s", e)
    try:
        ensure_training_archive_schema()
    except Exception as e:
        logger.warning("训练档案 schema 迁移跳过: %s", e)

# 初始化会话管理器
session_manager = get_session_manager()
logger.info("会话管理器已初始化")

# 初始化媒体服务（启动队列消费线程）
media_service = get_media_service()
logger.info("媒体服务已初始化")

# ========== 新框架：自动注册所有分析器和比对器 ==========
# 必须在初始化分析服务之前调用，否则注册表中没有分析器
auto_register()
logger.info("分析器注册表已初始化")
# ========================================================

# 注意：现在通过 config/analyzers.yaml 或环境变量 USE_REAL_ANALYZERS 控制模式
# 旧的 enable_real_analyzers() / enable_mock_analyzers() 已废弃

# 初始化分析服务
analysis_service = get_analysis_service()
analysis_health = analysis_service.get_pipeline_health()
if analysis_health.get("ready"):
    logger.info("分析服务健康检查通过")
else:
    log = logger.info if analysis_health.get("status") == "initializing" else logger.error
    log(
        "分析服务状态=%s（录制门禁不等待后台分析）: %s",
        analysis_health.get("status"),
        analysis_health.get("requiredFailures"),
    )

# 初始化反馈服务并设置SocketIO
feedback_service = get_feedback_service()
feedback_service.set_socketio(socketio)
logger.info("反馈服务已初始化并设置SocketIO")

# 设置触发系统的SocketIO（用于动作执行器发送事件）
trigger_system = get_trigger_system()
trigger_system.executor.set_socketio(socketio)
logger.info("触发系统已设置SocketIO")

# 设置分析服务回调（连接分析服务和反馈服务）
def on_analysis_result(session_id, result):
    """分析结果回调"""
    feedback_service.send_analysis_result(session_id, result)

def on_match_result(session_id, result):
    """匹配结果回调"""
    feedback_service.send_match_result(session_id, result)
    if (
        getattr(result, 'matcher_type', None) == 'pose_matcher'
        and bool(getattr(result, 'passed', False))
    ):
        try:
            from app.services.pose_auto_praise import get_pose_auto_praise_service

            get_pose_auto_praise_service().try_auto_praise(session_id, result)
        except Exception as exc:
            # Recognition/recording must remain alive even when a feedback
            # peripheral is temporarily unavailable.
            logger.warning(
                "模仿动作自动表扬失败 session=%s: %s",
                session_id,
                exc,
                exc_info=True,
            )

def on_trigger_action(session_id, action_type, data):
    """
    触发动作回调
    
    对于音频播放：ActionExecutor 已通过语音系统 emit，此处避免再播一次
   （否则队列里会叠两条 praise，听感像「表扬播完又立刻再播」）。
    """
    if action_type == 'play_audio':
        data = data or {}
        # ActionExecutor 成功时 metadata 已带 entry_id，说明已经播放过
        if data.get('entry_id'):
            logger.debug(
                "触发动作回调: 跳过重复播放 entry_id=%s session=%s",
                data.get('entry_id'), session_id
            )
            return
        try:
            from app.audio import get_audio_emitter
            emitter = get_audio_emitter()
            child_room = f"session_{session_id}_child"
            
            audio_type = data.get('type') or data.get('original_type', 'praise')
            type_to_entry = {
                'praise': 'praise',
                'interest': 'praise',
                'hint': 'hint',
                'question': 'question',
                'default': 'praise'
            }
            entry_id = type_to_entry.get(audio_type, 'praise')
            
            emitter.emit_audio(room=child_room, entry_id=entry_id)
            logger.info(f"触发动作回调: 通过语音系统播放 {entry_id}")
        except Exception as e:
            logger.error(f"触发动作回调播放音频失败: {e}")
    else:
        # 其他类型仍然使用旧的方式
        feedback_service.send_trigger_action(session_id, action_type, 'child', data)

analysis_service.set_callbacks(
    on_analysis=on_analysis_result,
    on_match=on_match_result,
    on_trigger=on_trigger_action
)
logger.info("分析服务回调已设置")

# 注册WebSocket事件处理器
register_legacy_socket_events(socketio, register_socket_events)
register_dialogue_events(socketio)
init_dialogue_service()
logger.info("WebSocket事件处理器已注册")

# 绑定SocketIO到机械臂服务（用于表情事件）
robot_service.set_socketio(socketio)
logger.info("SocketIO已绑定到机械臂服务")

# 初始化语音系统
audio_emitter = init_audio_emitter(socketio)
audio_controller = init_audio_controller(socketio)
logger.info("语音播放系统已初始化")

# 注册语音 WebSocket 事件
register_audio_events(socketio)
logger.info("语音WebSocket事件处理器已注册")


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/therapist')
def therapist():
    """旧教师端入口：重定向到新教师端前端。"""
    teacher_url = os.environ.get('TEACHER_FRONTEND_URL', '/teacher/')
    return redirect(teacher_url)


@app.route('/teacher')
def teacher_without_slash():
    return redirect('/teacher/')


@app.route('/teacher/', defaults={'asset_path': ''})
@app.route('/teacher/<path:asset_path>')
def teacher_frontend(asset_path: str):
    """Serve the production teacher SPA from the same 8080 origin."""
    dist = Path(__file__).resolve().parent / 'teacher_frontend' / 'dist'
    requested = dist / asset_path if asset_path else None
    if requested is not None and requested.is_file():
        return send_from_directory(dist, asset_path)
    index_file = dist / 'index.html'
    if not index_file.is_file():
        return jsonify({
            'success': False,
            'error': 'teacher_frontend_not_built',
            'message': '教师端尚未构建，请重新执行一键启动。',
        }), 503
    return send_from_directory(dist, 'index.html')


@app.route('/child')
def child():
    return render_template('child.html')


@app.route("/server")
def server_page():
    """实时监控台。旧 ?view=config（高级 YAML）已下线，重定向到配置中心概览。"""
    view = request.args.get("view", "")
    if view == "config":
        return redirect("/server/config/overview")
    return render_template("server.html")


@app.route("/server/report-review/<training_session_id>")
def server_report_review(training_session_id: str):
    """Server 侧报告审核/可视化编辑页。"""
    return render_template(
        "server_report_edit.html",
        training_session_id=training_session_id,
    )


@app.route("/server/config")
def server_config_root():
    """配置中心入口 → 概览（F-Algo）"""
    return redirect("/server/config/overview")


@app.route("/server/config/overview")
def server_config_overview():
    return render_template("server/config.html", active_module="overview")


@app.route("/server/config/camera")
def server_config_camera():
    return render_template("server/config.html", active_module="camera")


@app.route("/server/config/speech")
def server_config_speech():
    return render_template("server/config.html", active_module="speech")


@app.route("/server/config/report")
def server_config_report():
    return render_template("server/config.html", active_module="report")


@app.route("/server/config/content")
def server_config_content():
    """配置中心 · 交互内容（F-IC）"""
    return render_template("server/config.html", active_module="content")


@app.route("/server/config/devices")
def server_config_devices():
    """配置中心 · 设备与录制。"""
    return render_template("server/config.html", active_module="devices")


@app.route("/server/config/latency")
def server_config_latency():
    """配置中心 · 只读交互延迟诊断。"""
    return render_template("server/config.html", active_module="latency")


@app.route("/robot")
def robot_page():
    """机械臂控制面板页面"""
    return render_template("robot/control.html")


@app.route("/robot/emotion")
def robot_emotion_page():
    """机器人表情显示页面"""
    return render_template("robot/emotion.html")


@app.route("/robot/download")
def robot_download_page():
    """机器人端安装包下载页（局域网自助获取 exe+DollSer zip）"""
    return render_template("robot_download.html")


# ==================== Server 配置控制台 API ====================

ALLOWED_CONFIG_SCHEMA: Dict[str, Dict[str, Any]] = {
    "global": {
        "mode": {"type": "enum", "choices": ["mock", "real"]},
        "enable_sampling": {"type": "bool"},
        "enable_metrics": {"type": "bool"},
    },
    "analyzers": {
        "pose": {
            "mode": {"type": "nullable_enum", "choices": ["mock", "real"]},
            "enabled": {"type": "bool"},
            "sample_rate": {"type": "number", "min": 0.0, "max": 1.0},
            "model_path": {"type": "str"},
            "min_detection_confidence": {"type": "number", "min": 0.0, "max": 1.0},
            "num_poses": {"type": "number", "min": 1, "max": 10},
        },
        "face": {
            "mode": {"type": "nullable_enum", "choices": ["mock", "real"]},
            "enabled": {"type": "bool"},
            "sample_rate": {"type": "number", "min": 0.0, "max": 1.0},
            "model_path": {"type": "str"},
            "confidence_threshold": {"type": "number", "min": 0.0, "max": 1.0},
        },
        "attention": {
            "mode": {"type": "nullable_enum", "choices": ["mock", "real"]},
            "enabled": {"type": "bool"},
            "window_size": {"type": "number", "min": 1.0, "max": 120.0},
            "pose_threshold": {"type": "number", "min": 0.0, "max": 180.0},
            "min_detection_confidence": {"type": "number", "min": 0.0, "max": 1.0},
            "min_tracking_confidence": {"type": "number", "min": 0.0, "max": 1.0},
        },
        "speech": {
            "mode": {"type": "nullable_enum", "choices": ["mock", "real"]},
            "enabled": {"type": "bool"},
            "sample_rate": {"type": "number", "min": 0.0, "max": 1.0},
            "model_path": {"type": "str"},
            "model_name": {"type": "str"},
            "device": {"type": "str"},
            "sample_rate_audio": {"type": "number", "min": 1000, "max": 96000},
            "accumulation_duration": {"type": "number", "min": 0.1, "max": 60.0},
            "language": {"type": "str"},
        },
    },
    "matchers": {
        "pose": {
            "mode": {"type": "nullable_enum", "choices": ["mock", "real"]},
            "enabled": {"type": "bool"},
            "threshold": {"type": "number", "min": 0.0, "max": 1.0},
        },
        "speech": {
            "mode": {"type": "nullable_enum", "choices": ["mock", "real"]},
            "enabled": {"type": "bool"},
            "threshold": {"type": "number", "min": 0.0, "max": 100.0},
        },
    },
}


def _validate_typed_field(path: str, value: Any, spec: Dict[str, Any], errors: List[str]) -> None:
    """校验单个字段类型和取值范围。"""
    expected_type = spec.get("type")
    if expected_type == "bool":
        if not isinstance(value, bool):
            errors.append(f"{path} 必须是布尔值")
        return
    
    if expected_type == "str":
        if not isinstance(value, str):
            errors.append(f"{path} 必须是字符串")
        return
    
    if expected_type == "enum":
        if value not in spec.get("choices", []):
            choices = "/".join(spec.get("choices", []))
            errors.append(f"{path} 只能是 {choices}")
        return
    
    if expected_type == "nullable_enum":
        if value is None:
            return
        if value not in spec.get("choices", []):
            choices = "/".join(spec.get("choices", []))
            errors.append(f"{path} 只能是 null 或 {choices}")
        return
    
    if expected_type == "number":
        if not isinstance(value, (int, float)):
            errors.append(f"{path} 必须是数字")
            return
        min_value = spec.get("min")
        max_value = spec.get("max")
        if min_value is not None and value < min_value:
            errors.append(f"{path} 不能小于 {min_value}")
        if max_value is not None and value > max_value:
            errors.append(f"{path} 不能大于 {max_value}")
        return


def _validate_server_config_payload(payload: Dict[str, Any], *, partial: bool = True) -> List[str]:
    """校验 server 配置 payload，返回错误列表。"""
    errors: List[str] = []
    if not isinstance(payload, dict):
        return ["config 必须是对象"]
    
    # 全局配置校验
    if "global" in payload:
        global_cfg = payload.get("global")
        if not isinstance(global_cfg, dict):
            errors.append("global 必须是对象")
        else:
            schema = ALLOWED_CONFIG_SCHEMA["global"]
            for field_name, field_value in global_cfg.items():
                if field_name not in schema:
                    errors.append(f"global.{field_name} 不是允许字段")
                    continue
                _validate_typed_field(
                    f"global.{field_name}",
                    field_value,
                    schema[field_name],
                    errors
                )
    
    # analyzers / matchers 分组校验
    for group_name in ("analyzers", "matchers"):
        if group_name not in payload:
            continue
        
        group_cfg = payload.get(group_name)
        if not isinstance(group_cfg, dict):
            errors.append(f"{group_name} 必须是对象")
            continue
        
        group_schema = ALLOWED_CONFIG_SCHEMA[group_name]
        for item_name, item_cfg in group_cfg.items():
            if not isinstance(item_cfg, dict):
                errors.append(f"{group_name}.{item_name} 必须是对象")
                continue
            
            if item_name not in group_schema:
                errors.append(f"{group_name}.{item_name} 不是受支持的组件")
                continue
            
            item_schema = group_schema[item_name]
            for field_name, field_value in item_cfg.items():
                if field_name not in item_schema:
                    errors.append(f"{group_name}.{item_name}.{field_name} 不是允许字段")
                    continue
                _validate_typed_field(
                    f"{group_name}.{item_name}.{field_name}",
                    field_value,
                    item_schema[field_name],
                    errors
                )
    
    # replace 时做最小完整性校验
    if not partial:
        for required_key in ("global", "analyzers", "matchers"):
            if required_key not in payload:
                errors.append(f"完整替换配置缺少字段: {required_key}")
    
    return errors


def _collect_model_status(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """收集模型路径状态（存在性检查）。"""
    project_root = Path(__file__).resolve().parent
    results: List[Dict[str, Any]] = []
    
    analyzers = config.get("analyzers", {})
    if not isinstance(analyzers, dict):
        return results
    
    for analyzer_name, analyzer_cfg in analyzers.items():
        if not isinstance(analyzer_cfg, dict):
            continue
        model_path = analyzer_cfg.get("model_path")
        if not model_path or not isinstance(model_path, str):
            continue
        
        path_obj = Path(model_path)
        resolved = path_obj if path_obj.is_absolute() else project_root / path_obj
        exists = resolved.exists()
        
        results.append({
            "analyzer": analyzer_name,
            "model_path": model_path,
            "resolved_path": str(resolved),
            "exists": exists
        })
    
    return results


@app.route("/api/server/config", methods=["GET"])
def get_server_config():
    """获取分析配置（内存中的当前有效配置）。"""
    try:
        config_mgr = get_config_manager()
        return jsonify({
            "success": True,
            "config": config_mgr.get_all_config(),
            "configPath": config_mgr.config_path
        }), 200
    except Exception as e:
        logger.error(f"获取 server 配置失败: {e}")
        return jsonify({"success": False, "error": f"获取配置失败: {str(e)}"}), 500


@app.route("/api/server/config", methods=["PUT"])
def update_server_config():
    """更新分析配置（支持局部更新或整体替换，仅更新内存）。"""
    try:
        payload = request.get_json(silent=True) or {}
        new_config = payload.get("config")
        replace = bool(payload.get("replace", False))
        actor = str(payload.get("actor", "server_console"))
        
        errors = _validate_server_config_payload(new_config, partial=(not replace))
        if errors:
            return jsonify({"success": False, "errors": errors}), 400
        
        config_mgr = get_config_manager()
        if replace:
            updated = config_mgr.replace_config(new_config, actor=actor)
        else:
            updated = config_mgr.update_config(new_config, actor=actor)
        
        return jsonify({
            "success": True,
            "message": "配置已更新到内存",
            "config": updated
        }), 200
    except Exception as e:
        logger.error(f"更新 server 配置失败: {e}")
        return jsonify({"success": False, "error": f"更新配置失败: {str(e)}"}), 500


@app.route("/api/server/config/save", methods=["POST"])
def save_server_config():
    """将当前内存配置保存到 YAML 文件。"""
    try:
        payload = request.get_json(silent=True) or {}
        save_path = payload.get("path")
        
        config_mgr = get_config_manager()
        success = config_mgr.save_config(save_path)
        if not success:
            return jsonify({"success": False, "error": "保存配置失败"}), 500
        
        return jsonify({
            "success": True,
            "message": "配置已保存",
            "savedPath": save_path or config_mgr.config_path
        }), 200
    except Exception as e:
        logger.error(f"保存 server 配置失败: {e}")
        return jsonify({"success": False, "error": f"保存配置失败: {str(e)}"}), 500


@app.route("/api/server/config/reset-defaults", methods=["POST"])
def reset_server_config_defaults():
    """将内存配置恢复为默认值。"""
    try:
        payload = request.get_json(silent=True) or {}
        apply_env = bool(payload.get("applyEnvOverrides", False))
        actor = str(payload.get("actor", "server_console"))
        config_mgr = get_config_manager()
        config = config_mgr.reset_to_default(
            apply_env_overrides=apply_env,
            actor=actor
        )
        return jsonify({
            "success": True,
            "message": "已恢复默认配置",
            "config": config
        }), 200
    except Exception as e:
        logger.error(f"恢复默认配置失败: {e}")
        return jsonify({"success": False, "error": f"恢复默认配置失败: {str(e)}"}), 500


@app.route("/api/server/config/rollback", methods=["POST"])
def rollback_server_config():
    """回滚到最近一次配置快照。"""
    try:
        payload = request.get_json(silent=True) or {}
        actor = str(payload.get("actor", "server_console"))
        config_mgr = get_config_manager()
        rolled = config_mgr.rollback_last_snapshot(actor=actor)
        if rolled is None:
            return jsonify({
                "success": False,
                "error": "没有可回滚的配置快照"
            }), 400
        return jsonify({
            "success": True,
            "message": "已回滚到上一版配置",
            "config": rolled,
            "remainingSnapshots": config_mgr.get_snapshot_count()
        }), 200
    except Exception as e:
        logger.error(f"回滚配置失败: {e}")
        return jsonify({"success": False, "error": f"回滚失败: {str(e)}"}), 500


@app.route("/api/server/config/apply-preview", methods=["GET"])
def preview_server_config_apply():
    """预检配置应用影响。"""
    try:
        sessions = analysis_service.get_all_session_states()
        active_sessions = [s for s in sessions if s.get("is_active")]
        impact = {
            "activeSessionCount": len(active_sessions),
            "activeSessionIds": [s.get("session_id") for s in active_sessions],
            "requiresForceForActiveReload": len(active_sessions) > 0,
            "restartRequiredHint": (
                "更换底层模型依赖时建议使用 restart_required，确保依赖干净加载"
            )
        }
        return jsonify({
            "success": True,
            "impact": impact
        }), 200
    except Exception as e:
        logger.error(f"获取应用预检信息失败: {e}")
        return jsonify({"success": False, "error": f"预检失败: {str(e)}"}), 500


@app.route("/api/server/config/apply", methods=["POST"])
def apply_server_config():
    """
    应用配置到运行时。
    
    scope:
      - new_sessions_only: 仅新会话使用新配置（默认）
      - active_sessions: 通过重载流水线让当前运行中的会话也生效
      - restart_required: 标记需要重启服务后生效
    """
    try:
        payload = request.get_json(silent=True) or {}
        scope = payload.get("scope", "new_sessions_only")
        force = bool(payload.get("force", False))
        
        if scope not in (
            "new_sessions_only",
            "active_sessions",
            "restart_required"
        ):
            return jsonify({
                "success": False,
                "error": (
                    "scope 必须是 new_sessions_only / "
                    "active_sessions / restart_required"
                )
            }), 400
        
        if scope == "active_sessions":
            sessions = analysis_service.get_all_session_states()
            active_sessions = [s for s in sessions if s.get("is_active")]
            if active_sessions and not force:
                return jsonify({
                    "success": False,
                    "error": "检测到运行中会话，请确认强制重载",
                    "requiresForce": True,
                    "impact": {
                        "activeSessionCount": len(active_sessions),
                        "activeSessionIds": [
                            s.get("session_id") for s in active_sessions
                        ]
                    }
                }), 409
            if not analysis_service.reload_pipelines():
                return jsonify({
                    "success": False,
                    "error": "应用到运行时失败：流水线重载失败"
                }), 500
            message = "配置已应用到运行中的会话（流水线已重载）"
        elif scope == "restart_required":
            message = (
                "配置已接收并写入内存。该变更建议重启服务后再生效。"
            )
        else:
            message = "配置将在新会话中自动生效"
        
        return jsonify({
            "success": True,
            "scope": scope,
            "message": message,
            "restartRequired": scope == "restart_required"
        }), 200
    except Exception as e:
        logger.error(f"应用 server 配置失败: {e}")
        return jsonify({"success": False, "error": f"应用配置失败: {str(e)}"}), 500


@app.route("/api/server/config/history", methods=["GET"])
def get_server_config_history():
    """获取配置变更历史（审计日志）。"""
    try:
        limit = request.args.get("limit", default=100, type=int)
        config_mgr = get_config_manager()
        return jsonify({
            "success": True,
            "history": config_mgr.get_audit_logs(limit=limit)
        }), 200
    except Exception as e:
        logger.error(f"获取配置历史失败: {e}")
        return jsonify({"success": False, "error": f"获取历史失败: {str(e)}"}), 500


@app.route("/api/server/presets", methods=["GET"])
def get_server_presets():
    """获取预设模板列表。"""
    try:
        config_mgr = get_config_manager()
        presets = config_mgr.get_presets()
        return jsonify({
            "success": True,
            "presetNames": list(presets.keys())
        }), 200
    except Exception as e:
        logger.error(f"获取预设失败: {e}")
        return jsonify({"success": False, "error": f"获取预设失败: {str(e)}"}), 500


@app.route("/api/server/presets/apply", methods=["POST"])
def apply_server_preset():
    """应用指定预设模板到当前配置。"""
    try:
        payload = request.get_json(silent=True) or {}
        preset_name = payload.get("presetName")
        actor = str(payload.get("actor", "server_console"))
        if not preset_name:
            return jsonify({
                "success": False,
                "error": "presetName 不能为空"
            }), 400
        
        config_mgr = get_config_manager()
        config = config_mgr.apply_preset(preset_name, actor=actor)
        return jsonify({
            "success": True,
            "message": f"预设已应用: {preset_name}",
            "config": config
        }), 200
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"应用预设失败: {e}")
        return jsonify({"success": False, "error": f"应用预设失败: {str(e)}"}), 500


@app.route("/api/server/diagnostics", methods=["GET"])
def get_server_diagnostics():
    """获取分析诊断指标（错误率、耗时、吞吐）。"""
    try:
        diagnostics = analysis_service.get_diagnostics()
        return jsonify({
            "success": True,
            "diagnostics": diagnostics
        }), 200
    except Exception as e:
        logger.error(f"获取诊断指标失败: {e}")
        return jsonify({"success": False, "error": f"获取诊断失败: {str(e)}"}), 500


@app.route("/api/server/robot/control-mode", methods=["GET"])
def get_robot_control_mode():
    """获取机械臂控制模式。"""
    try:
        service = robot_service.get_robot_service()
        return jsonify({
            "success": True,
            "mode": service.get_control_mode(),
            "options": ["server_osc", "child_agent", "robot_runtime"],
        }), 200
    except Exception as e:
        logger.error(f"获取机械臂控制模式失败: {e}")
        return jsonify({"success": False, "error": f"获取控制模式失败: {str(e)}"}), 500


@app.route("/api/server/robot/control-mode", methods=["PUT"])
def set_robot_control_mode():
    """设置机械臂控制模式（写盘 + 立即生效）。"""
    try:
        payload = request.get_json(silent=True) or {}
        mode = payload.get("mode")
        if mode not in ("server_osc", "child_agent", "robot_runtime"):
            return jsonify({
                "success": False,
                "error": "mode 必须是 server_osc / child_agent / robot_runtime"
            }), 400

        service = robot_service.get_robot_service()
        service.set_control_mode(mode, persist=True)
        return jsonify({
            "success": True,
            "mode": mode,
            "persisted": True,
            "message": f"机械臂控制模式已切换为 {mode}（已写入 runtime_modes.yaml）",
        }), 200
    except Exception as e:
        logger.error(f"设置机械臂控制模式失败: {e}")
        return jsonify({"success": False, "error": f"设置控制模式失败: {str(e)}"}), 500


@app.route("/api/server/runtime-modes", methods=["GET"])
def get_runtime_modes():
    """获取儿童媒体 + 机械臂控制模式（与落盘一致）。"""
    try:
        from app.runtime_modes import load_runtime_modes
        modes = load_runtime_modes()
        return jsonify({
            "success": True,
            "childMediaMode": Config.get_child_media_mode(),
            "robotControlMode": robot_service.get_robot_service().get_control_mode(),
            "dialogueWakeWordEnabled": bool(Config.DIALOGUE_WAKE_WORD_ENABLED),
            "browserSpeechRate": float(Config.BROWSER_SPEECH_RATE),
            "persisted": modes,
        }), 200
    except Exception as e:
        logger.error(f"获取运行时模式失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/server/runtime-modes", methods=["PUT"])
def put_runtime_modes():
    """一次应用并写盘儿童媒体 + 机械臂控制模式。"""
    try:
        from app.runtime_modes import apply_to_process, save_runtime_modes

        payload = request.get_json(silent=True) or {}
        child = payload.get("childMediaMode") or payload.get("child_media_mode")
        robot = payload.get("robotControlMode") or payload.get("robot_control_mode")
        wake_word = (
            payload.get("dialogueWakeWordEnabled")
            if "dialogueWakeWordEnabled" in payload
            else payload.get("dialogue_wake_word_enabled")
        )
        speech_rate = (
            payload.get("browserSpeechRate")
            if "browserSpeechRate" in payload
            else payload.get("browser_speech_rate")
        )
        if child is None and robot is None and wake_word is None and speech_rate is None:
            return jsonify({"success": False, "error": "请提供至少一项运行时设置"}), 400

        saved = save_runtime_modes(
            child_media_mode=child,
            robot_control_mode=robot,
            dialogue_wake_word_enabled=wake_word,
            browser_speech_rate=speech_rate,
        )
        apply_to_process(saved)
        socketio.emit("browser_speech_rate_updated", {
            "speechRate": saved["browser_speech_rate"],
        })
        return jsonify({
            "success": True,
            "childMediaMode": saved["child_media_mode"],
            "robotControlMode": saved["robot_control_mode"],
            "dialogueWakeWordEnabled": saved["dialogue_wake_word_enabled"],
            "browserSpeechRate": saved["browser_speech_rate"],
            "persisted": True,
            "message": "运行时模式已应用并写入 config/runtime_modes.yaml",
        }), 200
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"设置运行时模式失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/child/runtime-config", methods=["GET"])
def get_child_runtime_config():
    """儿童端页面启动时拉取媒体模式与 Agent 地址等。"""
    try:
        return jsonify({
            "success": True,
            **Config.get_child_runtime_config(),
        }), 200
    except Exception as e:
        logger.error(f"获取儿童端运行时配置失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/server/child-media-mode", methods=["GET"])
def get_child_media_mode():
    """获取儿童端媒体采集模式。"""
    try:
        return jsonify({
            "success": True,
            "mode": Config.get_child_media_mode(),
            "options": ["browser", "agent"],
            "agentPort": Config.CHILD_MEDIA_AGENT_PORT,
        }), 200
    except Exception as e:
        logger.error(f"获取儿童媒体模式失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/server/child-media-mode", methods=["PUT"])
def set_child_media_mode():
    """设置儿童端媒体采集模式（写盘；新会话起生效）。"""
    try:
        payload = request.get_json(silent=True) or {}
        mode = payload.get("mode")
        Config.set_child_media_mode(mode, persist=True)
        return jsonify({
            "success": True,
            "mode": Config.get_child_media_mode(),
            "persisted": True,
            "message": f"儿童媒体模式已切换为 {Config.get_child_media_mode()}（已写入 runtime_modes.yaml）",
        }), 200
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"设置儿童媒体模式失败: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/server/status", methods=["GET"])
def get_server_status():
    """获取 server 控制台状态（统计、会话、模型文件检查）。"""
    try:
        status_use_case = app.extensions["facade_container"].get("server_status_use_case")
        payload = execute_server_status(
            status_use_case,
            ServerStatusInputs(
                config_manager=get_config_manager(),
                analysis_service=analysis_service,
                model_status=_collect_model_status,
                online_presence=get_online_presence_snapshot,
                robot_control_mode=lambda: robot_service.get_robot_service().get_control_mode(),
                child_media_mode=Config.get_child_media_mode,
                media_session_meta=get_media_session_meta,
                runtime_status=get_runtime_status,
            )
        )
        return jsonify(payload), 200
    except Exception as e:
        logger.error(f"获取 server 状态失败: {e}")
        return jsonify({"success": False, "error": f"获取状态失败: {str(e)}"}), 500


# @app.route('/manifest.json')
# def manifest():
#     return app.send_static_file('manifest.json')


# @app.route('/service-worker.js')
# def sw():
#     return app.send_static_file('service-worker.js')


# 静态文件路由
@app.route('/static/css/<path:filename>')
def css_files(filename):
    return app.send_static_file(f'css/{filename}')


@app.route('/static/js/<path:filename>')
def js_files(filename):
    return app.send_static_file(f'js/{filename}')


@app.route('/static/resources/<path:filename>')
def resources(filename):
    return app.send_static_file(f'resources/{filename}')


# 提供课程配置 JSON
@app.route('/courses')
def get_courses():
    """从数据库获取课程列表"""
    try:
        # 从数据库查询所有课程，按 ID 排序
        # 使用 joinedload 一次性加载关联的 CourseItem，避免 N+1 查询问题
        courses = Course.query.options(joinedload(Course.items)).order_by(Course.id).all()
        
        if not courses:
            # 如果数据库中没有课程，尝试从 JSON 文件读取（向后兼容）
            courses_file = os.path.join(app.static_folder, "courses.json")
            if os.path.exists(courses_file):
                with open(courses_file, encoding="utf-8") as f:
                    courses_data = json.load(f)
                return jsonify(filter_course_payloads(courses_data))
            return jsonify({"error": "课程数据不存在"}), 404
        
        # 转换为 JSON 格式（保持与原有格式兼容）
        # course.items 已经通过 joinedload 预加载，不会触发额外查询
        courses_data = filter_course_payloads(
            [course.to_dict() for course in courses]
        )
        return jsonify(courses_data)
    except Exception as e:
        return jsonify({"error": f"获取课程配置失败: {str(e)}"}), 500


# video_frame事件处理已移至app/sockets/events.py
# 使用register_socket_events()注册的事件处理器处理
# @socketio.on("video_frame")
# def handle_video_frame(frame):
#     # 转发给所有客户端（除了发送者自己）
#     emit("video_frame", frame, broadcast=True, include_self=False)


# 处理治疗师端发送的按钮事件
@socketio.on('show_image')
def handle_show_image():
    # 把事件广播给所有客户端（比如儿童端）
    emit('show_image', broadcast=True)


# play_resource事件处理已移至app/sockets/events.py
# 使用register_socket_events()注册的事件处理器处理

# 排序 / 配对游戏：与儿童端 iframe 使用的静态页一致（见 static/resources/interactive/）


@app.route("/sequencing")
def sequencing():
    """重定向到互动排序页，保留查询参数（与 /static/... 直链行为一致）。"""
    url = "/static/resources/interactive/sequencing.html"
    if request.query_string:
        url = url + "?" + request.query_string.decode()
    return redirect(url)


@app.route("/matching")
def matching():
    """重定向到互动配对页，保留查询参数。"""
    url = "/static/resources/interactive/matching.html"
    if request.query_string:
        url = url + "?" + request.query_string.decode()
    return redirect(url)

# 获取排序游戏图片列表接口


@app.route("/api/getSequencingImages")
def get_sequencing_images():
    """获取排序游戏图片列表 - 按物品分组，包含大小关系"""
    from pathlib import Path
    import re
    from app.dialogue.image_semantics import ordering_object_name
    
    category = request.args.get("category", "size")
    
    # 类别映射
    category_map = {
        'size': 'BigSmall',
        'length': 'LongShort', 
        'height': 'TallShort',
        'count': 'MoreLess'
    }
    folder_name = category_map.get(category, category)
    
    img_dir = Path(app.static_folder) / "resources" / "images" / "paixu" / folder_name
    
    if not img_dir.exists():
        return jsonify({"error": f"图片目录不存在: {img_dir}"}), 404
    
    # 按前缀分组
    groups = {}
    for f in img_dir.iterdir():
        if f.suffix.lower() in ('.png', '.jpg', '.jpeg') and f.name != 'Background.png':
            # 提取前缀和数字: Circle1.png -> ('Circle', 1)
            match = re.match(r'(.+?)(\d+)\.', f.name)
            if match:
                prefix, num = match.group(1), int(match.group(2))
                if prefix not in groups:
                    groups[prefix] = []
                groups[prefix].append({
                    'path': f"/static/resources/images/paixu/{folder_name}/{f.name}",
                    'level': num,  # 数字越大表示越大/长/多/高
                    'prefix': prefix,
                    'label': ordering_object_name(prefix),
                })
    
    # 对每组按 level 排序
    for prefix in groups:
        groups[prefix].sort(key=lambda x: x['level'])
    
    return jsonify({"groups": groups, "category": category})


@app.route("/api/getMatchingImages")
def get_matching_images():
    """获取配对游戏图片列表 - 每个子文件夹随机取一张图；含根目录单图。"""
    from pathlib import Path
    import random as rand_module
    from app.dialogue.image_semantics import matching_semantic_from_src
    
    img_dir = Path(app.static_folder) / "resources" / "images" / "matching"
    if not img_dir.exists():
        return jsonify({"error": f"图片目录不存在: {img_dir}"}), 404
    
    images = []
    # 根目录单图（image_1.jpg 等）
    for f in sorted(img_dir.iterdir()):
        if f.is_file() and f.suffix.lower() in ('.png', '.jpg', '.jpeg'):
            src = f"/static/resources/images/matching/{f.name}"
            sem = matching_semantic_from_src(src)
            images.append({
                "src": src,
                "label": sem["label"],
                "description": sem.get("description") or sem["label"],
            })
    # 遍历子文件夹，每个子文件夹代表一个"物品类别"
    for subfolder in sorted(img_dir.iterdir()):
        if subfolder.is_dir():
            files = [f for f in subfolder.iterdir() 
                     if f.is_file() and f.suffix.lower() in ('.png', '.jpg', '.jpeg')]
            if files:
                selected = rand_module.choice(files)
                src = f"/static/resources/images/matching/{subfolder.name}/{selected.name}"
                sem = matching_semantic_from_src(src)
                images.append({
                    "src": src,
                    "label": sem["label"],
                    "description": sem.get("description") or sem["label"],
                })
    
    # 兼容旧客户端：仍提供纯路径数组
    return jsonify({
        "images": [item["src"] for item in images],
        "items": images,
    })

# 保存游戏结果接口


@app.route("/api/saveResult", methods=["POST"])
def save_result():
    """接收排序游戏结果"""
    data = request.get_json()
    print("收到结果：", data)

    # 可以将数据保存到数据库或文件中
    save_dir = os.path.join(app.static_folder, "logs")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, "sequencing_results.json")

    # 保存结果到 JSON 文件
    try:
        with open(save_path, "a", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            f.write("\n")
        return jsonify({"message": "结果已保存！"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==================== 教师登录相关API ====================

@app.route("/api/teacher/login", methods=["POST"])
def teacher_login():
    """教师登录接口"""
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({"error": "用户名和密码不能为空"}), 400
        
        # 查询教师账户
        teacher = Teacher.query.filter_by(username=username).first()
        
        if not teacher:
            return jsonify({"error": "用户名或密码错误"}), 401
        
        if not teacher.is_active:
            return jsonify({"error": "账户已被禁用"}), 403
        
        # 验证密码
        if not teacher.check_password(password):
            return jsonify({"error": "用户名或密码错误"}), 401
        
        # 更新最后登录时间
        teacher.last_login = datetime.utcnow()
        db.session.commit()

        # Socket.IO shares this signed Flask session. Never trust the teacher
        # object cached by the browser as authorization state.
        session['teacher_id'] = teacher.id
        session['teacher_username'] = teacher.username
        session.permanent = True
        
        # 返回成功信息（不包含密码）
        return jsonify({
            "success": True,
            "message": "登录成功",
            "teacher": teacher.to_dict()
        }), 200
        
    except Exception as e:
        return jsonify({"error": f"登录失败: {str(e)}"}), 500


@app.route("/api/teacher/session", methods=["GET"])
def teacher_session_status():
    """Return the server-authenticated teacher for refresh/reconnect recovery."""
    teacher_id = session.get('teacher_id')
    if not teacher_id:
        return jsonify({"authenticated": False, "teacher": None}), 401
    teacher = db.session.get(Teacher, teacher_id)
    if teacher is None or not teacher.is_active:
        session.pop('teacher_id', None)
        session.pop('teacher_username', None)
        return jsonify({"authenticated": False, "teacher": None}), 401
    return jsonify({
        "authenticated": True,
        "teacher": teacher.to_dict(),
    }), 200


@app.route("/api/teacher/logout", methods=["POST"])
def teacher_logout():
    session.pop('teacher_id', None)
    session.pop('teacher_username', None)
    return jsonify({"success": True}), 200


@app.route("/api/training/finalize-beacon", methods=["POST"])
def finalize_training_beacon():
    """Reliable page-unload fallback for stopping a classroom recording.

    Socket.IO emits are not guaranteed during tab/window teardown. This route
    accepts only the authenticated teacher's request and delegates to the
    same idempotent finalizer used by the normal report flow.
    """
    if not session.get('teacher_id'):
        return jsonify({'success': False, 'error': 'teacher_auth_required'}), 401
    payload = request.get_json(silent=True) or {}
    training_id = payload.get('trainingSessionId') or payload.get('training_session_id')
    if not training_id:
        return jsonify({'success': False, 'error': 'missing_training_session_id'}), 400
    payload = dict(payload)
    payload['trainingSessionId'] = str(training_id)
    payload.setdefault('operationId', f"teacher-leave:{training_id}")
    payload.setdefault('requestId', payload['operationId'])
    try:
        from app.sockets.handlers import FinalizeTrainingHandler
        result = FinalizeTrainingHandler.handle(payload)
        if result.get('success'):
            from app.services.readiness_service import get_readiness_service
            get_readiness_service().cancel(training_session_id=str(training_id))
        for stopped_session_id in result.get('stoppedRuntimeSessions') or []:
            socketio.emit('stop_recording', {
                'sessionId': stopped_session_id,
                'trainingSessionId': str(training_id),
                'reason': 'teacher_leave_control',
                'operationId': payload['operationId'],
            }, room=f'session_{stopped_session_id}_child')
        return jsonify(result), 200 if result.get('success') else 409
    except Exception as exc:
        logger.error('finalize_training_beacon failed: %s', exc, exc_info=True)
        return jsonify({'success': False, 'error': str(exc)}), 500


@app.route("/api/teacher/register", methods=["POST"])
def teacher_register():
    """教师注册接口（可选，用于添加新教师账户）"""
    try:
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        real_name = data.get('real_name')
        email = data.get('email')
        phone = data.get('phone')
        
        if not username or not password:
            return jsonify({"error": "用户名和密码不能为空"}), 400
        
        # 检查用户名是否已存在
        if Teacher.query.filter_by(username=username).first():
            return jsonify({"error": "用户名已存在"}), 400
        
        # 创建新教师账户
        teacher = Teacher(
            username=username,
            real_name=real_name,
            email=email,
            phone=phone,
            is_active=True
        )
        teacher.set_password(password)
        
        db.session.add(teacher)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "注册成功",
            "teacher": teacher.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"注册失败: {str(e)}"}), 500


@app.route("/api/teacher/list", methods=["GET"])
def teacher_list():
    """获取教师列表（可选，用于管理）"""
    try:
        teachers = Teacher.query.all()
        return jsonify({
            "success": True,
            "teachers": [teacher.to_dict() for teacher in teachers]
        }), 200
    except Exception as e:
        return jsonify({"error": f"获取列表失败: {str(e)}"}), 500


# ==================== 学生信息相关API ====================

@app.route("/api/students", methods=["GET"])
def get_students():
    """获取学生列表"""
    try:
        students = Student.query.order_by(Student.created_at.desc()).all()
        return jsonify({
            "success": True,
            "students": [student.to_dict() for student in students]
        }), 200
    except Exception as e:
        return jsonify({"error": f"获取学生列表失败: {str(e)}"}), 500


@app.route("/api/students", methods=["POST"])
def create_student():
    """创建新学生"""
    try:
        data = request.get_json()
        name = data.get('name')
        age = data.get('age')
        preference = data.get('preference')
        teacher = data.get('teacher')
        screening = data.get('screening')
        avatar = data.get('avatar')  # 可以是URL或base64
        
        # 验证必填字段
        if not name:
            return jsonify({"error": "姓名不能为空"}), 400
        if age is None:
            return jsonify({"error": "年龄不能为空"}), 400
        
        # 创建新学生
        student = Student(
            name=name,
            age=age,
            preference=preference,
            teacher=teacher,
            screening=screening,
            avatar=avatar
        )
        
        db.session.add(student)
        db.session.commit()
        
        return jsonify({
            "success": True,
            "message": "学生创建成功",
            "student": student.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"创建学生失败: {str(e)}"}), 500


@app.route("/api/students/<int:student_id>", methods=["GET"])
def get_student_detail(student_id):
    """获取学生详细信息（包含能力数据和训练数据）"""
    try:
        student = Student.query.get(student_id)
        if not student:
            return jsonify({"error": "学生不存在"}), 404

        # 获取学生基本信息
        student_data = student.to_dict()

        # 获取最新的能力数据（从最新的训练记录中获取）
        latest_session = TrainingSession.query.filter_by(
            student_id=student_id
        ).order_by(desc(TrainingSession.date),
                   desc(TrainingSession.created_at)).first()

        abilities = []
        if latest_session:
            ability_items = AbilityItem.query.filter_by(
                training_session_id=latest_session.id
            ).all()
            for item in ability_items:
                abilities.append({
                    'subject': item.ability_type.name
                    if item.ability_type else None,
                    'score': item.score
                })
        # 无训练记录时返回空数组，避免全 0 伪装成已评估

        student_data['abilities'] = abilities
        student_data['has_training'] = latest_session is not None
        student_data['latest_behavior_session_id'] = (
            latest_session.behavior_session_id if latest_session else None
        )
        student_data['imitation_placeholder'] = True

        # 获取训练数据（最近30天的训练次数统计）
        training_sessions = TrainingSession.query.filter_by(
            student_id=student_id
        ).order_by(desc(TrainingSession.date)).limit(30).all()

        # 统计每天的训练次数
        training_data = {}
        for session in training_sessions:
            date_str = session.date.strftime('%m/%d') if session.date else None
            if date_str:
                if date_str not in training_data:
                    training_data[date_str] = 0
                # 统计该次训练中所有课程的训练次数总和
                details = TrainingDetail.query.filter_by(
                    training_session_id=session.id
                ).all()
                total_count = sum(detail.count for detail in details)
                training_data[date_str] += total_count

        # 转换为前端需要的格式（最近7天）
        training_data_list = [
            {'date': date_str, 'count': count}
            for date_str, count in sorted(
                training_data.items(), reverse=True)[:7]
        ]

        student_data['trainingData'] = training_data_list

        return jsonify({
            "success": True,
            "student": student_data
        }), 200

    except Exception as e:
        return jsonify({"error": f"获取学生详情失败: {str(e)}"}), 500


@app.route("/api/students/<int:student_id>/abilities", methods=["GET"])
def get_student_abilities(student_id):
    """获取学生的能力数据（历史记录，按时间升序便于趋势图）"""
    try:
        student = Student.query.get(student_id)
        if not student:
            return jsonify({"error": "学生不存在"}), 404

        sessions = TrainingSession.query.filter_by(
            student_id=student_id
        ).order_by(
            TrainingSession.date.asc(),
            TrainingSession.created_at.asc(),
        ).all()

        abilities_history = []
        for session in sessions:
            ability_items = AbilityItem.query.filter_by(
                training_session_id=session.id
            ).all()

            session_abilities = {
                'date': session.date.isoformat() if session.date else None,
                'behavior_session_id': session.behavior_session_id,
                'abilities': []
            }

            for item in ability_items:
                session_abilities['abilities'].append({
                    'subject': item.ability_type.name
                    if item.ability_type else None,
                    'score': item.score
                })

            if session_abilities['abilities']:
                abilities_history.append(session_abilities)

        return jsonify({
            "success": True,
            "abilities_history": abilities_history
        }), 200

    except Exception as e:
        return jsonify({"error": f"获取能力数据失败: {str(e)}"}), 500


@app.route("/api/students/<int:student_id>/training-sessions",
           methods=["GET"])
def get_student_training_sessions(student_id):
    """获取学生的训练记录列表（按次，含 behavior UUID 以便跳转报告）"""
    try:
        student = Student.query.get(student_id)
        if not student:
            return jsonify({"error": "学生不存在"}), 404

        # 获取分页参数
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)

        sessions = TrainingSession.query.filter_by(
            student_id=student_id
        ).order_by(desc(TrainingSession.date),
                   desc(TrainingSession.created_at)).paginate(
            page=page, per_page=per_page, error_out=False
        )

        sessions_data = []
        for session in sessions.items:
            session_dict = session.to_dict()

            # 获取训练详情
            details = TrainingDetail.query.filter_by(
                training_session_id=session.id
            ).all()
            session_dict['training_details'] = [
                detail.to_dict() for detail in details
            ]

            # 获取能力项
            ability_items = AbilityItem.query.filter_by(
                training_session_id=session.id
            ).all()
            session_dict['ability_items'] = [
                item.to_dict() for item in ability_items
            ]

            sessions_data.append(session_dict)

        return jsonify({
            "success": True,
            "sessions": sessions_data,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": sessions.total,
                "pages": sessions.pages
            }
        }), 200

    except Exception as e:
        return jsonify({"error": f"获取训练记录失败: {str(e)}"}), 500


@app.route("/api/students/<int:student_id>/latest-intervention",
           methods=["GET"])
def get_student_latest_intervention(student_id):
    """获取该儿童最新一次报告中的干预建议摘要"""
    try:
        student = Student.query.get(student_id)
        if not student:
            return jsonify({"error": "学生不存在"}), 404

        summary = (
            TrainingReportSummary.query
            .filter_by(student_id=student_id)
            .order_by(desc(TrainingReportSummary.updated_at))
            .first()
        )
        if not summary:
            return jsonify({
                "success": True,
                "data": None,
            }), 200

        session = TrainingSession.query.get(summary.training_session_id)
        data = summary.to_dict()
        data['report_status'] = session.report_status if session else None
        data['generated_at'] = (
            session.report_generated_at.isoformat() + 'Z'
            if session and session.report_generated_at else data.get('updated_at')
        )
        data['overall_score'] = session.overall_score if session else None

        return jsonify({
            "success": True,
            "data": data,
        }), 200

    except Exception as e:
        return jsonify({"error": f"获取干预建议失败: {str(e)}"}), 500


@app.route("/api/students/<int:student_id>/reports", methods=["GET"])
def get_student_reports(student_id):
    """获取该儿童历史报告索引列表"""
    try:
        student = Student.query.get(student_id)
        if not student:
            return jsonify({"error": "学生不存在"}), 404

        limit = request.args.get('limit', 20, type=int)
        limit = max(1, min(limit, 100))

        sessions = (
            TrainingSession.query
            .filter(
                TrainingSession.student_id == student_id,
                TrainingSession.behavior_session_id.isnot(None),
            )
            .order_by(
                desc(TrainingSession.report_generated_at),
                desc(TrainingSession.created_at),
            )
            .limit(limit)
            .all()
        )

        reports = []
        for session in sessions:
            reports.append({
                'id': session.id,
                'behavior_session_id': session.behavior_session_id,
                'date': session.date.isoformat() if session.date else None,
                'start_time': (
                    session.start_time.strftime('%H:%M:%S')
                    if session.start_time else None
                ),
                'overall_score': session.overall_score,
                'report_status': session.report_status,
                'report_generated_at': (
                    session.report_generated_at.isoformat() + 'Z'
                    if session.report_generated_at else None
                ),
            })

        return jsonify({
            "success": True,
            "reports": reports,
        }), 200

    except Exception as e:
        return jsonify({"error": f"获取报告列表失败: {str(e)}"}), 500


# ==================== 字典表相关API ====================

@app.route("/api/course-types", methods=["GET"])
def get_course_types():
    """获取课程类型字典表"""
    try:
        course_types = CourseType.query.order_by(CourseType.id).all()
        return jsonify({
            "success": True,
            "course_types": [ct.to_dict() for ct in course_types]
        }), 200
    except Exception as e:
        return jsonify({"error": f"获取课程类型失败: {str(e)}"}), 500


@app.route("/api/ability-types", methods=["GET"])
def get_ability_types():
    """获取能力类型字典表"""
    try:
        ability_types = AbilityType.query.order_by(AbilityType.id).all()
        return jsonify({
            "success": True,
            "ability_types": [at.to_dict() for at in ability_types]
        }), 200
    except Exception as e:
        return jsonify({"error": f"获取能力类型失败: {str(e)}"}), 500




# ==================== 新架构初始化 ====================

def init_app():
    """初始化应用（包括会话管理器清理任务等）"""
    import threading
    import time
    
    def cleanup_sessions_periodically():
        """定期清理过期会话（后台线程）"""
        while True:
            try:
                time.sleep(300)  # 每5分钟清理一次
                cleaned = session_manager.cleanup_expired_sessions()
                if cleaned > 0:
                    logger.info(f"清理了 {cleaned} 个过期会话")
            except Exception as e:
                logger.error(f"清理过期会话时出错: {e}")
    
    # 启动后台清理线程
    cleanup_thread = threading.Thread(target=cleanup_sessions_periodically, daemon=True)
    cleanup_thread.start()
    logger.info("会话清理后台任务已启动")
    
    logger.info("应用初始化完成")


# 应用启动时初始化
init_app()


if __name__ == '__main__':
    # 本地开发：默认一并启动教师端 Vite（可用 START_TEACHER_FRONTEND=0 关闭）
    from app.utils.dev_launcher import start_teacher_frontend
    start_teacher_frontend(logger)

    from app.utils.server_runtime import (
        resolve_server_run_options,
        resolve_ssl_context,
        log_lan_access_hints,
    )
    run_options = resolve_server_run_options()
    ssl_context, ssl_meta = resolve_ssl_context()
    logger.info(
        "后端启动选项: debug=%s use_reloader=%s https=%s",
        run_options["debug"],
        run_options["use_reloader"],
        ssl_meta["enabled"],
    )
    if ssl_meta["enabled"]:
        logger.info("HTTPS 证书: %s", ssl_meta["certfile"])
    log_lan_access_hints(
        logger,
        flask_port=8080,
        vite_port=5173,
        scheme=ssl_meta["scheme"],
    )
    # 必须绑 0.0.0.0：127.0.0.1 仅本机可访问，局域网设备连不上。
    # 热重载默认关闭，避免后台设备与分析进程被重复拉起。
    # HTTPS：ENABLE_HTTPS=true 或 SSL_CERTFILE+SSL_KEYFILE（自签名见 scripts/generate_lan_cert.ps1）。
    run_kwargs = dict(
        host="0.0.0.0",
        port=8080,
        debug=run_options["debug"],
        use_reloader=run_options["use_reloader"],
        allow_unsafe_werkzeug=True,
        # .env 已在文件顶部加载，禁止 Flask 重复扫描和输出提示。
        load_dotenv=False,
    )
    if ssl_context is not None:
        run_kwargs["ssl_context"] = ssl_context
    socketio.run(app, **run_kwargs)
