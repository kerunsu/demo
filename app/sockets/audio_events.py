"""
语音播放 WebSocket 事件处理器
处理来自儿童端的语音播放状态回调
"""
import time
from typing import Dict, Any
from flask_socketio import SocketIO
from app.audio import get_audio_controller, get_audio_emitter
from app.utils.logger import setup_logger

logger = setup_logger('audio_events')


def register_audio_events(socketio: SocketIO):
    """
    注册语音相关的 WebSocket 事件处理器
    
    Args:
        socketio: Flask-SocketIO 实例
    """
    controller = get_audio_controller()
    
    @socketio.on('play_audio')
    def handle_play_audio_test(data: Dict[str, Any]):
        """
        处理测试页面发送的 play_audio 事件（直接转发）
        
        注意：这是为了测试方便，正常流程中 play_audio 是由服务器端
        AudioEventEmitter 发送的，不需要客户端 emit
        
        事件数据格式:
        {
            'entry_id': str,
            'file_path': str,
            'priority': int (optional),
            'interrupt': bool (optional),
            'room': str (optional, default: broadcast)
        }
        """
        try:
            # 获取目标房间（如果没有指定则广播）
            room = data.get('room')
            
            logger.info(
                f"[测试] 收到 play_audio 请求 - 条目: {data.get('entry_id')}, "
                f"房间: {room or '广播'}"
            )
            
            # 转发到指定房间或广播
            if room:
                socketio.emit('play_audio', data, room=room)
            else:
                socketio.emit('play_audio', data)
            
        except Exception as e:
            logger.error(f"处理 play_audio 测试事件失败: {e}", exc_info=True)
    
    
    @socketio.on('audio_status')
    def handle_audio_status(data: Dict[str, Any]):
        """
        处理来自儿童端的语音播放状态更新
        
        事件数据格式:
        {
            'session_id': str,
            'status': 'playing' | 'paused' | 'stopped' | 'finished' | 'error',
            'entry_id': str,           # 当前播放的语音条目ID
            'file_path': str,          # 实际播放的文件路径
            'current_time': float,     # 当前播放时间（秒）
            'duration': float,         # 音频总时长（秒）
            'error_message': str       # 错误消息（status='error'时）
        }
        """
        try:
            payload = dict(data or {})
            session_id = payload.get('session_id') or payload.get('sessionId')
            if not session_id:
                logger.warning("audio_status 事件缺少 session_id/sessionId 字段")
                return
            session_id = str(session_id)
            status = str(
                payload.get('status') or payload.get('state') or 'unknown'
            ).strip().lower()
            status = {
                'finished': 'ended',
                'complete': 'ended',
                'completed': 'ended',
                'paused': 'stopped',
            }.get(status, status)
            entry_id = (
                payload.get('entry_id')
                or payload.get('entryId')
                or payload.get('audio_id')
                or payload.get('audioId')
            )
            file_path = (
                payload.get('file_path')
                or payload.get('filePath')
                or payload.get('file')
            )
            behavior_id = (
                payload.get('behaviorId')
                or payload.get('behavior_id')
                or payload.get('interactionId')
                or payload.get('sequenceId')
            )
            payload.update({
                'session_id': session_id,
                'sessionId': session_id,
                'status': status,
                'entry_id': entry_id,
                'entryId': entry_id,
                'file_path': file_path,
                'filePath': file_path,
            })
            if behavior_id:
                payload.update({
                    'behaviorId': str(behavior_id),
                    'behavior_id': str(behavior_id),
                    'interactionId': str(behavior_id),
                })

            try:
                from app.sockets.events import (
                    _interaction_context_for_behavior,
                    _record_interaction,
                )

                interaction_context = _interaction_context_for_behavior(behavior_id)
                if interaction_context:
                    event_type = (
                        'question_audio_ended'
                        if status == 'ended'
                        and interaction_context.get('eventType') in (
                            'question_presented', 'hint'
                        )
                        else 'modality_ended'
                        if status == 'ended'
                        else 'modality_failed'
                        if status in ('error', 'stopped', 'dropped', 'timeout')
                        else 'modality_started'
                        if status in ('playing', 'started')
                        else None
                    )
                    if event_type:
                        _record_interaction(
                            event_type,
                            interaction_context,
                            actor='child',
                            degraded=status in ('error', 'stopped', 'dropped', 'timeout'),
                            error=(
                                payload.get('error_message')
                                or payload.get('errorMessage')
                            ),
                            metadata={
                                'modality': 'audio',
                                'status': status,
                                'entryId': entry_id,
                                'filePath': file_path,
                            },
                        )
            except Exception as timeline_error:
                logger.warning('璇煶浜や簰鏃堕棿绾垮啓鍏ュけ璐? %s', timeline_error)
            
            logger.info(
                f"收到语音状态更新 - 会话: {session_id}, "
                f"状态: {status}, "
                f"条目: {entry_id}, "
                f"文件: {file_path}, "
                f"错误: {payload.get('error_message') or payload.get('errorMessage') or '-'}"
            )
            
            # 更新控制器中的播放状态
            if controller:
                controller.on_audio_status(session_id, payload)
            behavior_id = (
                payload.get('behaviorId')
                or payload.get('behavior_id')
                or behavior_id
            )

            # 系统播音期间暂停语音识别，防止提问/提示/表扬被麦克风回采后
            # 误判为儿童回答，再次触发表扬。
            try:
                from app.services import get_analysis_service
                get_analysis_service().update_system_audio_state(
                    session_id,
                    entry_id,
                    status,
                )
            except Exception as gate_error:
                logger.warning("更新系统播音 ASR 门控失败: %s", gate_error)
            
            # 将状态转发给教师端（用于UI显示）
            teacher_room = f"session_{session_id}_teacher"
            
            # 安全计算进度（处理 None 值）
            current_time_raw = (
                payload.get('current_time')
                or payload.get('currentTime')
                or 0
            )
            duration_raw = (
                payload.get('duration')
                or payload.get('durationSeconds')
                or 0
            )
            try:
                current_time = float(current_time_raw)
            except (TypeError, ValueError):
                current_time = 0.0
            try:
                duration = float(duration_raw)
            except (TypeError, ValueError):
                duration = 0.0
            progress = (current_time / duration * 100) if duration > 0 else 0
            
            socketio.emit('audio_status_update', {
                'session_id': session_id,
                'sessionId': session_id,
                'status': status,
                'entry_id': entry_id,
                'entryId': entry_id,
                'file_path': file_path,
                'filePath': file_path,
                'behaviorId': behavior_id,
                'behavior_id': behavior_id,
                'interactionId': behavior_id,
                'progress': progress,
                'error_message': (
                    payload.get('error_message')
                    or payload.get('errorMessage')
                    or ''
                ),
            }, room=teacher_room)
            
        except Exception as e:
            logger.error(f"处理 audio_status 事件失败: {e}", exc_info=True)
    
    
    @socketio.on('stop_audio')
    def handle_stop_audio(data: Dict[str, Any]):
        """
        处理教师端的停止语音播放请求
        
        事件数据格式:
        {
            'session_id': str (optional for test),
            'immediate': bool  # 是否立即停止（true）还是播放完当前音频后停止（false）
        }
        """
        try:
            from flask import request
            from app.sockets.events import (
                _control_rejection,
                _teacher_control_access,
            )

            payload = dict(data or {})
            access = _teacher_control_access(payload)
            if not access.get('ok') or not access.get('writable'):
                socketio.emit(
                    'stop_audio_ack',
                    _control_rejection(access),
                    to=request.sid,
                )
                return

            session_id = payload.get('session_id') or payload.get('sessionId')
            immediate = data.get('immediate', True)
            
            if not session_id:
                socketio.emit('stop_audio_ack', {
                    'success': False,
                    'error': 'session_id_missing',
                    'trainingSessionId': access.get('trainingSessionId'),
                }, to=request.sid)
                return

            from app.robot import get_robot_service

            busy_state = get_robot_service().get_behavior_busy_state() or {}
            if busy_state.get('busy') and not bool(payload.get('emergency')):
                socketio.emit('stop_audio_ack', {
                    'success': False,
                    'error': 'atomic_behavior_busy',
                    'behaviorId': busy_state.get('behaviorId') or busy_state.get('eventId'),
                    'trainingSessionId': access.get('trainingSessionId'),
                }, to=request.sid)
                return
            
            logger.info(
                f"教师请求停止语音播放 - 会话: {session_id}, "
                f"立即停止: {immediate}"
            )
            
            # 通过控制器停止播放（会向儿童端发送 stop_audio 事件）
            controller.stop_audio(session_id, immediate)
            socketio.emit('stop_audio_ack', {
                'success': True,
                'sessionId': session_id,
                'emergency': bool(payload.get('emergency')),
            }, to=request.sid)
            
        except Exception as e:
            logger.error(f"处理 stop_audio 事件失败: {e}", exc_info=True)
    
    
    logger.info("语音播放 WebSocket 事件处理器已注册")
