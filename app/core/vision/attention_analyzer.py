"""
注意力分析器（Mock）
Type B：滑动窗口分析
分析过去N秒的数据，综合得出注意力评分
"""
import random
import time
from typing import Optional, Dict, Any, List
import numpy as np

from app.core.base_analyzer import BaseWindowAnalyzer
from app.core.models import (
    AnalysisMode,
    AnalyzerType,
    AnalysisResult,
    AnalysisContext,
    WindowData
)
from app.utils.logger import setup_logger

logger = setup_logger('attention_analyzer')


class MockAttentionAnalyzer(BaseWindowAnalyzer):
    """
    Mock注意力分析器（Type B：滑动窗口分析）
    
    分析过去N秒的视频和音频数据，综合得出注意力评分。
    真实模型可能会分析：
    - 姿态稳定性
    - 眼动/视线方向
    - 头部姿态变化
    - 语音活动
    - 面部表情变化
    
    Mock版本返回模拟的注意力评分
    """
    
    def __init__(
        self,
        mode: AnalysisMode = AnalysisMode.WINDOW,
        config: Optional[Dict[str, Any]] = None,
        window_size: Optional[float] = None,
        **kwargs
    ):
        """
        初始化Mock注意力分析器
        
        Args:
            mode: 分析模式（Registry 统一传入；窗口分析器固定为 WINDOW）
            config: 配置参数
            window_size: 窗口大小（秒）；也可从 config.window_size 读取
        """
        config = config or {}
        ws = float(window_size if window_size is not None else config.get('window_size', 10.0))
        super().__init__(AnalyzerType.ATTENTION, ws, config)
        # mode 由基类固定为 WINDOW；保留参数以兼容 AnalyzerRegistry.create_analyzer
        
        # Mock配置
        self._base_attention = config.get('base_attention', 0.7)
        self._noise_level = config.get('noise_level', 0.15)
        
        # 注意力历史（用于生成平滑的变化）
        self._attention_history: List[float] = []
        self._max_history = 10
        
        logger.info(f"Mock注意力分析器已创建: window_size={ws}s")
    
    def _calculate_data_quality(
        self,
        video_frames: List,
        audio_chunks: List
    ) -> float:
        """
        计算数据质量（基于数据量）
        
        Returns:
            数据质量评分 (0-1)
        """
        expected_frames = self._window_size * 30  # 假设30fps
        expected_chunks = self._window_size * 10  # 假设10块/秒
        
        video_quality = min(len(video_frames) / expected_frames, 1.0) if expected_frames > 0 else 0.0
        audio_quality = min(len(audio_chunks) / expected_chunks, 1.0) if expected_chunks > 0 else 0.0
        
        return (video_quality + audio_quality) / 2
    
    def _generate_attention_score(self, data_quality: float) -> float:
        """
        生成模拟的注意力评分
        
        基于历史评分生成平滑变化的注意力值
        
        Args:
            data_quality: 数据质量
        
        Returns:
            注意力评分 (0-1)
        """
        # 基础注意力
        base = self._base_attention
        
        # 如果有历史数据，基于历史生成平滑变化
        if self._attention_history:
            last_attention = self._attention_history[-1]
            # 允许小幅变化
            change = random.uniform(-self._noise_level, self._noise_level)
            new_attention = last_attention + change
        else:
            # 首次生成
            new_attention = base + random.uniform(-self._noise_level, self._noise_level)
        
        # 考虑数据质量
        new_attention *= (0.5 + 0.5 * data_quality)
        
        # 限制在0-1范围内
        new_attention = max(0.0, min(1.0, new_attention))
        
        # 更新历史
        self._attention_history.append(new_attention)
        if len(self._attention_history) > self._max_history:
            self._attention_history.pop(0)
        
        return round(new_attention, 3)
    
    def _analyze_motion(self, video_frames: List) -> Dict[str, float]:
        """
        分析运动特征（Mock）
        
        Returns:
            运动特征字典
        """
        if len(video_frames) < 2:
            return {'motion_level': 0.0, 'stability': 1.0}
        
        # Mock: 生成随机的运动水平
        motion_level = random.uniform(0.1, 0.5)
        stability = 1.0 - motion_level
        
        return {
            'motion_level': round(motion_level, 3),
            'stability': round(stability, 3)
        }
    
    def _analyze_audio_activity(self, audio_chunks: List) -> Dict[str, Any]:
        """
        分析音频活动（Mock）
        
        Returns:
            音频活动字典
        """
        if not audio_chunks:
            return {'is_speaking': False, 'speech_ratio': 0.0}
        
        # Mock: 随机生成语音活动
        is_speaking = random.random() < 0.3  # 30%概率在说话
        speech_ratio = random.uniform(0.1, 0.4) if is_speaking else 0.0
        
        return {
            'is_speaking': is_speaking,
            'speech_ratio': round(speech_ratio, 3),
            'audio_chunks_analyzed': len(audio_chunks)
        }
    
    def analyze_window(
        self,
        video_frames: List,
        audio_chunks: List,
        context: AnalysisContext
    ) -> Optional[AnalysisResult]:
        """
        分析窗口数据
        
        Args:
            video_frames: 视频帧列表 [(timestamp, frame), ...]
            audio_chunks: 音频块列表 [(timestamp, chunk), ...]
            context: 分析上下文
        
        Returns:
            注意力分析结果
        """
        if not self.is_ready:
            if not self.initialize():
                return None
        
        try:
            # 计算数据质量
            data_quality = self._calculate_data_quality(video_frames, audio_chunks)
            
            # 生成注意力评分
            attention_score = self._generate_attention_score(data_quality)
            
            # 分析运动特征
            motion = self._analyze_motion(video_frames)
            
            # 分析音频活动
            audio_activity = self._analyze_audio_activity(audio_chunks)
            
            # 确定注意力状态
            if attention_score >= 0.7:
                attention_state = 'high'
            elif attention_score >= 0.4:
                attention_state = 'medium'
            else:
                attention_state = 'low'
            
            # 计算趋势
            trend = 'stable'
            if len(self._attention_history) >= 3:
                recent = self._attention_history[-3:]
                if recent[-1] > recent[0] + 0.1:
                    trend = 'increasing'
                elif recent[-1] < recent[0] - 0.1:
                    trend = 'decreasing'
            
            # 构建结果数据
            data = {
                'score': attention_score,
                'state': attention_state,
                'trend': trend,
                'window_size': self._window_size,
                'data_quality': round(data_quality, 3),
                'motion': motion,
                'audio_activity': audio_activity,
                'frame_count': len(video_frames),
                'audio_chunk_count': len(audio_chunks),
                'history': self._attention_history.copy()
            }
            
            result = AnalysisResult(
                session_id=context.session_id,
                analyzer_type=self._analyzer_type.value,
                mode=self._mode,
                timestamp=time.time(),
                data=data,
                confidence=data_quality
            )
            
            logger.debug(
                f"注意力分析完成: score={attention_score}, "
                f"state={attention_state}, trend={trend}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"注意力分析失败: {e}")
            return None
    
    def reset_history(self) -> None:
        """重置注意力历史"""
        self._attention_history.clear()
    
    def set_base_attention(self, value: float) -> None:
        """设置基础注意力值（用于测试）"""
        self._base_attention = max(0.0, min(1.0, value))

