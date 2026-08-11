"""
媒体服务
协调录制和分析功能
管理MediaRecorder和队列消费
"""
import threading
import time
from typing import Optional, Dict
from app.session import get_session_manager
from app.session.session_model import SessionStatus
from app.recorder import MediaRecorder
from app.queue import VideoQueue, AudioQueue, get_video_queue, get_audio_queue
from app.utils.logger import setup_logger
from app.utils.exceptions import RecordingStartError, RecordingStopError

logger = setup_logger('media_service')


class MediaService:
    """
    媒体服务
    
    负责：
    - 管理MediaRecorder的生命周期
    - 从队列消费视频帧和音频块
    - 将数据写入录制器
    - 协调会话状态
    """
    
    def __init__(self):
        """初始化媒体服务"""
        # 存储每个会话的MediaRecorder：{session_id: MediaRecorder}
        self._recorders: Dict[str, MediaRecorder] = {}
        # 锁，保证线程安全
        self._lock = threading.RLock()
        
        # 队列消费线程
        self._video_consumer_thread: Optional[threading.Thread] = None
        self._audio_consumer_thread: Optional[threading.Thread] = None
        self._stop_consumers = False
        
        # 队列引用
        self._video_queue: Optional[VideoQueue] = None
        self._audio_queue: Optional[AudioQueue] = None
        
        # 启动队列消费线程
        self._ensure_consumers_running()
        
        logger.info("媒体服务已初始化")
    
    def start_recording(
        self,
        session_id: str,
        student_id: Optional[int] = None,
        course_id: Optional[int] = None,
        course_item_id: Optional[int] = None
    ) -> bool:
        """
        启动录制
        
        Args:
            session_id: 会话ID
            student_id: 学生ID（可选）
            course_id: 课程ID（可选）
            course_item_id: 课程项ID（可选）
        
        Returns:
            True如果成功，False否则
        """
        try:
            with self._lock:
                # 检查会话是否存在
                session_manager = get_session_manager()
                session = session_manager.get_session(session_id)
                
                if not session:
                    logger.error("启动录制失败：会话不存在: session_id=%s", session_id)
                    return False
                
                # 检查是否已经在录制
                if session_id in self._recorders:
                    recorder = self._recorders[session_id]
                    if recorder.is_recording():
                        logger.warning("会话已在录制中: session_id=%s", session_id)
                        return True
                
                # 创建MediaRecorder
                recorder = MediaRecorder(session_id)
                
                # 启动录制（不自动捕获音频，通过WebSocket数据写入）
                recorder.start(
                    record_video=True,
                    record_audio=True,
                    auto_capture_audio=False  # 从WebSocket接收数据
                )
                
                # 存储录制器
                self._recorders[session_id] = recorder
                
                # 更新会话状态（如果还是CREATED，则启动）
                if session.status == SessionStatus.CREATED:
                    session.start()
                    session_manager.update_session(session)
                
                logger.info(
                    "启动录制成功: session_id=%s, student_id=%s, "
                    "course_id=%s, item_id=%s",
                    session_id, student_id, course_id, course_item_id
                )
                
                # 确保队列消费线程在运行
                self._ensure_consumers_running()
                
                return True
                
        except RecordingStartError as e:
            logger.error("启动录制失败: %s", e, exc_info=True)
            return False
        except Exception as e:
            logger.error("启动录制时出错: %s", e, exc_info=True)
            return False
    
    def stop_recording(self, session_id: str) -> bool:
        """
        停止录制
        
        Args:
            session_id: 会话ID
        
        Returns:
            True如果成功，False否则
        """
        try:
            with self._lock:
                if session_id not in self._recorders:
                    logger.warning("停止录制失败：录制器不存在: session_id=%s", session_id)
                    return False
                
                recorder = self._recorders[session_id]
                
                # 停止录制
                try:
                    recorder.stop()
                except RecordingStopError as e:
                    logger.error("停止录制器失败: %s", e)
                
                # 清理录制器
                recorder.cleanup()
                del self._recorders[session_id]
                
                # 更新会话状态
                session_manager = get_session_manager()
                session = session_manager.get_session(session_id)
                if session:
                    session_manager.end_session(session_id, SessionStatus.COMPLETED)
                
                # 清空队列
                video_queue = get_video_queue()
                audio_queue = get_audio_queue()
                video_queue.clear(session_id)
                audio_queue.clear(session_id)
                
                logger.info("停止录制成功: session_id=%s", session_id)
                
                return True
                
        except Exception as e:
            logger.error("停止录制时出错: %s", e, exc_info=True)
            return False
    
    def process_video_frame(
        self,
        session_id: str,
        frame: str,
        timestamp: Optional[float] = None
    ) -> bool:
        """
        处理视频帧（从队列消费并写入录制器）
        
        Args:
            session_id: 会话ID
            frame: 视频帧数据（base64字符串）
            timestamp: 时间戳（可选）
        
        Returns:
            True如果成功，False否则
        """
        try:
            with self._lock:
                if session_id not in self._recorders:
                    logger.warning(
                        "处理视频帧失败：录制器不存在: session_id=%s",
                        session_id
                    )
                    return False
                
                recorder = self._recorders[session_id]
                
                if not recorder.is_recording():
                    logger.warning(
                        "处理视频帧失败：录制器未在运行: session_id=%s",
                        session_id
                    )
                    return False
                
                # 写入视频帧
                recorder.write_video_frame(frame)
                
                return True
                
        except Exception as e:
            logger.error(
                "处理视频帧时出错: session_id=%s, error=%s",
                session_id, e, exc_info=True
            )
            return False
    
    def process_audio_chunk(
        self,
        session_id: str,
        chunk: str,
        timestamp: Optional[float] = None
    ) -> bool:
        """
        处理音频块（从队列消费并写入录制器）
        
        Args:
            session_id: 会话ID
            chunk: 音频块数据（base64字符串）
            timestamp: 时间戳（可选）
        
        Returns:
            True如果成功，False否则
        """
        try:
            with self._lock:
                if session_id not in self._recorders:
                    logger.warning(
                        "处理音频块失败：录制器不存在: session_id=%s",
                        session_id
                    )
                    return False
                
                recorder = self._recorders[session_id]
                
                if not recorder.is_recording():
                    logger.warning(
                        "处理音频块失败：录制器未在运行: session_id=%s",
                        session_id
                    )
                    return False
                
                # 写入音频块
                recorder.write_audio_chunk(chunk)
                
                return True
                
        except Exception as e:
            logger.error(
                "处理音频块时出错: session_id=%s, error=%s",
                session_id, e, exc_info=True
            )
            return False
    
    def _ensure_consumers_running(self):
        """确保队列消费线程在运行"""
        if self._video_consumer_thread is None or not self._video_consumer_thread.is_alive():
            self._stop_consumers = False
            self._video_consumer_thread = threading.Thread(
                target=self._video_consumer_loop,
                daemon=True,
                name="VideoQueueConsumer"
            )
            self._video_consumer_thread.start()
            logger.info("视频队列消费线程已启动")
        
        if self._audio_consumer_thread is None or not self._audio_consumer_thread.is_alive():
            self._stop_consumers = False
            self._audio_consumer_thread = threading.Thread(
                target=self._audio_consumer_loop,
                daemon=True,
                name="AudioQueueConsumer"
            )
            self._audio_consumer_thread.start()
            logger.info("音频队列消费线程已启动")
    
    def _video_consumer_loop(self):
        """视频队列消费循环（后台线程）"""
        logger.info("视频队列消费循环已启动")
        
        while not self._stop_consumers:
            try:
                # 获取队列实例
                if self._video_queue is None:
                    self._video_queue = get_video_queue()
                
                # 获取所有有数据的会话
                sessions = self._video_queue.list_sessions()
                
                for session_id in sessions:
                    # 从队列获取视频帧
                    result = self._video_queue.get(session_id)
                    
                    if result:
                        frame, timestamp, _ = result
                        
                        # 处理视频帧（写入录制器）
                        success = self.process_video_frame(session_id, frame, timestamp)
                        
                        if not success:
                            logger.warning(
                                "处理视频帧失败，但已从队列移除: session_id=%s",
                                session_id
                            )
                
                # 短暂休眠，避免CPU占用过高
                time.sleep(0.01)  # 10ms
                
            except Exception as e:
                logger.error("视频队列消费循环出错: %s", e, exc_info=True)
                time.sleep(0.1)  # 出错时休眠更长时间
    
    def _audio_consumer_loop(self):
        """音频队列消费循环（后台线程）"""
        logger.info("音频队列消费循环已启动")
        
        while not self._stop_consumers:
            try:
                # 获取队列实例
                if self._audio_queue is None:
                    self._audio_queue = get_audio_queue()
                
                # 获取所有有数据的会话
                sessions = self._audio_queue.list_sessions()
                
                for session_id in sessions:
                    # 从队列获取音频块
                    result = self._audio_queue.get(session_id)
                    
                    if result:
                        chunk, timestamp, _ = result
                        
                        # 处理音频块（写入录制器）
                        success = self.process_audio_chunk(session_id, chunk, timestamp)
                        
                        if not success:
                            logger.warning(
                                "处理音频块失败，但已从队列移除: session_id=%s",
                                session_id
                            )
                
                # 短暂休眠，避免CPU占用过高
                time.sleep(0.01)  # 10ms
                
            except Exception as e:
                logger.error("音频队列消费循环出错: %s", e, exc_info=True)
                time.sleep(0.1)  # 出错时休眠更长时间
    
    def get_recorder(self, session_id: str) -> Optional[MediaRecorder]:
        """
        获取指定会话的录制器
        
        Args:
            session_id: 会话ID
        
        Returns:
            MediaRecorder实例，如果不存在则返回None
        """
        with self._lock:
            return self._recorders.get(session_id)
    
    def is_recording(self, session_id: str) -> bool:
        """
        检查指定会话是否正在录制
        
        Args:
            session_id: 会话ID
        
        Returns:
            True如果正在录制，False否则
        """
        with self._lock:
            if session_id not in self._recorders:
                return False
            return self._recorders[session_id].is_recording()
    
    def list_active_recordings(self) -> list[str]:
        """
        获取所有正在录制的会话ID列表
        
        Returns:
            会话ID列表
        """
        with self._lock:
            return [
                session_id for session_id, recorder in self._recorders.items()
                if recorder.is_recording()
            ]
    
    def get_statistics(self) -> Dict:
        """
        获取媒体服务统计信息
        
        Returns:
            统计信息字典
        """
        with self._lock:
            stats = {
                'total_recorders': len(self._recorders),
                'active_recordings': len([
                    r for r in self._recorders.values() if r.is_recording()
                ]),
                'video_consumer_running': (
                    self._video_consumer_thread is not None
                    and self._video_consumer_thread.is_alive()
                ),
                'audio_consumer_running': (
                    self._audio_consumer_thread is not None
                    and self._audio_consumer_thread.is_alive()
                ),
                'sessions': {}
            }
            
            for session_id, recorder in self._recorders.items():
                stats['sessions'][session_id] = {
                    'is_recording': recorder.is_recording(),
                    'video_duration': recorder.get_video_duration(),
                    'audio_duration': recorder.get_audio_duration(),
                    'statistics': recorder.get_statistics()
                }
            
            return stats


# 全局媒体服务实例（单例模式）
_media_service: Optional[MediaService] = None
_service_lock = threading.Lock()


def get_media_service() -> MediaService:
    """
    获取全局媒体服务实例（单例模式）
    
    Returns:
        MediaService实例
    """
    global _media_service
    if _media_service is None:
        with _service_lock:
            if _media_service is None:
                _media_service = MediaService()
    return _media_service

