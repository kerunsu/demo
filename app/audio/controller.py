"""
语音播放控制器
管理播放状态、处理停止请求、状态回调等
"""
import time
from typing import Dict, Optional
from flask_socketio import SocketIO
from app.utils.logger import setup_logger
from .models import AudioStatus, PlaybackStatus

logger = setup_logger('audio.controller')


class AudioController:
    """语音播放控制器 - 管理播放状态和控制命令"""
    
    def __init__(self, socketio: SocketIO):
        """
        初始化播放控制器
        
        Args:
            socketio: Flask-SocketIO 实例
        """
        self.socketio = socketio
        
        # 会话播放状态 {session_id: PlaybackStatus}
        self._session_status: Dict[str, PlaybackStatus] = {}
    
    def stop_audio(self, session_id: str, immediate: bool = True) -> bool:
        """
        停止指定会话的语音播放
        
        Args:
            session_id: 会话ID
            immediate: 是否立即停止（True=立即，False=播完当前）
        
        Returns:
            是否发送成功
        """
        try:
            # 发送停止事件到儿童端房间
            child_room = f"session_{session_id}_child"
            self.socketio.emit('stop_audio', {
                'immediate': immediate,
                'timestamp': time.time()
            }, room=child_room)
            
            # 更新状态
            if session_id in self._session_status:
                self._session_status[session_id].status = AudioStatus.STOPPED
                self._session_status[session_id].updated_at = time.time()
            
            logger.info(f"发送停止播放命令: session={session_id}, immediate={immediate}")
            return True
            
        except Exception as e:
            logger.error(f"停止播放失败: {e}")
            return False
    
    def stop_all_audio(self) -> int:
        """
        停止所有会话的语音播放
        
        Returns:
            停止的会话数量
        """
        count = 0
        for session_id in list(self._session_status.keys()):
            if self.stop_audio(session_id):
                count += 1
        
        logger.info(f"停止所有播放: {count} 个会话")
        return count
    
    def on_audio_status(self, session_id: str, data: dict) -> Optional[PlaybackStatus]:
        """
        处理儿童端播放状态回调
        
        Args:
            session_id: 会话ID
            data: 状态数据 {
                'status': 'playing' | 'ended' | 'error',
                'audioId': str,
                'file': str,
                'timestamp': float
            }
        """
        try:
            status_str = str(
                data.get('status') or data.get('state') or 'unknown'
            ).strip().lower()
            audio_id = (
                data.get('entry_id')
                or data.get('entryId')
                or data.get('audio_id')
                or data.get('audioId')
            )
            file_path = (
                data.get('file_path')
                or data.get('filePath')
                or data.get('file')
            )
            timestamp = (
                data.get('timestamp')
                or data.get('updated_at')
                or data.get('updatedAt')
                or time.time()
            )
            behavior_id = (
                data.get('behaviorId')
                or data.get('behavior_id')
                or data.get('interactionId')
                or data.get('sequenceId')
            )
            
            # 解析状态（客户端历史用 finished，统一映射为 ended）
            status_aliases = {
                'finished': 'ended',
                'complete': 'ended',
                'completed': 'ended',
                'paused': 'stopped',
            }
            normalized_status = status_aliases.get(status_str, status_str)
            try:
                status = AudioStatus(normalized_status)
            except ValueError:
                logger.warning(f"未知的播放状态: {status_str}")
                return None
            
            # 更新状态
            playback_status = PlaybackStatus(
                session_id=session_id,
                status=status,
                current_audio_id=audio_id,
                current_file=file_path,
                updated_at=timestamp
            )
            self._session_status[session_id] = playback_status
            
            # 转发给教师端
            self.socketio.emit(
                'audio_status_update', 
                playback_status.to_dict(), 
                room=session_id
            )

            if behavior_id and status == AudioStatus.PLAYING:
                try:
                    from app.robot import get_robot_service

                    get_robot_service().mark_behavior_modality_started(
                        behavior_id=behavior_id,
                        request_id=(data.get('requestId') or data.get('request_id')),
                        session_id=session_id,
                        modality=data.get('modality'),
                        actual_at_ms=int(time.time() * 1000),
                    )
                except Exception as coordination_error:
                    logger.warning(
                        "记录语音实际启动失败 session=%s: %s",
                        session_id,
                        coordination_error,
                    )

            if (
                behavior_id
                and status
                in (AudioStatus.ENDED, AudioStatus.ERROR, AudioStatus.STOPPED)
            ):
                try:
                    from app.robot import get_robot_service

                    resolved_behavior_id = (
                        get_robot_service().mark_behavior_audio_complete(
                            behavior_id=behavior_id,
                            request_id=(
                                data.get('requestId') or data.get('request_id')
                            ),
                            session_id=session_id,
                            modality=data.get('modality'),
                            status=normalized_status,
                            completion_key=(
                                f"file:{audio_id or ''}:{file_path or ''}"
                            ),
                        )
                    )
                    if resolved_behavior_id:
                        data['behaviorId'] = resolved_behavior_id
                        data['behavior_id'] = resolved_behavior_id
                        data['interactionId'] = resolved_behavior_id
                except Exception as coordination_error:
                    logger.warning(
                        "释放行为语音互斥失败 session=%s: %s",
                        session_id,
                        coordination_error,
                    )
            
            logger.debug(f"更新播放状态: session={session_id}, status={status_str}, audio={audio_id}")
            return playback_status
            
        except Exception as e:
            logger.error(f"处理播放状态回调失败: {e}")
            return None
    
    def get_status(self, session_id: str) -> Optional[PlaybackStatus]:
        """
        获取会话的当前播放状态
        
        Args:
            session_id: 会话ID
        
        Returns:
            PlaybackStatus 或 None
        """
        return self._session_status.get(session_id)
    
    def get_all_status(self) -> Dict[str, PlaybackStatus]:
        """
        获取所有会话的播放状态
        
        Returns:
            {session_id: PlaybackStatus}
        """
        return self._session_status.copy()
    
    def clear_status(self, session_id: str):
        """
        清除会话的播放状态
        
        Args:
            session_id: 会话ID
        """
        if session_id in self._session_status:
            del self._session_status[session_id]
            logger.debug(f"清除播放状态: session={session_id}")
    
    def clear_all_status(self):
        """清除所有播放状态"""
        count = len(self._session_status)
        self._session_status.clear()
        logger.info(f"清除所有播放状态: {count} 个会话")
    
    def get_stats(self) -> dict:
        """
        获取统计信息
        
        Returns:
            统计信息字典
        """
        stats = {
            'total_sessions': len(self._session_status),
            'playing': 0,
            'stopped': 0,
            'ended': 0,
            'error': 0,
            'idle': 0
        }
        
        for status in self._session_status.values():
            if status.status == AudioStatus.PLAYING:
                stats['playing'] += 1
            elif status.status == AudioStatus.STOPPED:
                stats['stopped'] += 1
            elif status.status == AudioStatus.ENDED:
                stats['ended'] += 1
            elif status.status == AudioStatus.ERROR:
                stats['error'] += 1
            elif status.status == AudioStatus.IDLE:
                stats['idle'] += 1
        
        return stats


# 全局实例
_controller_instance: Optional[AudioController] = None


def get_audio_controller() -> Optional[AudioController]:
    """
    获取语音播放控制器单例
    
    注意：需要先调用 init_audio_controller() 初始化
    """
    return _controller_instance


def init_audio_controller(socketio: SocketIO) -> AudioController:
    """
    初始化语音播放控制器
    
    Args:
        socketio: Flask-SocketIO 实例
    
    Returns:
        初始化后的控制器实例
    """
    global _controller_instance
    
    if _controller_instance is None:
        _controller_instance = AudioController(socketio)
        logger.info("语音播放控制器初始化完成")
    
    return _controller_instance
