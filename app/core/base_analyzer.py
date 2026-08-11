"""
分析器基类
定义所有分析器的统一接口
"""
from abc import ABC, abstractmethod
from typing import Any, Optional, Dict
import numpy as np

from app.core.models import (
    AnalysisMode,
    AnalyzerStatus,
    AnalyzerType,
    AnalysisResult,
    AnalysisContext
)
from app.utils.logger import setup_logger

logger = setup_logger('base_analyzer')


class BaseAnalyzer(ABC):
    """
    分析器抽象基类
    
    所有分析器（视觉/音频）都应继承此类并实现抽象方法。
    支持三种分析模式：
    - REALTIME: 实时逐帧/逐块分析
    - WINDOW: 滑动窗口分析
    - SESSION: 会话级汇总分析
    """
    
    def __init__(
        self,
        analyzer_type: AnalyzerType,
        mode: AnalysisMode = AnalysisMode.REALTIME,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        初始化分析器
        
        Args:
            analyzer_type: 分析器类型
            mode: 分析模式
            config: 配置参数，支持:
                - sample_rate: 采样率 (0.0-1.0，默认 1.0 表示每帧都分析)
        """
        self._analyzer_type = analyzer_type
        self._mode = mode
        self._config = config or {}
        self._status = AnalyzerStatus.UNINITIALIZED
        self._is_initialized = False
        self._last_error: Optional[str] = None
        
        # 采样控制
        self._sample_rate = self._config.get('sample_rate', 1.0)
        self._call_count = 0
        self._analysis_count = 0
        
        logger.debug(
            f"创建分析器: type={analyzer_type.value}, mode={mode.value}, "
            f"sample_rate={self._sample_rate}"
        )
    
    @property
    def analyzer_type(self) -> AnalyzerType:
        """返回分析器类型"""
        return self._analyzer_type
    
    @property
    def mode(self) -> AnalysisMode:
        """返回分析模式"""
        return self._mode
    
    @property
    def status(self) -> AnalyzerStatus:
        """返回分析器状态"""
        return self._status
    
    @property
    def is_ready(self) -> bool:
        """检查分析器是否就绪"""
        return self._status == AnalyzerStatus.READY or self._status == AnalyzerStatus.RUNNING
    
    @property
    def config(self) -> Dict[str, Any]:
        """返回配置"""
        return self._config
    
    @property
    def sample_rate(self) -> float:
        """返回采样率"""
        return self._sample_rate
    
    @property
    def analysis_count(self) -> int:
        """返回实际分析次数"""
        return self._analysis_count

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error
    
    def should_analyze(self) -> bool:
        """
        检查当前调用是否应该执行分析（采样控制）
        
        Returns:
            True 如果应该分析，False 否则
        """
        self._call_count += 1
        
        # sample_rate = 1.0: 每次都分析
        # sample_rate = 0.5: 每2次分析1次
        # sample_rate = 0.33: 每3次分析1次
        
        if self._sample_rate >= 1.0:
            return True
        
        if self._sample_rate <= 0.0:
            return False
        
        # 使用计数器模式
        interval = int(1.0 / self._sample_rate)
        return (self._call_count % interval) == 1
    
    def initialize(self) -> bool:
        """
        初始化分析器
        
        子类可以重写此方法以加载模型等资源。
        
        Returns:
            True如果初始化成功，False否则
        """
        try:
            self._do_initialize()
            self._last_error = None
            self._status = AnalyzerStatus.READY
            self._is_initialized = True
            logger.info(f"分析器初始化成功: {self._analyzer_type.value}")
            return True
        except Exception as e:
            self._last_error = str(e)
            self._status = AnalyzerStatus.ERROR
            logger.error(f"分析器初始化失败: {self._analyzer_type.value}, 错误: {e}")
            return False
    
    def _do_initialize(self) -> None:
        """
        实际的初始化逻辑
        
        子类应该重写此方法而不是initialize()
        """
        pass
    
    def cleanup(self) -> None:
        """
        清理分析器资源
        
        子类可以重写此方法以释放模型等资源。
        """
        try:
            self._do_cleanup()
            self._status = AnalyzerStatus.STOPPED
            self._is_initialized = False
            logger.info(f"分析器已清理: {self._analyzer_type.value}")
        except Exception as e:
            logger.error(f"分析器清理失败: {self._analyzer_type.value}, 错误: {e}")
    
    def _do_cleanup(self) -> None:
        """
        实际的清理逻辑
        
        子类应该重写此方法而不是cleanup()
        """
        pass
    
    @abstractmethod
    def analyze(self, data: Any, context: AnalysisContext) -> Optional[AnalysisResult]:
        """
        执行分析
        
        Args:
            data: 输入数据（视频帧或音频块）
            context: 分析上下文
        
        Returns:
            分析结果，如果分析失败或跳过返回None
        """
        pass
    
    def analyze_with_sampling(
        self,
        data: Any,
        context: AnalysisContext
    ) -> Optional[AnalysisResult]:
        """
        带采样控制的分析
        
        自动检查 sample_rate，决定是否执行分析
        
        Args:
            data: 输入数据
            context: 分析上下文
        
        Returns:
            分析结果，如果跳过返回 None
        """
        if not self.should_analyze():
            return None
        
        self._analysis_count += 1
        return self.analyze(data, context)
    
    def get_info(self) -> Dict[str, Any]:
        """
        获取分析器信息
        
        Returns:
            分析器信息字典
        """
        return {
            'analyzer_type': self._analyzer_type.value,
            'mode': self._mode.value,
            'status': self._status.value,
            'is_ready': self.is_ready,
            'config': self._config
        }


class BaseVisionAnalyzer(BaseAnalyzer):
    """
    视觉分析器基类
    
    用于分析视频帧，如姿态估计、表情分析、眼动追踪等。
    """
    
    def __init__(
        self,
        analyzer_type: AnalyzerType,
        mode: AnalysisMode = AnalysisMode.REALTIME,
        config: Optional[Dict[str, Any]] = None
    ):
        super().__init__(analyzer_type, mode, config)
    
    @abstractmethod
    def analyze_frame(self, frame: np.ndarray, context: AnalysisContext) -> Optional[AnalysisResult]:
        """
        分析单帧视频
        
        Args:
            frame: 视频帧（numpy数组，BGR格式）
            context: 分析上下文
        
        Returns:
            分析结果
        """
        pass
    
    def analyze(self, data: Any, context: AnalysisContext) -> Optional[AnalysisResult]:
        """
        执行分析（实现基类抽象方法）
        
        Args:
            data: 视频帧（numpy数组）
            context: 分析上下文
        
        Returns:
            分析结果
        """
        if not isinstance(data, np.ndarray):
            logger.warning(f"视觉分析器收到非numpy数组数据: {type(data)}")
            return None
        
        return self.analyze_frame(data, context)


class BaseAudioAnalyzer(BaseAnalyzer):
    """
    音频分析器基类
    
    用于分析音频数据，如语音识别、情感分析等。
    支持两种分析方式：
    - analyze_chunk: 分析单个音频块（实时）
    - analyze_accumulated: 分析累积的音频数据（窗口/会话）
    """
    
    def __init__(
        self,
        analyzer_type: AnalyzerType,
        mode: AnalysisMode = AnalysisMode.REALTIME,
        config: Optional[Dict[str, Any]] = None
    ):
        super().__init__(analyzer_type, mode, config)
        self._sample_rate = config.get('sample_rate', 16000) if config else 16000
        self._channels = config.get('channels', 1) if config else 1
    
    @property
    def sample_rate(self) -> int:
        """音频采样率"""
        return self._sample_rate
    
    @property
    def channels(self) -> int:
        """音频通道数"""
        return self._channels
    
    @abstractmethod
    def analyze_chunk(self, chunk: bytes, context: AnalysisContext) -> Optional[AnalysisResult]:
        """
        分析单个音频块（实时分析）
        
        Args:
            chunk: 音频块（PCM bytes）
            context: 分析上下文
        
        Returns:
            分析结果
        """
        pass
    
    def analyze_accumulated(
        self,
        audio_data: bytes,
        context: AnalysisContext
    ) -> Optional[AnalysisResult]:
        """
        分析累积的音频数据（窗口/会话分析）
        
        默认实现调用analyze_chunk，子类可以重写以实现更复杂的逻辑。
        
        Args:
            audio_data: 累积的音频数据
            context: 分析上下文
        
        Returns:
            分析结果
        """
        return self.analyze_chunk(audio_data, context)
    
    def analyze(self, data: Any, context: AnalysisContext) -> Optional[AnalysisResult]:
        """
        执行分析（实现基类抽象方法）
        
        Args:
            data: 音频数据（bytes）
            context: 分析上下文
        
        Returns:
            分析结果
        """
        if not isinstance(data, bytes):
            logger.warning(f"音频分析器收到非bytes数据: {type(data)}")
            return None
        
        return self.analyze_chunk(data, context)


class BaseWindowAnalyzer(BaseAnalyzer):
    """
    滑动窗口分析器基类（Type B）
    
    用于分析过去一段时间的数据，如注意力检测。
    """
    
    def __init__(
        self,
        analyzer_type: AnalyzerType,
        window_size: float = 10.0,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        初始化窗口分析器
        
        Args:
            analyzer_type: 分析器类型
            window_size: 窗口大小（秒）
            config: 配置参数
        """
        super().__init__(analyzer_type, AnalysisMode.WINDOW, config)
        self._window_size = window_size
    
    @property
    def window_size(self) -> float:
        """窗口大小（秒）"""
        return self._window_size
    
    @abstractmethod
    def analyze_window(
        self,
        video_frames: list,
        audio_chunks: list,
        context: AnalysisContext
    ) -> Optional[AnalysisResult]:
        """
        分析窗口数据
        
        Args:
            video_frames: 视频帧列表 [(timestamp, frame), ...]
            audio_chunks: 音频块列表 [(timestamp, chunk), ...]
            context: 分析上下文
        
        Returns:
            分析结果
        """
        pass
    
    def analyze(self, data: Any, context: AnalysisContext) -> Optional[AnalysisResult]:
        """
        执行分析（实现基类抽象方法）
        
        Args:
            data: WindowData对象
            context: 分析上下文
        
        Returns:
            分析结果
        """
        from app.core.models import WindowData
        
        if not isinstance(data, WindowData):
            logger.warning(f"窗口分析器收到非WindowData数据: {type(data)}")
            return None
        
        return self.analyze_window(
            data.video_frames,
            data.audio_chunks,
            context
        )

