"""
音频录制器
使用wave和pyaudio录制音频
"""
import threading
import wave
import pyaudio
import numpy as np
from pathlib import Path
from typing import Optional
from datetime import datetime
from queue import Queue
from app.recorder.base_recorder import BaseRecorder
from app.config import Config
from app.utils.exceptions import (
    RecordingStartError,
    RecordingStopError,
    RecordingException
)
from app.utils.logger import setup_logger

logger = setup_logger('audio_recorder')


class AudioRecorder(BaseRecorder):
    """
    音频录制器
    
    使用pyaudio捕获音频，使用wave保存为WAV文件
    支持实时音频流录制
    """
    
    def __init__(
        self,
        output_path: Path,
        session_id: str,
        sample_rate: int = None,
        channels: int = None,
        chunk_size: int = 1024,
        format: int = None
    ):
        """
        初始化音频录制器
        
        Args:
            output_path: 输出文件路径
            session_id: 会话ID
            sample_rate: 采样率（默认使用Config.AUDIO_SAMPLE_RATE）
            channels: 声道数（默认使用Config.AUDIO_CHANNELS）
            chunk_size: 每次读取的音频块大小
            format: 音频格式（默认pyaudio.paInt16）
        """
        super().__init__(output_path, session_id)
        
        self.sample_rate = sample_rate or Config.AUDIO_SAMPLE_RATE
        self.channels = channels or Config.AUDIO_CHANNELS
        self.chunk_size = chunk_size
        self.format = format or pyaudio.paInt16
        
        self.audio: Optional[pyaudio.PyAudio] = None
        self.stream: Optional[pyaudio.Stream] = None
        self.wave_file: Optional[wave.Wave_write] = None
        self._lock = threading.Lock()
        self._audio_queue: Queue = Queue()
        self._recording_thread: Optional[threading.Thread] = None
        self._stop_recording = False
        
        logger.debug(
            f"音频录制器配置: {self.sample_rate}Hz, "
            f"{self.channels}声道, chunk_size={self.chunk_size}"
        )
    
    def start(self, auto_capture: bool = True):
        """
        开始录制
        
        Args:
            auto_capture: 是否自动从麦克风捕获音频（默认True）
                         如果False，只初始化文件，通过write()方法手动写入数据
        """
        if self.is_recording:
            logger.warning("录制器已经在运行")
            return
        
        try:
            with self._lock:
                # 初始化PyAudio（用于获取音频格式信息）
                self.audio = pyaudio.PyAudio()
                
                # 打开WAV文件
                self.wave_file = wave.open(str(self.output_path), 'wb')
                self.wave_file.setnchannels(self.channels)
                self.wave_file.setsampwidth(self.audio.get_sample_size(self.format))
                self.wave_file.setframerate(self.sample_rate)
                
                self.is_recording = True
                self.start_time = datetime.utcnow()
                self.frame_count = 0
                self._stop_recording = False
                
                # 如果启用自动捕获，打开音频流并启动录制线程
                if auto_capture:
                    # 打开音频流（从麦克风输入）
                    self.stream = self.audio.open(
                        format=self.format,
                        channels=self.channels,
                        rate=self.sample_rate,
                        input=True,
                        frames_per_buffer=self.chunk_size
                    )
                    
                    # 启动录制线程
                    self._recording_thread = threading.Thread(
                        target=self._recording_loop,
                        daemon=True
                    )
                    self._recording_thread.start()
                    logger.info(
                        f"开始音频录制（自动捕获）: {self.output_path}"
                    )
                else:
                    # 不启动自动捕获，只初始化文件，等待手动写入
                    logger.info(
                        f"开始音频录制（手动写入）: {self.output_path}"
                    )
                
        except Exception as e:
            logger.error(f"启动音频录制失败: {e}")
            self.cleanup()
            raise RecordingStartError(f"启动音频录制失败: {e}") from e
    
    def _recording_loop(self):
        """录制循环（在后台线程中运行）"""
        try:
            while not self._stop_recording and self.is_recording:
                if self.stream:
                    # 读取音频数据
                    data = self.stream.read(self.chunk_size, exception_on_overflow=False)
                    
                    # 写入WAV文件
                    if self.wave_file:
                        self.wave_file.writeframes(data)
                        self.frame_count += 1
        except Exception as e:
            logger.error(f"音频录制循环出错: {e}")
            self.is_recording = False
    
    def stop(self):
        """停止录制"""
        if not self.is_recording:
            logger.warning("录制器未在运行")
            return
        
        try:
            with self._lock:
                self._stop_recording = True
                self.is_recording = False
                
                # 等待录制线程结束（如果存在）
                if self._recording_thread and self._recording_thread.is_alive():
                    self._recording_thread.join(timeout=2.0)
                
                # 关闭流（如果存在）
                if self.stream:
                    self.stream.stop_stream()
                    self.stream.close()
                    self.stream = None
                
                # 关闭文件
                if self.wave_file:
                    self.wave_file.close()
                    self.wave_file = None
                
                duration = self.get_duration()
                
                logger.info(
                    f"停止音频录制: {self.output_path}, "
                    f"时长: {duration:.2f}秒, 块数: {self.frame_count}"
                )
                
        except Exception as e:
            logger.error(f"停止音频录制失败: {e}")
            raise RecordingStopError(f"停止音频录制失败: {e}") from e
        finally:
            self.cleanup()
    
    def write(self, audio_data):
        """
        写入音频数据
        
        注意：对于实时录制，音频数据通常通过_stream自动捕获
        此方法用于手动写入音频数据（例如从WebSocket接收的音频块）
        
        Args:
            audio_data: 音频数据（bytes或numpy数组）
            
        Raises:
            RecordingException: 如果写入失败或录制器未启动
        """
        if not self.is_recording:
            raise RecordingException("录制器未启动，无法写入音频数据")
        
        if self.wave_file is None:
            raise RecordingException("音频文件未打开")
        
        try:
            with self._lock:
                if isinstance(audio_data, np.ndarray):
                    # 如果是numpy数组，转换为bytes
                    audio_data = audio_data.tobytes()
                
                if self.wave_file:
                    self.wave_file.writeframes(audio_data)
                    self.frame_count += 1
                    
        except Exception as e:
            logger.error(f"写入音频数据失败: {e}")
            raise RecordingException(f"写入音频数据失败: {e}") from e
    
    def write_from_base64(self, base64_data: str):
        """
        从base64字符串写入音频数据
        
        Args:
            base64_data: base64编码的音频数据
        """
        import base64
        
        try:
            # 解码base64
            audio_bytes = base64.b64decode(base64_data)
            self.write(audio_bytes)
            
        except Exception as e:
            logger.error(f"从base64写入音频失败: {e}")
            raise RecordingException(f"从base64写入音频失败: {e}") from e
    
    def cleanup(self):
        """清理资源"""
        try:
            if self.stream:
                self.stream.stop_stream()
                self.stream.close()
                self.stream = None
            
            if self.wave_file:
                self.wave_file.close()
                self.wave_file = None
            
            if self.audio:
                self.audio.terminate()
                self.audio = None
                
        except Exception as e:
            logger.warning(f"清理音频录制器时出错: {e}")
        finally:
            self.is_recording = False
            self._stop_recording = True
            logger.debug("音频录制器资源已清理")

