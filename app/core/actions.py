"""
动作定义模块
定义触发系统可执行的各种动作
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Callable
from enum import Enum
import uuid

from app.utils.logger import setup_logger

logger = setup_logger('actions')


class ActionType(Enum):
    """动作类型枚举"""
    PLAY_AUDIO = "play_audio"           # 播放音频
    PLAY_VIDEO = "play_video"           # 播放视频
    SHOW_IMAGE = "show_image"           # 显示图片
    EMIT_EVENT = "emit_event"           # 发送WebSocket事件
    LOG = "log"                         # 记录日志
    NOTIFY = "notify"                   # 发送通知
    CUSTOM = "custom"                   # 自定义动作


class ActionTarget(Enum):
    """动作目标枚举"""
    CHILD = "child"                     # 儿童端
    THERAPIST = "therapist"             # 教师端
    BOTH = "both"                       # 两端都发送
    SERVER = "server"                   # 仅服务器端（如记录日志）


@dataclass
class ActionResult:
    """动作执行结果"""
    success: bool                       # 是否成功
    action_type: str                    # 动作类型
    target: str                         # 目标
    message: str = ""                   # 结果消息
    error: Optional[str] = None         # 错误信息
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionDefinition:
    """
    动作定义
    
    定义一个可执行的动作，包括类型、目标和参数
    """
    action_type: ActionType             # 动作类型
    target: ActionTarget                # 目标
    payload: Dict[str, Any] = field(default_factory=dict)  # 动作参数
    description: str = ""               # 动作描述
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'action_type': self.action_type.value,
            'target': self.target.value,
            'payload': self.payload,
            'description': self.description
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ActionDefinition':
        """从字典创建"""
        return cls(
            action_type=ActionType(data['action_type']),
            target=ActionTarget(data['target']),
            payload=data.get('payload', {}),
            description=data.get('description', '')
        )


# ==================== 预定义动作工厂 ====================

class ActionFactory:
    """
    动作工厂
    
    提供创建常用动作的便捷方法
    """
    
    @staticmethod
    def play_praise_audio(audio_path: str = "/static/resources/audio/praise.mp3") -> ActionDefinition:
        """
        创建播放表扬音频的动作
        
        Args:
            audio_path: 音频文件路径
        
        Returns:
            ActionDefinition
        """
        return ActionDefinition(
            action_type=ActionType.PLAY_AUDIO,
            target=ActionTarget.CHILD,
            payload={'audio': audio_path, 'type': 'praise'},
            description="播放表扬音频"
        )
    
    @staticmethod
    def play_hint_audio(audio_path: str) -> ActionDefinition:
        """
        创建播放提示音频的动作
        
        Args:
            audio_path: 音频文件路径
        
        Returns:
            ActionDefinition
        """
        return ActionDefinition(
            action_type=ActionType.PLAY_AUDIO,
            target=ActionTarget.CHILD,
            payload={'audio': audio_path, 'type': 'hint'},
            description="播放提示音频"
        )
    
    @staticmethod
    def play_interest_content(content_path: str) -> ActionDefinition:
        """
        创建播放感兴趣内容的动作（用于注意力干预）
        
        Args:
            content_path: 内容路径（视频或音频）
        
        Returns:
            ActionDefinition
        """
        # 根据路径判断类型
        if content_path.endswith(('.mp4', '.webm', '.avi')):
            action_type = ActionType.PLAY_VIDEO
        else:
            action_type = ActionType.PLAY_AUDIO
        
        return ActionDefinition(
            action_type=action_type,
            target=ActionTarget.CHILD,
            payload={'content': content_path, 'type': 'interest'},
            description="播放感兴趣内容（注意力干预）"
        )
    
    @staticmethod
    def emit_to_therapist(event_name: str, data: Dict[str, Any]) -> ActionDefinition:
        """
        创建向教师端发送事件的动作
        
        Args:
            event_name: 事件名称
            data: 事件数据
        
        Returns:
            ActionDefinition
        """
        return ActionDefinition(
            action_type=ActionType.EMIT_EVENT,
            target=ActionTarget.THERAPIST,
            payload={'event': event_name, 'data': data},
            description=f"向教师端发送事件: {event_name}"
        )
    
    @staticmethod
    def emit_to_child(event_name: str, data: Dict[str, Any]) -> ActionDefinition:
        """
        创建向儿童端发送事件的动作
        
        Args:
            event_name: 事件名称
            data: 事件数据
        
        Returns:
            ActionDefinition
        """
        return ActionDefinition(
            action_type=ActionType.EMIT_EVENT,
            target=ActionTarget.CHILD,
            payload={'event': event_name, 'data': data},
            description=f"向儿童端发送事件: {event_name}"
        )
    
    @staticmethod
    def emit_to_both(event_name: str, data: Dict[str, Any]) -> ActionDefinition:
        """
        创建向两端发送事件的动作
        
        Args:
            event_name: 事件名称
            data: 事件数据
        
        Returns:
            ActionDefinition
        """
        return ActionDefinition(
            action_type=ActionType.EMIT_EVENT,
            target=ActionTarget.BOTH,
            payload={'event': event_name, 'data': data},
            description=f"向两端发送事件: {event_name}"
        )
    
    @staticmethod
    def log_event(message: str, level: str = "info") -> ActionDefinition:
        """
        创建记录日志的动作
        
        Args:
            message: 日志消息
            level: 日志级别
        
        Returns:
            ActionDefinition
        """
        return ActionDefinition(
            action_type=ActionType.LOG,
            target=ActionTarget.SERVER,
            payload={'message': message, 'level': level},
            description=f"记录日志: {message}"
        )
    
    @staticmethod
    def notify_match_success(score: float, matcher_type: str) -> ActionDefinition:
        """
        创建匹配成功通知动作
        
        Args:
            score: 匹配分数
            matcher_type: 匹配器类型
        
        Returns:
            ActionDefinition
        """
        return ActionDefinition(
            action_type=ActionType.NOTIFY,
            target=ActionTarget.BOTH,
            payload={
                'type': 'match_success',
                'score': score,
                'matcher_type': matcher_type
            },
            description=f"通知匹配成功: {matcher_type}, score={score:.2f}"
        )
    
    @staticmethod
    def custom_action(
        handler_name: str,
        params: Dict[str, Any],
        target: ActionTarget = ActionTarget.SERVER
    ) -> ActionDefinition:
        """
        创建自定义动作
        
        Args:
            handler_name: 处理器名称
            params: 处理器参数
            target: 目标
        
        Returns:
            ActionDefinition
        """
        return ActionDefinition(
            action_type=ActionType.CUSTOM,
            target=target,
            payload={'handler': handler_name, 'params': params},
            description=f"自定义动作: {handler_name}"
        )


# ==================== 动作执行器接口 ====================

class ActionExecutor:
    """
    动作执行器
    
    负责执行具体的动作。需要与 WebSocket (socketio) 集成。
    """
    
    def __init__(self, socketio=None):
        """
        初始化动作执行器
        
        Args:
            socketio: Flask-SocketIO 实例
        """
        self._socketio = socketio
        self._custom_handlers: Dict[str, Callable] = {}
        
        logger.info("动作执行器已初始化")
    
    def set_socketio(self, socketio) -> None:
        """设置 SocketIO 实例"""
        self._socketio = socketio
        logger.info("SocketIO 实例已设置")
    
    def register_custom_handler(self, name: str, handler: Callable) -> None:
        """
        注册自定义动作处理器
        
        Args:
            name: 处理器名称
            handler: 处理函数，签名为 handler(params: Dict) -> ActionResult
        """
        self._custom_handlers[name] = handler
        logger.info(f"注册自定义动作处理器: {name}")
    
    def execute(self, action: ActionDefinition, session_id: str) -> ActionResult:
        """
        执行动作
        
        Args:
            action: 动作定义
            session_id: 会话ID
        
        Returns:
            ActionResult
        """
        try:
            action_type = action.action_type
            
            if action_type == ActionType.PLAY_AUDIO:
                return self._execute_play_audio(action, session_id)
            elif action_type == ActionType.PLAY_VIDEO:
                return self._execute_play_video(action, session_id)
            elif action_type == ActionType.SHOW_IMAGE:
                return self._execute_show_image(action, session_id)
            elif action_type == ActionType.EMIT_EVENT:
                return self._execute_emit_event(action, session_id)
            elif action_type == ActionType.LOG:
                return self._execute_log(action, session_id)
            elif action_type == ActionType.NOTIFY:
                return self._execute_notify(action, session_id)
            elif action_type == ActionType.CUSTOM:
                return self._execute_custom(action, session_id)
            else:
                return ActionResult(
                    success=False,
                    action_type=action_type.value,
                    target=action.target.value,
                    error=f"未知的动作类型: {action_type}"
                )
                
        except Exception as e:
            logger.error(f"执行动作失败: {action.action_type.value}, 错误: {e}")
            return ActionResult(
                success=False,
                action_type=action.action_type.value,
                target=action.target.value,
                error=str(e)
            )
    
    def _emit_to_target(
        self,
        event: str,
        data: Dict[str, Any],
        target: ActionTarget
    ) -> bool:
        """
        向目标发送事件
        
        Args:
            event: 事件名称
            data: 事件数据
            target: 目标
        
        Returns:
            是否成功
        """
        if self._socketio is None:
            logger.warning("SocketIO 未设置，无法发送事件")
            return False
        
        try:
            # 广播事件（实际应用中可能需要根据 target 过滤）
            self._socketio.emit(event, data)
            return True
        except Exception as e:
            logger.error(f"发送事件失败: {event}, 错误: {e}")
            return False
    
    def _execute_play_audio(self, action: ActionDefinition, session_id: str) -> ActionResult:
        """
        执行播放音频动作
        
        使用新的语音系统播放音频，支持两种方式：
        1. entry_id: 使用语音系统的条目ID（推荐）
        2. audio/content: 旧版硬编码路径（兼容模式，会尝试映射到语音系统）
        """
        audio_type = action.payload.get('type', 'default')
        type_to_entry = {
            'praise': 'praise',
            'interest': 'praise',
            'hint': 'hint',
            'question': 'question',
            'default': 'praise',
        }
        entry_id = action.payload.get('entry_id') or type_to_entry.get(
            audio_type,
            'praise',
        )
        request_id = (
            action.payload.get('requestId')
            or action.payload.get('request_id')
            or f'auto-{uuid.uuid4().hex[:12]}'
        )
        behavior_id = (
            action.payload.get('behaviorId')
            or action.payload.get('behavior_id')
            or f'behavior-{uuid.uuid4().hex[:12]}'
        )
        base_metadata = {
            'entry_id': entry_id,
            'original_type': audio_type,
            'requestId': request_id,
            'behaviorId': behavior_id,
            'interactionId': behavior_id,
        }
        robot_service = None
        reserved = False

        try:
            from app.audio import get_audio_emitter
            from app.robot import get_robot_service
            from app.session import get_session_manager

            runtime_session = get_session_manager().get_session(session_id)
            if not runtime_session or runtime_session.course_id is None:
                return ActionResult(
                    success=False,
                    action_type=action.action_type.value,
                    target=action.target.value,
                    message='自动反馈缺少有效 runtime session，未播放',
                    error='runtime_session_unavailable',
                    metadata={
                        **base_metadata,
                        'accepted': False,
                        'suppressed': True,
                    },
                )

            robot_service = get_robot_service()
            reservation = robot_service.reserve_behavior(
                behavior_id=behavior_id,
                request_id=request_id,
                session_id=session_id,
            )
            if not reservation.get('accepted'):
                active_id = reservation.get('activeBehaviorId')
                return ActionResult(
                    success=False,
                    action_type=action.action_type.value,
                    target=action.target.value,
                    message='当前行为播放中，自动表扬已整组忽略',
                    error='behavior_busy',
                    metadata={
                        **base_metadata,
                        'accepted': False,
                        'busy': True,
                        'suppressed': True,
                        'behaviorId': active_id,
                        'interactionId': active_id,
                        'activeBehaviorId': active_id,
                        'remainingMs': int(
                            reservation.get('remainingMs') or 0
                        ),
                    },
                )
            reserved = True

            metadata = runtime_session.metadata or {}
            robot_result = robot_service.trigger_course_event({
                'action': 'play',
                'studentId': runtime_session.student_id,
                'courseId': runtime_session.course_id,
                'itemId': runtime_session.course_item_id,
                'courseType': metadata.get('course_type') or 'default',
                'sessionId': session_id,
                'trainingSessionId': getattr(
                    runtime_session,
                    'training_session_id',
                    None,
                ),
                'aux': {'praise': True},
                'requestId': request_id,
                'behaviorId': behavior_id,
                'interactionId': behavior_id,
            })
            if not robot_result.get('success'):
                robot_service.abort_behavior(behavior_id)
                return ActionResult(
                    success=False,
                    action_type=action.action_type.value,
                    target=action.target.value,
                    message=robot_result.get('message') or '自动表扬行为启动失败',
                    error='behavior_start_failed',
                    metadata={
                        **base_metadata,
                        'accepted': False,
                        'suppressed': True,
                    },
                )

            emitter = get_audio_emitter()
            child_room = f"session_{session_id}_child"
            emitted = bool(emitter and emitter.emit_audio(
                room=child_room,
                entry_id=entry_id,
                behavior_id=behavior_id,
                request_id=request_id,
            ))
            if not emitted:
                robot_service.abort_behavior(behavior_id)
                return ActionResult(
                    success=False,
                    action_type=action.action_type.value,
                    target=action.target.value,
                    message=f'自动表扬语音发送失败: {entry_id}',
                    error='audio_dispatch_failed',
                    metadata={
                        **base_metadata,
                        'accepted': False,
                        'suppressed': True,
                    },
                )

            if not robot_service.set_behavior_audio_expected(
                behavior_id,
                1,
                session_id=session_id,
            ):
                robot_service.abort_behavior(behavior_id)
                return ActionResult(
                    success=False,
                    action_type=action.action_type.value,
                    target=action.target.value,
                    message='自动表扬未能原子提交，已取消本次动作与表情',
                    error='behavior_commit_failed',
                    metadata={
                        **base_metadata,
                        'accepted': False,
                        'suppressed': True,
                    },
                )
            logger.info(
                '自动反馈原子播放: session=%s behavior=%s entry=%s',
                session_id,
                behavior_id,
                entry_id,
            )
            return ActionResult(
                success=True,
                action_type=action.action_type.value,
                target=action.target.value,
                message=f"播放语音: {entry_id}",
                metadata={
                    **base_metadata,
                    'accepted': True,
                    'busy': False,
                    'remainingMs': int(
                        robot_service.get_behavior_busy_state().get(
                            'remainingMs',
                            0,
                        )
                    ),
                },
            )

        except Exception as e:
            if reserved and robot_service:
                robot_service.abort_behavior(behavior_id)
            logger.error(f"播放音频失败: {e}", exc_info=True)
            return ActionResult(
                success=False,
                action_type=action.action_type.value,
                target=action.target.value,
                message=f"播放音频失败: {e}",
                error=str(e),
                metadata={
                    **base_metadata,
                    'accepted': False,
                    'suppressed': True,
                },
            )
    
    def _execute_play_video(self, action: ActionDefinition, session_id: str) -> ActionResult:
        """执行播放视频动作"""
        content_path = action.payload.get('content', '')
        content_type = action.payload.get('type', 'default')
        
        event_data = {
            'session_id': session_id,
            'action': 'play_video',
            'content': content_path,
            'type': content_type
        }
        
        success = self._emit_to_target('trigger_action', event_data, action.target)
        
        return ActionResult(
            success=success,
            action_type=action.action_type.value,
            target=action.target.value,
            message=f"播放视频: {content_path}" if success else "播放视频失败",
            metadata={'content': content_path, 'type': content_type}
        )
    
    def _execute_show_image(self, action: ActionDefinition, session_id: str) -> ActionResult:
        """执行显示图片动作"""
        image_path = action.payload.get('image', '')
        
        event_data = {
            'session_id': session_id,
            'action': 'show_image',
            'image': image_path
        }
        
        success = self._emit_to_target('trigger_action', event_data, action.target)
        
        return ActionResult(
            success=success,
            action_type=action.action_type.value,
            target=action.target.value,
            message=f"显示图片: {image_path}" if success else "显示图片失败",
            metadata={'image': image_path}
        )
    
    def _execute_emit_event(self, action: ActionDefinition, session_id: str) -> ActionResult:
        """执行发送事件动作"""
        event_name = action.payload.get('event', 'custom_event')
        event_data = action.payload.get('data', {})
        event_data['session_id'] = session_id
        
        success = self._emit_to_target(event_name, event_data, action.target)
        
        return ActionResult(
            success=success,
            action_type=action.action_type.value,
            target=action.target.value,
            message=f"发送事件: {event_name}" if success else "发送事件失败",
            metadata={'event': event_name}
        )
    
    def _execute_log(self, action: ActionDefinition, session_id: str) -> ActionResult:
        """执行记录日志动作"""
        message = action.payload.get('message', '')
        level = action.payload.get('level', 'info')
        
        log_message = f"[{session_id}] {message}"
        
        if level == 'debug':
            logger.debug(log_message)
        elif level == 'info':
            logger.info(log_message)
        elif level == 'warning':
            logger.warning(log_message)
        elif level == 'error':
            logger.error(log_message)
        else:
            logger.info(log_message)
        
        return ActionResult(
            success=True,
            action_type=action.action_type.value,
            target=action.target.value,
            message=f"记录日志: {message}",
            metadata={'level': level}
        )
    
    def _execute_notify(self, action: ActionDefinition, session_id: str) -> ActionResult:
        """执行通知动作"""
        notify_type = action.payload.get('type', 'info')
        
        event_data = {
            'session_id': session_id,
            'action': 'notify',
            **action.payload
        }
        
        success = self._emit_to_target('notification', event_data, action.target)
        
        return ActionResult(
            success=success,
            action_type=action.action_type.value,
            target=action.target.value,
            message=f"发送通知: {notify_type}" if success else "发送通知失败",
            metadata=action.payload
        )
    
    def _execute_custom(self, action: ActionDefinition, session_id: str) -> ActionResult:
        """执行自定义动作"""
        handler_name = action.payload.get('handler', '')
        params = action.payload.get('params', {})
        params['session_id'] = session_id
        
        if handler_name not in self._custom_handlers:
            return ActionResult(
                success=False,
                action_type=action.action_type.value,
                target=action.target.value,
                error=f"未找到自定义处理器: {handler_name}"
            )
        
        try:
            handler = self._custom_handlers[handler_name]
            result = handler(params)
            
            if isinstance(result, ActionResult):
                return result
            else:
                return ActionResult(
                    success=True,
                    action_type=action.action_type.value,
                    target=action.target.value,
                    message=f"执行自定义动作: {handler_name}",
                    metadata={'result': result}
                )
        except Exception as e:
            return ActionResult(
                success=False,
                action_type=action.action_type.value,
                target=action.target.value,
                error=f"执行自定义处理器失败: {e}"
            )

