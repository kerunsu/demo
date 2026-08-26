"""
反馈服务
实时推送分析结果到前端
"""
import threading
import time
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass

from app.core.models import AnalysisResult, MatchResult
from app.queue.result_queue import get_result_queue, ResultType
from app.storage.result_storage import get_result_storage
from app.utils.logger import setup_logger

logger = setup_logger('feedback_service')


@dataclass
class FeedbackConfig:
    """反馈服务配置"""
    enable_realtime: bool = True        # 启用实时反馈
    enable_storage: bool = True         # 启用结果存储
    batch_interval: float = 0.1         # 批量发送间隔（秒）
    attention_throttle: float = 0.45    # 略低于窗口调度间隔，避免丢更新


class FeedbackService:
    """
    反馈服务
    
    功能：
    - 实时推送匹配结果到教师端
    - 实时推送注意力分数
    - 推送会话总结
    - 触发动作通知（如自动播放表扬）
    """
    
    def __init__(
        self,
        socketio: Any = None,
        config: Optional[FeedbackConfig] = None
    ):
        """
        初始化反馈服务
        
        Args:
            socketio: Flask-SocketIO实例
            config: 配置
        """
        self._socketio = socketio
        self._config = config or FeedbackConfig()
        
        self._result_queue = get_result_queue()
        self._result_storage = get_result_storage()
        
        # 节流控制
        self._last_attention_update: Dict[str, float] = {}
        
        self._lock = threading.Lock()
        
        logger.info("反馈服务已初始化")
    
    def set_socketio(self, socketio: Any) -> None:
        """设置SocketIO实例"""
        self._socketio = socketio
        logger.info("反馈服务已设置SocketIO实例")
    
    def send_match_result(
        self,
        session_id: str,
        match_result: MatchResult
    ) -> bool:
        """
        发送匹配结果
        
        Args:
            session_id: 会话ID
            match_result: 匹配结果
        
        Returns:
            是否成功
        """
        try:
            # 存储结果
            if self._config.enable_storage:
                self._result_storage.store_match_result(session_id, match_result)
            
            # 放入队列
            self._result_queue.put_match_result(session_id, match_result)
            
            # 实时推送
            if self._config.enable_realtime and self._socketio:
                event_data = {
                    'sessionId': session_id,
                    'session_id': session_id,
                    'matcher_type': match_result.matcher_type,
                    'score': match_result.score,
                    'passed': match_result.passed,
                    'threshold': match_result.threshold,
                    'timestamp': match_result.timestamp,
                    'details': match_result.details
                }
                
                self._socketio.emit('match_result', event_data, room=session_id)
                logger.debug(f"发送匹配结果: {session_id}, score={match_result.score}")
            
            return True
            
        except Exception as e:
            logger.error(f"发送匹配结果失败: {e}")
            return False
    
    def send_attention_score(
        self,
        session_id: str,
        score: float,
        state: str = 'unknown',
        trend: str = 'stable',
        details: Optional[Dict] = None
    ) -> bool:
        """
        发送注意力分数
        
        Args:
            session_id: 会话ID
            score: 注意力分数 (0-1)
            state: 状态 (high/medium/low)
            trend: 趋势 (increasing/stable/decreasing)
            details: 详细信息
        
        Returns:
            是否成功
        """
        try:
            # 节流控制
            now = time.time()
            last_update = self._last_attention_update.get(session_id, 0)
            if now - last_update < self._config.attention_throttle:
                return True  # 跳过但返回成功
            
            self._last_attention_update[session_id] = now

            # 统一推送 0–100
            score100 = float(score or 0)
            if score100 <= 1.0001:
                score100 *= 100.0
            
            # 放入队列
            attention_data = {
                'score': score100,
                'score_scale': '0-100',
                'state': state,
                'trend': trend,
                'details': details or {}
            }
            self._result_queue.put_attention_result(session_id, attention_data)
            
            # 实时推送（限定会话房间，避免广播到其它课）
            if self._config.enable_realtime and self._socketio:
                details = details or {}
                event_data = {
                    'session_id': session_id,
                    'score': round(score100, 1),
                    'score_scale': '0-100',
                    'state': state,
                    'trend': trend,
                    'provider': 'server',
                    'face_present': details.get('face_present', details.get('has_face')),
                    'timestamp': now
                }
                self._socketio.emit('attention_update', event_data, room=session_id)
                logger.debug(f"发送注意力更新: {session_id}, score={score100:.1f}")
            
            return True
            
        except Exception as e:
            logger.error(f"发送注意力分数失败: {e}")
            return False
    
    def send_analysis_result(
        self,
        session_id: str,
        analysis_result: AnalysisResult
    ) -> bool:
        """
        发送分析结果
        
        Args:
            session_id: 会话ID
            analysis_result: 分析结果
        
        Returns:
            是否成功
        """
        try:
            # 存储结果
            if self._config.enable_storage:
                self._result_storage.store_analysis_result(session_id, analysis_result)
            
            # 放入队列
            self._result_queue.put_analysis_result(session_id, analysis_result)
            
            # 特殊处理注意力结果
            if analysis_result.analyzer_type == 'attention':
                # 仅 browser 联调且 prefer_browser 时跳过服务端推送，避免双源跳变；
                # agent（robot_runtime）生产路径必须推送服务端注意力。
                try:
                    from app.behavior.camera_config import should_prefer_browser_for_report
                    if should_prefer_browser_for_report():
                        return True
                except Exception:
                    pass
                data = analysis_result.data or {}
                # 无脸也要推送 score=0，否则教师端会一直 hold 旧分（捂摄像头像延迟 5–10s）
                face_missing = (
                    str(data.get('data_quality', '')).upper() == 'MISSING'
                    or data.get('face_present') is False
                    or data.get('has_face') is False
                )
                if face_missing:
                    return self.send_attention_score(
                        session_id,
                        score=0,
                        state='low',
                        trend=data.get('trend', 'stable'),
                        details={**data, 'face_present': False},
                    )
                return self.send_attention_score(
                    session_id,
                    score=data.get('score', 0),
                    state=data.get('state', 'unknown'),
                    trend=data.get('trend', 'stable'),
                    details=data
                )
            
            # 其他分析结果的实时推送（可选）
            if self._config.enable_realtime and self._socketio:
                event_data = {
                    'session_id': session_id,
                    'analyzer_type': analysis_result.analyzer_type,
                    'data': analysis_result.data,
                    'confidence': analysis_result.confidence,
                    'timestamp': analysis_result.timestamp
                }
                
                self._socketio.emit('analysis_result', event_data)
            
            return True
            
        except Exception as e:
            logger.error(f"发送分析结果失败: {e}")
            return False
    
    def send_session_summary(
        self,
        session_id: str,
        summary: Dict[str, Any]
    ) -> bool:
        """
        发送会话总结
        
        Args:
            session_id: 会话ID
            summary: 总结数据
        
        Returns:
            是否成功
        """
        try:
            # 导出结果到文件
            if self._config.enable_storage:
                export_path = self._result_storage.export_session(session_id)
                if export_path:
                    summary['export_path'] = export_path
            
            # 实时推送
            if self._socketio:
                event_data = {
                    'session_id': session_id,
                    'summary': summary,
                    'timestamp': time.time()
                }
                
                self._socketio.emit('session_summary', event_data)
                logger.info(f"发送会话总结: {session_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"发送会话总结失败: {e}")
            return False
    
    def send_trigger_action(
        self,
        session_id: str,
        action_type: str,
        target: str,
        action_data: Dict[str, Any]
    ) -> bool:
        """
        发送触发动作
        
        用于通知前端执行自动动作（如播放表扬）
        
        Args:
            session_id: 会话ID
            action_type: 动作类型
            target: 目标（child/teacher）
            action_data: 动作数据
        
        Returns:
            是否成功
        """
        try:
            # 放入队列
            self._result_queue.put_trigger_action(session_id, action_type, action_data)
            
            # 实时推送
            if self._socketio:
                event_data = {
                    'session_id': session_id,
                    'action_type': action_type,
                    'target': target,
                    'data': action_data,
                    'timestamp': time.time()
                }
                
                self._socketio.emit('trigger_action', event_data)
                logger.info(f"发送触发动作: {session_id}, type={action_type}, target={target}")
            
            return True
            
        except Exception as e:
            logger.error(f"发送触发动作失败: {e}")
            return False
    
    def send_play_command(
        self,
        session_id: str,
        audio_file: str,
        target: str = 'child'
    ) -> bool:
        """
        发送播放命令（便捷方法）
        
        Args:
            session_id: 会话ID
            audio_file: 音频文件路径
            target: 目标设备
        
        Returns:
            是否成功
        """
        return self.send_trigger_action(
            session_id,
            action_type='play_audio',
            target=target,
            action_data={'audio_file': audio_file}
        )
    
    def cleanup_session(self, session_id: str) -> None:
        """清理会话数据"""
        with self._lock:
            # 清理节流记录
            if session_id in self._last_attention_update:
                del self._last_attention_update[session_id]
            
            # 清理队列
            self._result_queue.clear(session_id)
        
        logger.debug(f"清理反馈会话: {session_id}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取服务统计"""
        return {
            'socketio_connected': self._socketio is not None,
            'config': {
                'enable_realtime': self._config.enable_realtime,
                'enable_storage': self._config.enable_storage,
                'attention_throttle': self._config.attention_throttle
            },
            'queue_stats': self._result_queue.get_statistics(),
            'storage_stats': self._result_storage.get_statistics()
        }


# 全局反馈服务实例
_feedback_service: Optional[FeedbackService] = None
_service_lock = threading.Lock()


def get_feedback_service() -> FeedbackService:
    """获取全局反馈服务实例（单例模式）"""
    global _feedback_service
    if _feedback_service is None:
        with _service_lock:
            if _feedback_service is None:
                _feedback_service = FeedbackService()
    return _feedback_service

