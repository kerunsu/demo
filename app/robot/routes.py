"""
机械臂 REST API 路由
Flask Blueprint 实现
"""
from flask import Blueprint, request, jsonify, send_file

from app.robot import get_robot_service
from app.robot.motion_storage import (
    get_motion_metadata,
    import_dollser_motion_file,
    set_motion_speed,
)
from app.robot.release_package import load_manifest, resolve_zip_path
from app.utils.logger import setup_logger
from app.versioning import version_matrix

logger = setup_logger('robot_routes')

# 创建 Blueprint
robot_bp = Blueprint('robot', __name__, url_prefix='/api/robot')


# ========== 动作管理 API ==========

@robot_bp.route('/motions', methods=['GET'])
def get_motions():
    """获取动作列表"""
    try:
        service = get_robot_service()
        motions = service.get_motion_list()
        return jsonify({'success': True, 'motions': motions})
    except Exception as e:
        logger.error(f"获取动作列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/motions/<path:name>', methods=['GET'])
def get_motion(name):
    """获取动作详情"""
    try:
        service = get_robot_service()
        motion = service.get_motion(name)
        if motion is None:
            return jsonify({'success': False, 'error': 'Motion not found'}), 404
        return jsonify({'success': True, 'motion': motion, 'metadata': get_motion_metadata(name)})
    except Exception as e:
        logger.error(f"获取动作详情失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/motions', methods=['POST'])
def save_motion():
    """保存动作"""
    try:
        data = request.get_json()
        name = data.get('name')
        frames = data.get('frames')
        
        if not name or not frames:
            return jsonify({'success': False, 'error': 'name and frames required'}), 400
        
        service = get_robot_service()
        success = service.save_motion(name, frames)
        
        if success:
            return jsonify({
                'success': True, 
                'message': f'Motion "{name}" saved',
                'frameCount': len(frames)
            })
        else:
            return jsonify({'success': False, 'error': 'Failed to save motion'}), 500
    except Exception as e:
        logger.error(f"保存动作失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/motions/import', methods=['POST'])
def import_motion():
    """上传并导入 v2 dollser-motion JSON 动作文件"""
    temp_path = None
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'file required'}), 400

        upload_file = request.files['file']
        if not upload_file or not upload_file.filename:
            return jsonify({'success': False, 'error': 'file required'}), 400

        import tempfile
        import os

        with tempfile.NamedTemporaryFile(delete=False, suffix='.json') as tmp:
            upload_file.save(tmp.name)
            temp_path = tmp.name

        motion_name = request.form.get('motionName') or None
        imported_name = import_dollser_motion_file(temp_path, motion_name)

        return jsonify({
            'success': True,
            'message': f'Motion "{imported_name}" imported',
            'motionName': imported_name
        })
    except ValueError as e:
        logger.error(f"导入动作格式错误: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"导入动作失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if temp_path:
            try:
                import os
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass


@robot_bp.route('/motions/<path:name>', methods=['DELETE'])
def delete_motion(name):
    """删除动作"""
    try:
        service = get_robot_service()
        success = service.delete_motion(name)
        
        if success:
            return jsonify({'success': True, 'message': f'Motion "{name}" deleted'})
        else:
            return jsonify({'success': False, 'error': 'Motion not found'}), 404
    except Exception as e:
        logger.error(f"删除动作失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/play/<path:name>', methods=['POST'])
def play_motion(name):
    """播放动作"""
    try:
        service = get_robot_service()
        success = service.play_motion(name)
        
        if success:
            return jsonify({'success': True, 'message': f'Playing motion "{name}"'})
        else:
            return jsonify({'success': False, 'error': 'Failed to play motion'}), 400
    except Exception as e:
        logger.error(f"播放动作失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/stop', methods=['POST'])
def stop_playback():
    """停止播放"""
    try:
        service = get_robot_service()
        stopped = bool(service.stop_playback())
        return jsonify({
            'success': stopped,
            'message': 'Playback stop command sent' if stopped else 'Playback stop command failed',
        }), 200 if stopped else 502
    except Exception as e:
        logger.error(f"停止播放失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 映射配置 API ==========

@robot_bp.route('/mapping/full', methods=['GET'])
def get_full_mapping():
    """获取完整映射配置"""
    try:
        service = get_robot_service()
        mapping = service.get_full_mapping()
        return jsonify({'success': True, 'mapping': mapping})
    except Exception as e:
        logger.error(f"获取映射配置失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/mapping/idle', methods=['PUT'])
def set_idle_pose():
    """设置静态姿势"""
    try:
        data = request.get_json()
        motion_name = data.get('motionName')
        
        if not motion_name:
            return jsonify({'success': False, 'error': 'motionName required'}), 400
        
        service = get_robot_service()
        service.set_idle_pose(motion_name)
        return jsonify({'success': True, 'message': f'Idle pose set to "{motion_name}"'})
    except Exception as e:
        logger.error(f"设置静态姿势失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/mapping/defaults/<aux_type>', methods=['PUT'])
def update_default_motions(aux_type):
    """更新通用动作"""
    try:
        if aux_type not in [
            'praise', 'hint', 'question', 'silent',
            'social_greeting_intro', 'social_greeting_play',
            'social_farewell_bye', 'social_farewell_reply',
        ]:
            return jsonify({'success': False, 'error': 'Invalid auxType'}), 400
        
        data = request.get_json()
        motions = data.get('motions')
        emotion = data.get('emotion')  # 新增：获取表情字段
        sequence = data.get('sequence')
        animation = data.get('animation')
        
        if not isinstance(motions, list):
            return jsonify({'success': False, 'error': 'motions must be an array'}), 400
        
        service = get_robot_service()
        service.update_default_motions(aux_type, motions, emotion, sequence, animation)
        return jsonify({
            'success': True, 
            'message': f'Default {aux_type} motions updated',
            'count': len(motions),
            'emotion': emotion,
            'sequence': sequence,
            'animation': animation,
        })
    except Exception as e:
        logger.error(f"更新通用动作失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/mapping/defaults/<aux_type>', methods=['DELETE'])
def delete_default_motions(aux_type):
    """删除通用动作"""
    try:
        service = get_robot_service()
        service.delete_default_motions(aux_type)
        return jsonify({'success': True, 'message': f'Default {aux_type} motions deleted'})
    except Exception as e:
        logger.error(f"删除通用动作失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/mapping/course/<int:course_id>/<aux_type>', methods=['PUT'])
def update_course_motions(course_id, aux_type):
    """更新课程级动作"""
    try:
        data = request.get_json()
        motions = data.get('motions')
        emotion = data.get('emotion')  # 新增：获取表情字段
        sequence = data.get('sequence')
        animation = data.get('animation')
        
        if not isinstance(motions, list):
            return jsonify({'success': False, 'error': 'motions must be an array'}), 400
        
        service = get_robot_service()
        service.update_course_motions(course_id, aux_type, motions, emotion, sequence, animation)
        return jsonify({
            'success': True,
            'message': f'Course {course_id} {aux_type} motions updated',
            'count': len(motions),
            'emotion': emotion,
            'sequence': sequence,
            'animation': animation,
        })
    except Exception as e:
        logger.error(f"更新课程级动作失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/mapping/course/<int:course_id>/<aux_type>', methods=['DELETE'])
def delete_course_motions(course_id, aux_type):
    """删除课程级动作"""
    try:
        service = get_robot_service()
        service.delete_course_motions(course_id, aux_type)
        return jsonify({'success': True, 'message': f'Course {course_id} {aux_type} motions deleted'})
    except Exception as e:
        logger.error(f"删除课程级动作失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/mapping/student/<int:student_id>/course/<int:course_id>/<aux_type>', methods=['PUT'])
def update_student_course_motions(student_id, course_id, aux_type):
    """更新学生-课程级动作"""
    try:
        data = request.get_json()
        motions = data.get('motions')
        emotion = data.get('emotion')  # 新增：获取表情字段
        sequence = data.get('sequence')
        animation = data.get('animation')
        
        if not isinstance(motions, list):
            return jsonify({'success': False, 'error': 'motions must be an array'}), 400
        
        service = get_robot_service()
        service.update_student_course_motions(student_id, course_id, aux_type, motions, emotion, sequence, animation)
        return jsonify({
            'success': True,
            'message': f'Student {student_id} course {course_id} {aux_type} motions updated',
            'count': len(motions),
            'emotion': emotion,
            'sequence': sequence,
            'animation': animation,
        })
    except Exception as e:
        logger.error(f"更新学生-课程级动作失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/mapping/student/<int:student_id>/course/<int:course_id>/<aux_type>', methods=['DELETE'])
def delete_student_course_motions(student_id, course_id, aux_type):
    """删除学生-课程级动作"""
    try:
        service = get_robot_service()
        service.delete_student_course_motions(student_id, course_id, aux_type)
        return jsonify({
            'success': True, 
            'message': f'Student {student_id} course {course_id} {aux_type} motions deleted'
        })
    except Exception as e:
        logger.error(f"删除学生-课程级动作失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/mapping/item/<int:student_id>/<int:course_id>/<int:item_id>/<aux_type>', methods=['PUT'])
def update_item_motions(student_id, course_id, item_id, aux_type):
    """更新项目级动作"""
    try:
        data = request.get_json()
        motions = data.get('motions')
        emotion = data.get('emotion')  # 新增：获取表情字段
        sequence = data.get('sequence')
        animation = data.get('animation')
        
        if not isinstance(motions, list):
            return jsonify({'success': False, 'error': 'motions must be an array'}), 400
        
        service = get_robot_service()
        service.update_item_motions(student_id, course_id, item_id, aux_type, motions, emotion, sequence, animation)
        return jsonify({
            'success': True,
            'message': f'Item level {aux_type} motions updated',
            'count': len(motions),
            'emotion': emotion,
            'sequence': sequence,
            'animation': animation,
        })
    except Exception as e:
        logger.error(f"更新项目级动作失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/mapping/item/<int:student_id>/<int:course_id>/<int:item_id>/<aux_type>', methods=['DELETE'])
def delete_item_motions(student_id, course_id, item_id, aux_type):
    """删除项目级动作"""
    try:
        service = get_robot_service()
        service.delete_item_motions(student_id, course_id, item_id, aux_type)
        return jsonify({'success': True, 'message': f'Item level {aux_type} motions deleted'})
    except Exception as e:
        logger.error(f"删除项目级动作失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 课程触发 API ==========

@robot_bp.route('/course-event', methods=['POST'])
def trigger_course_event():
    """
    触发课程事件（供外部/内部调用）
    
    请求体：
    {
        "action": "play",
        "studentId": 101,
        "courseId": 1,
        "itemId": 1,
        "aux": {"question": false, "praise": true, "hint": false}
    }
    """
    try:
        data = request.get_json()
        
        if not data.get('courseId'):
            return jsonify({'success': False, 'error': 'courseId required'}), 400
        
        service = get_robot_service()
        result = service.trigger_course_event(data)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 404
    except Exception as e:
        logger.error(f"触发课程事件失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/sequence/preview', methods=['POST'])
def preview_behavior_sequence():
    """控制端试播完整表情/动作/语音序列（会驱动已连接的真机）。"""
    try:
        data = request.get_json(silent=True) or {}
        if not isinstance(data.get('motions'), list):
            return jsonify({'success': False, 'error': 'motions must be an array'}), 400
        result = get_robot_service().preview_behavior_sequence(data)
        return jsonify(result), 200 if result.get('success') else 400
    except Exception as e:
        logger.error('试播行为序列失败: %s', e)
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/sequence/status/<command_id>', methods=['GET'])
def behavior_sequence_status(command_id: str):
    """Return the accepted plan's real scheduler/component lifecycle."""
    try:
        status = get_robot_service().get_command_status(command_id)
        if status is None:
            return jsonify({
                'success': False,
                'error': 'command_not_found',
                'commandId': command_id,
            }), 404
        return jsonify({'success': True, 'status': status})
    except Exception as e:
        logger.error('读取行为命令状态失败: %s', e)
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/control/status', methods=['GET'])
def robot_control_status():
    """Operator snapshot for configured transport, live targets and command truth."""
    try:
        return jsonify({
            'success': True,
            'control': get_robot_service().get_control_snapshot(),
        })
    except Exception as e:
        logger.error('读取机器人控制状态失败: %s', e)
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 基础数据 API ==========

@robot_bp.route('/students', methods=['GET'])
def get_students():
    """获取学生列表"""
    try:
        service = get_robot_service()
        students = service.get_students()
        return jsonify({'success': True, 'students': students})
    except Exception as e:
        logger.error(f"获取学生列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/courses', methods=['GET'])
def get_courses():
    """获取课程列表"""
    try:
        service = get_robot_service()
        courses = service.get_courses()
        return jsonify({'success': True, 'courses': courses})
    except Exception as e:
        logger.error(f"获取课程列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== 表情管理 API ==========

@robot_bp.route('/emotions', methods=['GET'])
def get_emotions():
    """获取所有可用表情列表（含默认与引用计数）"""
    try:
        service = get_robot_service()
        payload = service.get_emotions_payload()
        return jsonify({'success': True, **payload})
    except Exception as e:
        logger.error(f"获取表情列表失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/emotions/default', methods=['GET'])
def get_default_emotion():
    """获取默认表情（持久化）"""
    try:
        service = get_robot_service()
        return jsonify({'success': True, 'emotion': service.get_default_emotion()})
    except Exception as e:
        logger.error(f"获取默认表情失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/emotions/default', methods=['PUT'])
def put_default_emotion():
    """设置默认表情"""
    try:
        data = request.get_json() or {}
        emotion = data.get('emotion')
        if not emotion:
            return jsonify({'success': False, 'error': 'emotion required'}), 400
        service = get_robot_service()
        name = service.set_default_emotion(emotion)
        return jsonify({'success': True, 'emotion': name})
    except FileNotFoundError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"设置默认表情失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/emotions/global-filter', methods=['GET', 'PUT'])
def emotion_global_filter():
    """读取或更新应用于全部表情媒体的环境光滤镜。"""
    try:
        service = get_robot_service()
        if request.method == 'GET':
            return jsonify({
                'success': True,
                'globalFilter': service.get_global_emotion_filter(),
            })
        result = service.set_global_emotion_filter(request.get_json(silent=True))
        service.trigger_emotion(
            service.get_default_emotion(),
            settingsOnly=True,
            globalFilter=result,
        )
        return jsonify({'success': True, 'globalFilter': result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"更新全局表情滤镜失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/emotions/<name>/style', methods=['GET', 'PUT'])
def emotion_style(name: str):
    """读取或更新单个表情的播放与显示参数。"""
    try:
        service = get_robot_service()
        if name not in service.get_available_emotions():
            return jsonify({'success': False, 'error': 'Emotion not found'}), 404
        if request.method == 'GET':
            return jsonify({'success': True, 'style': service.get_emotion_style(name)})
        result = service.set_emotion_style(name, request.get_json(silent=True))
        service.trigger_emotion(name, settingsOnly=True, style=result)
        return jsonify({'success': True, 'style': result})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"更新表情参数失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/emotions/upload', methods=['POST'])
def upload_emotion():
    """上传新的 MP4 表情到 Emotions/；历史 GIF 只读兼容。"""
    try:
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'file required'}), 400
        f = request.files['file']
        if not f or not f.filename:
            return jsonify({'success': False, 'error': 'empty filename'}), 400
        raw = f.read()
        service = get_robot_service()
        result = service.upload_emotion(f.filename, raw)
        return jsonify({
            'success': True,
            'emotion': result['name'],
            'optimization': result,
        }), 201
    except FileExistsError as e:
        return jsonify({'success': False, 'error': str(e)}), 409
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"上传表情失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/emotions/<name>', methods=['DELETE'])
def delete_emotion(name: str):
    """删除表情；有引用时需 force=1"""
    try:
        force = request.args.get('force', '').lower() in ('1', 'true', 'yes')
        if request.is_json:
            body = request.get_json(silent=True) or {}
            force = force or bool(body.get('force'))
        service = get_robot_service()
        service.delete_emotion(name, force=force)
        return jsonify({'success': True, 'deleted': name})
    except PermissionError as e:
        from app.robot.emotion_assets import find_emotion_references
        refs = find_emotion_references(name)
        return jsonify({
            'success': False,
            'error': str(e),
            'referencedBy': refs,
            'hint': '加 ?force=1 强制删除',
        }), 409
    except FileNotFoundError as e:
        return jsonify({'success': False, 'error': str(e)}), 404
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"删除表情失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/emotions/trigger', methods=['POST'])
def trigger_emotion():
    """手动触发表情切换"""
    try:
        data = request.get_json()
        emotion = data.get('emotion')
        
        if not emotion:
            return jsonify({'success': False, 'error': 'emotion required'}), 400
        
        service = get_robot_service()
        success = service.trigger_emotion(emotion)
        
        if success:
            return jsonify({'success': True, 'message': f'Emotion "{emotion}" triggered'})
        else:
            return jsonify({'success': False, 'error': 'Failed to trigger emotion'}), 500
    except Exception as e:
        logger.error(f"触发表情失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@robot_bp.route('/motions/<path:name>/playback', methods=['GET', 'PUT'])
def motion_playback_settings(name):
    """读取或设置单个动作的播放速度倍率。"""
    try:
        service = get_robot_service()
        if service.get_motion(name) is None:
            return jsonify({'success': False, 'error': 'Motion not found'}), 404
        if request.method == 'GET':
            return jsonify({'success': True, 'playback': {
                'speedMultiplier': get_motion_metadata(name)['speedMultiplier'],
            }})
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or set(data) != {'speedMultiplier'}:
            return jsonify({
                'success': False,
                'error': 'body must contain only speedMultiplier',
            }), 400
        metadata = set_motion_speed(name, data.get('speedMultiplier'))
        return jsonify({'success': True, 'playback': {
            'speedMultiplier': metadata['speedMultiplier'],
        }})
    except ValueError as e:
        return jsonify({'success': False, 'error': str(e)}), 400
    except Exception as e:
        logger.error(f"更新动作倍率失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ========== Encouragement animation library API ==========

@robot_bp.route('/animations', methods=['GET'])
def get_animations():
    try:
        return jsonify({'success': True, **get_robot_service().get_animations_payload()})
    except Exception as exc:
        logger.error('Failed to list encouragement animations: %s', exc)
        return jsonify({'success': False, 'error': str(exc)}), 500


@robot_bp.route('/animations/upload', methods=['POST'])
def upload_animation():
    try:
        upload = request.files.get('file')
        if upload is None or not upload.filename:
            return jsonify({'success': False, 'error': 'file required'}), 400
        result = get_robot_service().upload_animation(upload.filename, upload.read())
        return jsonify({
            'success': True,
            'animation': result['name'],
            'optimization': result,
        }), 201
    except FileExistsError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 409
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:
        logger.error('Failed to upload encouragement animation: %s', exc)
        return jsonify({'success': False, 'error': str(exc)}), 500


@robot_bp.route('/animations/<path:name>/rename', methods=['PUT'])
def rename_animation(name: str):
    try:
        data = request.get_json(silent=True) or {}
        new_name = data.get('newName')
        if not isinstance(new_name, str) or not new_name.strip():
            return jsonify({'success': False, 'error': 'newName required'}), 400
        result = get_robot_service().rename_animation(name, new_name)
        return jsonify({'success': True, **result})
    except FileExistsError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 409
    except FileNotFoundError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 404
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:
        logger.error('Failed to rename encouragement animation: %s', exc)
        return jsonify({'success': False, 'error': str(exc)}), 500


@robot_bp.route('/animations/<path:name>', methods=['DELETE'])
def delete_animation(name: str):
    try:
        force = request.args.get('force', '').lower() in ('1', 'true', 'yes')
        get_robot_service().delete_animation(name, force=force)
        return jsonify({'success': True, 'deleted': name})
    except PermissionError as exc:
        from app.robot.animation_assets import find_animation_references
        return jsonify({
            'success': False,
            'error': str(exc),
            'referencedBy': find_animation_references(name),
        }), 409
    except FileNotFoundError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 404
    except ValueError as exc:
        return jsonify({'success': False, 'error': str(exc)}), 400
    except Exception as exc:
        logger.error('Failed to delete encouragement animation: %s', exc)
        return jsonify({'success': False, 'error': str(exc)}), 500


# ========== Robot Runtime 注册 ==========

def _check_runtime_key() -> bool:
    from app.robot.config import ROBOT_RUNTIME_KEY
    if not ROBOT_RUNTIME_KEY:
        return True
    provided = (
        request.headers.get('X-Robot-Runtime-Key')
        or request.headers.get('X-Child-Media-Agent-Key')
        or ''
    )
    return provided == ROBOT_RUNTIME_KEY


@robot_bp.route('/runtime/register', methods=['POST'])
def runtime_register():
    """机器人端 Runtime 上报可达地址。"""
    if not _check_runtime_key():
        return jsonify({'ok': False, 'success': False, 'error': 'unauthorized'}), 401
    try:
        from app.robot.runtime_registry import register_runtime
        data = request.get_json(silent=True) or {}
        advertised = data.get('advertisedUrl')
        if not advertised:
            return jsonify({'ok': False, 'success': False, 'error': 'advertisedUrl required'}), 400
        record = register_runtime(
            advertised,
            port=data.get('port'),
            capabilities=data.get('capabilities'),
            meta={k: v for k, v in data.items() if k not in ('advertisedUrl', 'port', 'capabilities')},
        )
        # 告诉 Runtime 可用的后端公网/局域网基址（供 UI 拼 /child 链接）
        backend_public = request.host_url.rstrip('/')
        logger.info("Robot Runtime 已注册: %s", advertised)
        return jsonify({
            'ok': True,
            'success': True,
            'runtime': record,
            'backendPublicUrl': backend_public,
            'versionMatrix': version_matrix(record),
        })
    except Exception as e:
        logger.error("Runtime 注册失败: %s", e)
        return jsonify({'ok': False, 'success': False, 'error': str(e)}), 500


@robot_bp.route('/runtime/heartbeat', methods=['POST'])
def runtime_heartbeat():
    if not _check_runtime_key():
        return jsonify({'ok': False, 'success': False, 'error': 'unauthorized'}), 401
    try:
        from app.robot.runtime_registry import heartbeat_runtime
        data = request.get_json(silent=True) or {}
        ok = heartbeat_runtime(data.get('advertisedUrl'))
        return jsonify({'ok': ok, 'success': ok})
    except Exception as e:
        return jsonify({'ok': False, 'success': False, 'error': str(e)}), 500


@robot_bp.route('/runtime/behavior/event', methods=['POST'])
def runtime_behavior_event():
    """Receive a correlated started/terminal event from Robot Runtime."""
    if not _check_runtime_key():
        return jsonify({'ok': False, 'success': False, 'error': 'unauthorized'}), 401
    payload = request.get_json(silent=True) or {}
    result = get_robot_service().mark_behavior_motion_event(
        behavior_id=payload.get('behaviorId'),
        request_id=payload.get('requestId'),
        session_id=payload.get('sessionId'),
        modality=payload.get('modality'),
        status=payload.get('status') or payload.get('terminalStatus'),
        reason=payload.get('reason'),
        actual_at_runtime_ms=payload.get('actualAtRuntimeMs'),
    )
    if not result:
        logger.warning('忽略不匹配的 Runtime 行为回执: %s', payload)
        return jsonify({
            'ok': False,
            'success': False,
            'error': 'behavior_event_not_active_or_mismatched',
        }), 409
    return jsonify({'ok': True, 'success': True, **result})


@robot_bp.route('/runtime/status', methods=['GET'])
def runtime_status():
    from app.robot.runtime_registry import get_runtime_status
    return jsonify({'ok': True, 'success': True, **get_runtime_status()})


@robot_bp.route('/runtime/version', methods=['GET'])
def runtime_release_version():
    """当前可下载的机器人端发布包元信息（manifest + zip 是否存在）。"""
    zip_path, meta = resolve_zip_path(load_manifest())
    return jsonify({
        'ok': True,
        'success': True,
        'available': bool(zip_path),
        'version': meta.get('version'),
        'buildVersion': meta.get('buildVersion') or meta.get('version'),
        'protocolVersion': meta.get('protocolVersion'),
        'sourceCommit': meta.get('sourceCommit'),
        'filename': meta.get('resolvedFilename') or meta.get('filename'),
        'latest': meta.get('latest'),
        'sha256': meta.get('sha256'),
        'sizeBytes': meta.get('sizeBytes') or 0,
        'builtAt': meta.get('builtAt'),
        'error': meta.get('error') if not zip_path else None,
        'downloadUrl': '/api/robot/runtime/download',
        'pageUrl': '/robot/download',
    })


@robot_bp.route('/runtime/download', methods=['GET'])
def runtime_release_download():
    """下载机器人端 EIArt-Robot zip（exe + DollSer）。"""
    zip_path, meta = resolve_zip_path(load_manifest())
    if not zip_path:
        return jsonify({
            'ok': False,
            'success': False,
            'available': False,
            'error': meta.get('error') or 'release zip not available',
        }), 404
    download_name = meta.get('resolvedFilename') or zip_path.name
    return send_file(
        zip_path,
        mimetype='application/zip',
        as_attachment=True,
        download_name=download_name,
    )
