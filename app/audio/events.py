"""
语音播放事件发送器
通过 SocketIO 发送语音播放事件到客户端
"""
import time
from typing import Optional, List, Dict, Any
from flask_socketio import SocketIO
from app.utils.logger import setup_logger
from .models import AudioContext
from .selector import AudioSelector

logger = setup_logger('audio.events')


class AudioEventEmitter:
    """语音播放事件发送器"""
    
    def __init__(self, socketio: SocketIO, selector: AudioSelector):
        """
        初始化事件发送器
        
        Args:
            socketio: Flask-SocketIO 实例
            selector: 语音选择器实例
        """
        self.socketio = socketio
        self.selector = selector

    def _emit_once(
        self,
        event: str,
        payload: Dict[str, Any],
        room: str,
    ) -> bool:
        """Emit only to the correlated child room; never leak via broadcast."""
        if not room:
            logger.warning("%s 缺少目标儿童房间，拒绝下发", event)
            return False
        try:
            participants = self.socketio.server.manager.get_participants(
                "/",
                room,
            )
            if next(iter(participants), None) is None:
                logger.warning("%s 暂无儿童成员，拒绝下发 %s", room, event)
                return False
        except Exception:
            # Test emitters and non-standard managers may not expose
            # occupancy; preserving the exact room is still isolation-safe.
            pass
        self.socketio.emit(event, payload, room=room)
        return True
    
    def emit_audio(
        self,
        room: str,                          # 目标房间（通常是 session_id）
        entry_id: str,                      # 语音条目ID
        context: Optional[AudioContext] = None,
        priority: int = 0,                  # 优先级（0=普通，1=高，可打断）
        interrupt: bool = False,            # 是否打断当前播放
        file_type: str = 'files',           # 文件类型（用于拟声课程）
        behavior_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> bool:
        """
        发送语音播放事件
        
        Args:
            room: 目标房间（session_id）
            entry_id: 语音条目ID或别名
            context: 播放上下文
            priority: 优先级
            interrupt: 是否打断当前播放
            file_type: 文件类型
        
        Returns:
            是否发送成功
        
        事件格式:
        {
            "action": "play",
            "audioId": "praise_correct",
            "file": "resources/audios/301/1/1.mp3",
            "priority": 0,
            "interrupt": false,
            "timestamp": 1234567890.123
        }
        """
        try:
            # 选择语音文件
            file_path = self.selector.select(entry_id, context, file_type)
            
            if not file_path:
                logger.warning(f"无法选择语音: entry_id={entry_id}, file_type={file_type}")
                return False
            
            # 构造事件数据（与 audio_player.js 期望的格式匹配）
            event_data = {
                'entry_id': entry_id,
                'file_path': file_path,
                'priority': priority,
                'interrupt': interrupt,
                'timestamp': time.time()
            }
            self._add_correlation_ids(
                event_data,
                behavior_id=behavior_id,
                request_id=request_id,
            )
            self._add_session_ids(event_data, room)
            
            # 发送事件
            if not self._emit_once('play_audio', event_data, room):
                return False
            
            logger.info(f"发送语音播放事件: room={room}, entry={entry_id}, file={file_path}")
            return True
            
        except Exception as e:
            logger.error(f"发送语音播放事件失败: {e}")
            return False
    
    def emit_audio_sequence(
        self,
        room: str,
        entry_ids: List[str],
        interval: float = 0.5,              # 间隔秒数
        context: Optional[AudioContext] = None
    ) -> bool:
        """
        发送语音序列播放事件
        
        Args:
            room: 目标房间
            entry_ids: 语音条目ID列表
            interval: 播放间隔（秒）
            context: 播放上下文
        
        Returns:
            是否发送成功
        
        事件格式:
        {
            "action": "play_sequence",
            "sequence": [
                {"audioId": "...", "file": "..."},
                {"audioId": "...", "file": "..."}
            ],
            "interval": 500,  // 毫秒
            "timestamp": 1234567890.123
        }
        """
        try:
            # 选择所有语音文件
            sequence = []
            for entry_id in entry_ids:
                file_path = self.selector.select(entry_id, context)
                if file_path:
                    sequence.append({
                        'audioId': entry_id,
                        'file': file_path
                    })
            
            if not sequence:
                logger.warning(f"语音序列为空: entry_ids={entry_ids}")
                return False
            
            # 构造事件数据
            event_data = {
                'action': 'play_sequence',
                'sequence': sequence,
                'interval': int(interval * 1000),  # 转换为毫秒
                'timestamp': time.time()
            }
            self._add_session_ids(event_data, room)
            
            # 发送事件
            if not self._emit_once('play_audio', event_data, room):
                return False
            
            logger.info(f"发送语音序列播放事件: room={room}, count={len(sequence)}")
            return True
            
        except Exception as e:
            logger.error(f"发送语音序列播放事件失败: {e}")
            return False
    
    def emit_file_path(
        self,
        room: str,
        file_path: str,
        entry_id: str = 'direct',
        priority: int = 0,
        interrupt: bool = False,
        delay_ms: int = 0,
        behavior_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> bool:
        """直接按静态相对路径发送 play_audio（如课点 hint_audio；支持文件夹随机）。"""
        try:
            from app.utils.resource_utils import resolve_playable_audio_path
            path = resolve_playable_audio_path(file_path or '')
            if not path:
                logger.warning(f"直接语音路径无效: {file_path}")
                return False
            event_data = {
                'entry_id': entry_id,
                'file_path': path,
                'priority': priority,
                'interrupt': interrupt,
                'timestamp': time.time(),
                'delay_ms': max(0, int(delay_ms or 0)),
                'startAtServerMs': int(time.time() * 1000) + max(0, int(delay_ms or 0)),
            }
            self._add_correlation_ids(
                event_data,
                behavior_id=behavior_id,
                request_id=request_id,
            )
            self._add_session_ids(event_data, room)
            if not self._emit_once('play_audio', event_data, room):
                return False
            logger.info(
                f"发送直接语音: room={room}, entry={entry_id}, "
                f"file={path}, raw={file_path}"
            )
            return True
        except Exception as e:
            logger.error(f"发送直接语音失败: {e}")
            return False

    def emit_for_course(
        self,
        room: str,
        course_type: str,
        audio_type: str,                    # 'question' | 'praise' | 'hint'
        item_id: Optional[int] = None,
        context: Optional[AudioContext] = None,
        priority: int = 0,
        delay_ms: int = 0,
        behavior_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> bool:
        """
        为课程发送语音播放事件（便捷接口）
        
        Args:
            room: 目标房间
            course_type: 课程类型，如 "naming", "mimic"
            audio_type: 语音类型
            item_id: 课程项ID
            context: 上下文
            priority: 优先级
        
        Returns:
            是否发送成功
        """
        try:
            # 使用选择器的便捷接口
            file_path = self.selector.select_for_course(
                course_type=course_type,
                audio_type=audio_type,
                item_id=item_id,
                context=context
            )
            
            if not file_path:
                logger.warning(f"无法为课程选择语音: type={course_type}, audio={audio_type}")
                return False
            
            # 构造事件数据（与 audio_player.js 期望的格式匹配）
            event_data = {
                'entry_id': f"{course_type}_{audio_type}",
                'file_path': file_path,
                'priority': priority,
                'interrupt': False,
                'timestamp': time.time(),
                'delay_ms': max(0, int(delay_ms or 0)),
            }
            self._add_correlation_ids(
                event_data,
                behavior_id=behavior_id,
                request_id=request_id,
            )
            self._add_session_ids(event_data, room)
            
            # 发送事件
            if not self._emit_once('play_audio', event_data, room):
                return False
            
            logger.info(f"发送课程语音: room={room}, course={course_type}, type={audio_type}, file={file_path}")
            return True
            
        except Exception as e:
            logger.error(f"发送课程语音失败: {e}")
            return False

    @staticmethod
    def _add_correlation_ids(
        payload: Dict[str, Any],
        *,
        behavior_id: Optional[str],
        request_id: Optional[str],
    ) -> None:
        """Attach stable IDs in both modern and legacy-friendly spellings."""
        if behavior_id:
            value = str(behavior_id)
            payload['behaviorId'] = value
            payload['behavior_id'] = value
            payload['interactionId'] = value
            payload['protocolVersion'] = '1'
            payload['modality'] = 'speech'
        if request_id:
            value = str(request_id)
            payload['requestId'] = value
            payload['request_id'] = value

    @staticmethod
    def _add_session_ids(
        payload: Dict[str, Any],
        room: Optional[str],
    ) -> None:
        """Correlate file audio with the exact child runtime session."""
        value = str(room or '').strip()
        if not value:
            return
        prefix = 'session_'
        suffix = '_child'
        if value.startswith(prefix) and value.endswith(suffix):
            value = value[len(prefix):-len(suffix)]
        if not value:
            return
        payload['sessionId'] = value
        payload['session_id'] = value
    
    def emit_vocalization(
        self,
        room: str,
        animal_name: str,
        is_question: bool = True,
        context: Optional[AudioContext] = None
    ) -> bool:
        """
        为拟声课程发送语音播放事件
        
        Args:
            room: 目标房间
            animal_name: 动物名称，如 "cat"
            is_question: 是否是提问语音
            context: 上下文
        
        Returns:
            是否发送成功
        """
        try:
            file_path = self.selector.select_vocalization(
                animal_name=animal_name,
                is_question=is_question,
                context=context
            )
            
            if not file_path:
                logger.warning(f"无法为拟声课程选择语音: animal={animal_name}")
                return False
            
            # 构造事件数据
            event_data = {
                'action': 'play',
                'audioId': f"vocalization_{animal_name}_{'q' if is_question else 'a'}",
                'file': file_path,
                'priority': 0,
                'interrupt': False,
                'timestamp': time.time()
            }
            self._add_session_ids(event_data, room)
            
            # 发送事件
            if not self._emit_once('play_audio', event_data, room):
                return False
            
            logger.info(f"发送拟声语音: room={room}, animal={animal_name}, question={is_question}")
            return True
            
        except Exception as e:
            logger.error(f"发送拟声语音失败: {e}")
            return False


# 全局实例
_emitter_instance: Optional[AudioEventEmitter] = None


def get_audio_emitter() -> Optional[AudioEventEmitter]:
    """
    获取语音事件发送器单例
    
    注意：需要先调用 init_audio_emitter() 初始化
    """
    return _emitter_instance


def init_audio_emitter(socketio: SocketIO) -> AudioEventEmitter:
    """
    初始化语音事件发送器
    
    Args:
        socketio: Flask-SocketIO 实例
    
    Returns:
        初始化后的发送器实例
    """
    global _emitter_instance
    
    if _emitter_instance is None:
        from .selector import get_audio_selector
        selector = get_audio_selector()
        _emitter_instance = AudioEventEmitter(socketio, selector)
        logger.info("语音事件发送器初始化完成")
    
    return _emitter_instance
