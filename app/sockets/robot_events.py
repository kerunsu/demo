"""
机械臂 WebSocket 事件处理
处理姿态数据、录制控制、播放控制、表情切换等事件
"""
import random
from flask import request
from flask_socketio import emit

from app.robot import get_robot_service
from app.utils.logger import setup_logger

logger = setup_logger('robot_events')


def register_robot_events(socketio):
    """
    注册机械臂相关的 WebSocket 事件
    
    Args:
        socketio: Flask-SocketIO 实例
    """
    
    @socketio.on('robot_pose_data')
    def handle_pose_data(data):
        """
        处理姿态数据
        
        事件数据格式：
        {
            pitch: float,
            yaw: float,
            armL: float,
            armR: float
        }
        """
        try:
            service = get_robot_service()
            
            # 如果正在录制，添加帧
            if service.is_recording:
                service.add_frame(data)
            
            # 发送实时姿态到机械臂
            service.send_realtime(data)
            
        except Exception as e:
            logger.error(f"处理姿态数据出错: {e}")
    
    @socketio.on('robot_start_recording')
    def handle_start_recording():
        """开始录制"""
        try:
            service = get_robot_service()
            service.start_recording()
            emit('robot_recording_status', {'isRecording': True})
            logger.info("机械臂录制开始")
        except Exception as e:
            logger.error(f"开始录制出错: {e}")
            emit('robot_recording_status', {'isRecording': False, 'error': str(e)})
    
    @socketio.on('robot_stop_recording')
    def handle_stop_recording(data):
        """
        停止录制
        
        事件数据格式：
        {
            motionName: str (可选)
        }
        """
        try:
            motion_name = data.get('motionName') if data else None
            service = get_robot_service()
            result = service.stop_recording(motion_name)
            
            emit('robot_recording_status', {
                'isRecording': False,
                'saved': result['saved'],
                'motionName': result['motionName'],
                'frameCount': result['frameCount']
            })
            logger.info(f"机械臂录制停止: {result['motionName']}, {result['frameCount']} 帧")
        except Exception as e:
            logger.error(f"停止录制出错: {e}")
            emit('robot_recording_status', {'isRecording': False, 'error': str(e)})
    
    @socketio.on('robot_play_motion')
    def handle_play_motion(data):
        """
        播放动作
        
        事件数据格式：
        {
            motionName: str
        }
        """
        try:
            motion_name = data.get('motionName')
            if not motion_name:
                emit('robot_playback_status', {'isPlaying': False, 'error': 'motionName required'})
                return
            
            service = get_robot_service()
            
            def on_complete():
                # 播放完成后发送状态
                socketio.emit('robot_playback_status', {
                    'isPlaying': False,
                    'motionName': motion_name
                })
            
            success = service.play_motion(motion_name, on_complete)
            
            if success:
                emit('robot_playback_status', {'isPlaying': True, 'motionName': motion_name})
            else:
                emit('robot_playback_status', {'isPlaying': False, 'error': 'Failed to play'})
                
        except Exception as e:
            logger.error(f"播放动作出错: {e}")
            emit('robot_playback_status', {'isPlaying': False, 'error': str(e)})
    
    @socketio.on('robot_stop_playback')
    def handle_stop_playback():
        """停止播放"""
        try:
            service = get_robot_service()
            service.stop_playback()
            emit('robot_playback_status', {'isPlaying': False})
            logger.info("机械臂播放停止")
        except Exception as e:
            logger.error(f"停止播放出错: {e}")

    @socketio.on('robot_emotion_ended')
    def handle_robot_emotion_ended(data):
        """Correlate the display's actual terminal with the Server command ledger."""
        payload = data or {}
        command_id = payload.get('behaviorId') or payload.get('sequenceId')
        try:
            status = get_robot_service().mark_expression_terminal(
                command_id,
                status=str(payload.get('status') or 'ended'),
                request_id=payload.get('requestId') or payload.get('request_id'),
                session_id=payload.get('sessionId') or payload.get('session_id'),
                modality=payload.get('modality'),
                reason=payload.get('reason'),
            )
            if status is None:
                logger.debug('忽略未知表情完成回执: %s', command_id)
        except Exception as e:
            logger.error('处理表情完成回执失败: %s', e)

    @socketio.on('robot_emotion_started')
    def handle_robot_emotion_started(data):
        payload = data or {}
        try:
            from app.sockets.events import _record_latency_modality_callback

            _record_latency_modality_callback(
                payload,
                phase='started',
                modality='expression',
                actor='robot_display',
            )
            result = get_robot_service().mark_behavior_modality_started(
                behavior_id=payload.get('behaviorId'),
                request_id=payload.get('requestId'),
                session_id=payload.get('sessionId'),
                modality=payload.get('modality'),
                actual_at_ms=payload.get('actualAtClientMs'),
            )
            if result is None:
                logger.debug('忽略不匹配的表情 started 回执: %s', payload)
        except Exception as e:
            logger.error('处理表情 started 回执失败: %s', e)

    @socketio.on('robot_emotion_ready')
    def handle_robot_emotion_ready(data):
        payload = data or {}
        try:
            from app.sockets.events import _record_latency_modality_callback

            _record_latency_modality_callback(
                payload,
                phase='ready',
                modality='expression',
                actor='robot_display',
            )
            result = get_robot_service().mark_behavior_modality_ready(
                behavior_id=payload.get('behaviorId'),
                request_id=payload.get('requestId'),
                session_id=payload.get('sessionId'),
                modality=payload.get('modality'),
            )
            if result is None:
                logger.debug('忽略不匹配的表情 ready 回执: %s', payload)
        except Exception as e:
            logger.error('处理表情 ready 回执失败: %s', e)
    
    # ========== 表情事件处理 ==========
    
    @socketio.on('robot_emotion_auto_random')
    def handle_emotion_auto_random():
        """
        自动随机切换表情（60秒超时触发）
        """
        try:
            service = get_robot_service()
            busy_state = getattr(service, 'get_behavior_busy_state', None)
            if callable(busy_state):
                state = busy_state() or {}
                if state.get('busy'):
                    logger.info(
                        '繁忙行为期间忽略 robot_emotion_auto_random: active=%s',
                        state.get('eventId'),
                    )
                    return
            emotions = service.get_available_emotions()
            
            if not emotions:
                logger.warning("无可用表情，无法随机切换")
                return
            
            # 随机选择一个表情
            random_emotion = random.choice(emotions)
            logger.info(f"🎲 自动随机表情: {random_emotion}")
            
            # 发送表情切换事件
            service.trigger_emotion(random_emotion)
            
        except Exception as e:
            logger.error(f"自动随机表情出错: {e}")
    
    logger.info("机械臂 WebSocket 事件已注册（包含表情事件）")
