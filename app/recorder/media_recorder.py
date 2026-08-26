"""
统一媒体录制器
协调视频和音频的同步录制
"""
from pathlib import Path
from typing import Optional
from datetime import datetime
from app.recorder.video_recorder import VideoRecorder
from app.recorder.audio_recorder import AudioRecorder
from app.config import Config
from app.utils.exceptions import RecordingStartError, RecordingStopError, RecordingException
from app.utils.logger import setup_logger

logger = setup_logger('media_recorder')


class MediaRecorder:
    """
    统一媒体录制器
    
    管理视频和音频的同步录制
    一个会话对应一个视频文件和一个音频文件
    """
    
    def __init__(
        self,
        session_id: str,
        video_path: Path = None,
        audio_path: Path = None
    ):
        """
        初始化媒体录制器
        
        Args:
            session_id: 会话ID
            video_path: 视频文件路径（默认使用Config生成）
            audio_path: 音频文件路径（默认使用Config生成）
        """
        self.session_id = session_id
        
        # 生成文件路径
        if video_path is None:
            video_path = Config.get_video_file_path(session_id)
        if audio_path is None:
            audio_path = Config.get_audio_file_path(session_id)
        
        self.video_path = Path(video_path)
        self.audio_path = Path(audio_path)
        
        # 创建录制器
        self.video_recorder: Optional[VideoRecorder] = None
        self.audio_recorder: Optional[AudioRecorder] = None
        
        logger.info(
            f"初始化媒体录制器: session_id={session_id}, "
            f"video={self.video_path}, audio={self.audio_path}"
        )
    
    def start(self, record_video: bool = True, record_audio: bool = True, auto_capture_audio: bool = False):
        """
        开始录制
        
        Args:
            record_video: 是否录制视频
            record_audio: 是否录制音频
            auto_capture_audio: 是否自动从麦克风捕获音频（默认False）
                               如果False，音频数据通过write_audio_chunk()手动写入
                               如果True，自动从服务器麦克风捕获（不推荐，会与WebSocket数据冲突）
            
        Raises:
            RecordingStartError: 如果启动失败
        """
        try:
            # Path resolution is intentionally side-effect free.  A recording
            # directory appears only when formal capture is actually starting.
            if record_video:
                self.video_path.parent.mkdir(parents=True, exist_ok=True)
            if record_audio:
                self.audio_path.parent.mkdir(parents=True, exist_ok=True)
            if record_video:
                self.video_recorder = VideoRecorder(
                    self.video_path,
                    self.session_id
                )
                self.video_recorder.start()
                logger.info("视频录制已启动")
            
            if record_audio:
                self.audio_recorder = AudioRecorder(
                    self.audio_path,
                    self.session_id
                )
                # 默认不自动捕获，通过WebSocket接收的数据手动写入
                self.audio_recorder.start(auto_capture=auto_capture_audio)
                logger.info("音频录制已启动")
            
            logger.info(f"媒体录制已启动: session_id={self.session_id}")
            
        except Exception as e:
            logger.error(f"启动媒体录制失败: {e}")
            # 清理已启动的录制器
            self.stop()
            raise RecordingStartError(f"启动媒体录制失败: {e}") from e
    
    def stop(self):
        """
        停止录制
        
        Raises:
            RecordingStopError: 如果停止失败
        """
        errors = []
        
        try:
            if self.video_recorder and self.video_recorder.is_active():
                try:
                    self.video_recorder.stop()
                    logger.info("视频录制已停止")
                except Exception as e:
                    logger.error(f"停止视频录制失败: {e}")
                    errors.append(f"视频: {e}")
            
            if self.audio_recorder and self.audio_recorder.is_active():
                try:
                    self.audio_recorder.stop()
                    logger.info("音频录制已停止")
                except Exception as e:
                    logger.error(f"停止音频录制失败: {e}")
                    errors.append(f"音频: {e}")
            
            if errors:
                raise RecordingStopError(f"停止录制时出错: {', '.join(errors)}")
            
            logger.info(f"媒体录制已停止: session_id={self.session_id}")
            
        except RecordingStopError:
            raise
        except Exception as e:
            logger.error(f"停止媒体录制时出错: {e}")
            raise RecordingStopError(f"停止媒体录制失败: {e}") from e
        finally:
            self.cleanup()
    
    def write_video_frame(self, frame):
        """
        写入视频帧
        
        Args:
            frame: 视频帧（numpy数组或base64字符串）
            
        Raises:
            RecordingException: 如果写入失败
        """
        if not self.video_recorder:
            raise RecordingException("视频录制器未初始化")
        
        if isinstance(frame, str):
            # 如果是base64字符串
            self.video_recorder.write_from_base64(frame)
        else:
            # 如果是numpy数组
            self.video_recorder.write(frame)
    
    def write_audio_chunk(self, audio_data):
        """
        写入音频块
        
        Args:
            audio_data: 音频数据（bytes或base64字符串）
            
        Raises:
            RecordingException: 如果写入失败
        """
        if not self.audio_recorder:
            raise RecordingException("音频录制器未初始化")
        
        if isinstance(audio_data, str):
            # 如果是base64字符串
            self.audio_recorder.write_from_base64(audio_data)
        else:
            # 如果是bytes或numpy数组
            self.audio_recorder.write(audio_data)
    
    def is_recording(self) -> bool:
        """
        检查是否正在录制
        
        Returns:
            True如果视频或音频任一正在录制
        """
        video_active = self.video_recorder and self.video_recorder.is_active()
        audio_active = self.audio_recorder and self.audio_recorder.is_active()
        return video_active or audio_active
    
    def get_video_duration(self) -> Optional[float]:
        """获取视频录制时长"""
        if self.video_recorder:
            return self.video_recorder.get_duration()
        return None
    
    def get_audio_duration(self) -> Optional[float]:
        """获取音频录制时长"""
        if self.audio_recorder:
            return self.audio_recorder.get_duration()
        return None
    
    def get_statistics(self) -> dict:
        """
        获取录制统计信息
        
        Returns:
            统计信息字典
        """
        stats = {
            'session_id': self.session_id,
            'video_path': str(self.video_path) if self.video_path else None,
            'audio_path': str(self.audio_path) if self.audio_path else None,
            'is_recording': self.is_recording(),
        }
        
        if self.video_recorder:
            stats['video'] = {
                'is_active': self.video_recorder.is_active(),
                'duration': self.video_recorder.get_duration(),
                'frame_count': self.video_recorder.get_frame_count(),
            }
        
        if self.audio_recorder:
            stats['audio'] = {
                'is_active': self.audio_recorder.is_active(),
                'duration': self.audio_recorder.get_duration(),
                'chunk_count': self.audio_recorder.get_frame_count(),
            }
        
        return stats
    
    def cleanup(self):
        """清理资源"""
        if self.video_recorder:
            try:
                self.video_recorder.cleanup()
            except Exception as e:
                logger.warning(f"清理视频录制器时出错: {e}")
            finally:
                self.video_recorder = None
        
        if self.audio_recorder:
            try:
                self.audio_recorder.cleanup()
            except Exception as e:
                logger.warning(f"清理音频录制器时出错: {e}")
            finally:
                self.audio_recorder = None
        
        logger.debug("媒体录制器资源已清理")
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.stop()
        return False

