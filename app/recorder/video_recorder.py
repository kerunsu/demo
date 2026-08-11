"""
视频录制器
使用OpenCV录制视频
"""
import threading
import cv2
import numpy as np
from pathlib import Path
from typing import Optional
from datetime import datetime
from app.recorder.base_recorder import BaseRecorder
from app.config import Config
from app.utils.exceptions import RecordingStartError, RecordingStopError, RecordingException
from app.utils.logger import setup_logger

logger = setup_logger('video_recorder')


class VideoRecorder(BaseRecorder):
    """
    视频录制器
    
    使用OpenCV的VideoWriter进行视频录制
    支持异步写入（使用队列缓冲）
    """
    
    def __init__(
        self,
        output_path: Path,
        session_id: str,
        width: int = None,
        height: int = None,
        fps: int = None,
        codec: str = None
    ):
        """
        初始化视频录制器
        
        Args:
            output_path: 输出文件路径
            session_id: 会话ID
            width: 视频宽度（默认使用Config.VIDEO_WIDTH）
            height: 视频高度（默认使用Config.VIDEO_HEIGHT）
            fps: 帧率（默认使用Config.VIDEO_FPS）
            codec: 编解码器（默认使用Config.VIDEO_CODEC）
        """
        super().__init__(output_path, session_id)
        
        self.width = width or Config.VIDEO_WIDTH
        self.height = height or Config.VIDEO_HEIGHT
        self.fps = fps or Config.VIDEO_FPS
        self.codec = codec or Config.VIDEO_CODEC
        
        self.writer: Optional[cv2.VideoWriter] = None
        self._lock = threading.Lock()
        
        # 四字符代码（FourCC）用于指定视频编解码器
        self.fourcc = cv2.VideoWriter_fourcc(*self._get_fourcc(self.codec))
        
        logger.debug(
            f"视频录制器配置: {self.width}x{self.height}, "
            f"{self.fps}fps, codec={self.codec}"
        )
    
    @staticmethod
    def _get_fourcc(codec: str) -> str:
        """
        将编解码器名称转换为FourCC代码
        
        Args:
            codec: 编解码器名称（如'libx264', 'mp4v'等）
            
        Returns:
            FourCC代码字符串
        """
        codec_map = {
            'libx264': 'avc1',  # H.264
            'mp4v': 'mp4v',     # MPEG-4
            'xvid': 'XVID',     # Xvid
            'mjpg': 'MJPG',     # Motion-JPEG (推荐，Windows兼容性好)
        }
        # 默认使用 MJPG，兼容性最好
        return codec_map.get(codec.lower(), 'MJPG')
    
    def start(self):
        """开始录制"""
        if self.is_recording:
            logger.warning("录制器已经在运行")
            return
        
        try:
            with self._lock:
                self.writer = cv2.VideoWriter(
                    str(self.output_path),
                    self.fourcc,
                    self.fps,
                    (self.width, self.height)
                )
                
                if not self.writer.isOpened():
                    raise RecordingStartError(f"无法打开视频写入器: {self.output_path}")
                
                self.is_recording = True
                self.start_time = datetime.utcnow()
                self.frame_count = 0
                
                logger.info(f"开始视频录制: {self.output_path}")
                
        except Exception as e:
            logger.error(f"启动视频录制失败: {e}")
            if self.writer:
                self.writer.release()
                self.writer = None
            raise RecordingStartError(f"启动视频录制失败: {e}") from e
    
    def stop(self):
        """停止录制"""
        if not self.is_recording:
            logger.warning("录制器未在运行")
            return
        
        try:
            with self._lock:
                if self.writer:
                    self.writer.release()
                    self.writer = None
                
                self.is_recording = False
                duration = self.get_duration()
                
                logger.info(
                    f"停止视频录制: {self.output_path}, "
                    f"时长: {duration:.2f}秒, 帧数: {self.frame_count}"
                )
                
        except Exception as e:
            logger.error(f"停止视频录制失败: {e}")
            raise RecordingStopError(f"停止视频录制失败: {e}") from e
    
    def write(self, frame):
        """
        写入视频帧
        
        Args:
            frame: 视频帧（numpy数组，BGR格式，shape为(height, width, 3))
            
        Raises:
            RecordingException: 如果写入失败或录制器未启动
        """
        if not self.is_recording:
            raise RecordingException("录制器未启动，无法写入帧")
        
        if self.writer is None:
            raise RecordingException("视频写入器未初始化")
        
        try:
            # 确保帧的尺寸正确
            if frame.shape[:2] != (self.height, self.width):
                # 调整帧大小
                frame = cv2.resize(frame, (self.width, self.height))
            
            with self._lock:
                if self.writer and self.writer.isOpened():
                    self.writer.write(frame)
                    self.frame_count += 1
                else:
                    raise RecordingException("视频写入器未打开")
                    
        except Exception as e:
            logger.error(f"写入视频帧失败: {e}")
            raise RecordingException(f"写入视频帧失败: {e}") from e
    
    def write_from_base64(self, base64_data: str):
        """
        从base64字符串写入帧
        
        Args:
            base64_data: base64编码的图像数据
        """
        import base64
        from io import BytesIO
        from PIL import Image
        
        try:
            # 解码base64
            image_data = base64.b64decode(base64_data)
            image = Image.open(BytesIO(image_data))
            
            # 转换为numpy数组（RGB）
            frame_rgb = np.array(image)
            
            # 转换为BGR（OpenCV格式）
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
            
            # 写入帧
            self.write(frame_bgr)
            
        except Exception as e:
            logger.error(f"从base64写入帧失败: {e}")
            raise RecordingException(f"从base64写入帧失败: {e}") from e
    
    def cleanup(self):
        """清理资源"""
        if self.writer:
            try:
                self.writer.release()
            except Exception as e:
                logger.warning(f"清理视频写入器时出错: {e}")
            finally:
                self.writer = None
        
        self.is_recording = False
        logger.debug("视频录制器资源已清理")

