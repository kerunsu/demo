"""
比对器基类
用于 Type A（实时分析+控制）场景中的目标比对
"""
from abc import ABC, abstractmethod
from typing import Any, Optional, Dict
import numpy as np
import time

from app.core.models import (
    AnalyzerType,
    MatchResult,
    AnalysisContext
)
from app.utils.logger import setup_logger

logger = setup_logger('base_matcher')


class BaseMatcher(ABC):
    """
    比对器抽象基类
    
    用于将实时数据与预设目标进行比对，返回匹配度。
    典型场景：
    - 姿态比对：儿童姿态与目标图片姿态比对
    - 语音比对：儿童发音与目标语音比对
    """
    
    def __init__(
        self,
        matcher_type: AnalyzerType,
        threshold: float = 0.8,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        初始化比对器
        
        Args:
            matcher_type: 比对器类型
            threshold: 匹配阈值 (0-1)
            config: 配置参数
        """
        self._matcher_type = matcher_type
        self._threshold = threshold
        self._config = config or {}
        self._target = None
        self._target_features = None
        self._is_initialized = False
        
        logger.debug(f"创建比对器: type={matcher_type.value}, threshold={threshold}")
    
    @property
    def matcher_type(self) -> AnalyzerType:
        """返回比对器类型"""
        return self._matcher_type
    
    @property
    def threshold(self) -> float:
        """返回匹配阈值"""
        return self._threshold
    
    @threshold.setter
    def threshold(self, value: float) -> None:
        """设置匹配阈值"""
        if 0 <= value <= 1:
            self._threshold = value
        else:
            raise ValueError("阈值必须在0-1之间")
    
    @property
    def has_target(self) -> bool:
        """检查是否已设置目标"""
        return self._target is not None
    
    @property
    def is_ready(self) -> bool:
        """检查比对器是否就绪"""
        return self._is_initialized and self._target is not None
    
    def initialize(self) -> bool:
        """
        初始化比对器
        
        Returns:
            True如果初始化成功
        """
        try:
            self._do_initialize()
            self._is_initialized = True
            logger.info(f"比对器初始化成功: {self._matcher_type.value}")
            return True
        except Exception as e:
            logger.error(f"比对器初始化失败: {self._matcher_type.value}, 错误: {e}")
            return False
    
    def _do_initialize(self) -> None:
        """
        实际的初始化逻辑
        
        子类应该重写此方法
        """
        pass
    
    def cleanup(self) -> None:
        """清理比对器资源"""
        try:
            self._do_cleanup()
            self._target = None
            self._target_features = None
            self._is_initialized = False
            logger.info(f"比对器已清理: {self._matcher_type.value}")
        except Exception as e:
            logger.error(f"比对器清理失败: {self._matcher_type.value}, 错误: {e}")
    
    def _do_cleanup(self) -> None:
        """
        实际的清理逻辑
        
        子类应该重写此方法
        """
        pass
    
    @abstractmethod
    def set_target(self, target: Any) -> bool:
        """
        设置比对目标
        
        Args:
            target: 目标数据（如目标图片、目标音频）
        
        Returns:
            True如果设置成功
        """
        pass
    
    @abstractmethod
    def extract_features(self, data: Any) -> Optional[Any]:
        """
        提取特征
        
        Args:
            data: 输入数据
        
        Returns:
            提取的特征，失败返回None
        """
        pass
    
    @abstractmethod
    def compute_similarity(self, features1: Any, features2: Any) -> float:
        """
        计算两个特征的相似度
        
        Args:
            features1: 特征1
            features2: 特征2
        
        Returns:
            相似度 (0-1)
        """
        pass
    
    def match(self, data: Any, context: AnalysisContext) -> Optional[MatchResult]:
        """
        执行比对
        
        Args:
            data: 输入数据（实时数据）
            context: 分析上下文
        
        Returns:
            匹配结果
        """
        if not self.is_ready:
            logger.warning(f"比对器未就绪: {self._matcher_type.value}")
            return None
        
        try:
            # 提取输入数据的特征
            features = self.extract_features(data)
            if features is None:
                return None
            
            # 计算相似度
            score = self.compute_similarity(features, self._target_features)
            
            # 判断是否达到阈值
            passed = score >= self._threshold
            
            # 获取详细信息
            details = self._get_match_details(features, score)
            
            result = MatchResult(
                session_id=context.session_id,
                matcher_type=self._matcher_type.value,
                timestamp=time.time(),
                score=score,
                passed=passed,
                threshold=self._threshold,
                details=details,
                frame_index=context.frame_index
            )
            
            logger.debug(
                f"比对完成: type={self._matcher_type.value}, "
                f"score={score:.3f}, passed={passed}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"比对失败: {self._matcher_type.value}, 错误: {e}")
            return None
    
    def _get_match_details(self, features: Any, score: float) -> Dict[str, Any]:
        """
        获取匹配详细信息
        
        子类可以重写此方法以返回更多详细信息
        
        Args:
            features: 输入特征
            score: 匹配分数
        
        Returns:
            详细信息字典
        """
        return {
            'score': score,
            'threshold': self._threshold
        }
    
    def get_info(self) -> Dict[str, Any]:
        """获取比对器信息"""
        return {
            'matcher_type': self._matcher_type.value,
            'threshold': self._threshold,
            'has_target': self.has_target,
            'is_ready': self.is_ready,
            'config': self._config
        }


class BasePoseMatcher(BaseMatcher):
    """
    姿态比对器基类
    
    用于比对儿童姿态与目标图片姿态
    """
    
    def __init__(
        self,
        threshold: float = 0.8,
        config: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            AnalyzerType.POSE_MATCHER,
            threshold,
            config
        )
    
    @abstractmethod
    def set_target(self, target_image: np.ndarray) -> bool:
        """
        设置目标姿态图片
        
        Args:
            target_image: 目标图片（numpy数组）
        
        Returns:
            True如果设置成功
        """
        pass
    
    def set_target_from_path(self, image_path: str) -> bool:
        """
        从文件路径设置目标图片
        
        Args:
            image_path: 图片路径
        
        Returns:
            True如果设置成功
        """
        import cv2
        
        try:
            image = cv2.imread(image_path)
            if image is None:
                logger.error(f"无法读取图片: {image_path}")
                return False
            return self.set_target(image)
        except Exception as e:
            logger.error(f"设置目标图片失败: {e}")
            return False


class BaseSpeechMatcher(BaseMatcher):
    """
    语音比对器基类
    
    用于比对儿童发音与目标语音
    """
    
    def __init__(
        self,
        threshold: float = 0.8,
        config: Optional[Dict[str, Any]] = None
    ):
        super().__init__(
            AnalyzerType.SPEECH_MATCHER,
            threshold,
            config
        )
    
    @abstractmethod
    def set_target(self, target_audio: bytes) -> bool:
        """
        设置目标音频
        
        Args:
            target_audio: 目标音频数据
        
        Returns:
            True如果设置成功
        """
        pass
    
    def set_target_text(self, target_text: str) -> bool:
        """
        设置目标文本（用于语音识别后比对）
        
        Args:
            target_text: 目标文本
        
        Returns:
            True如果设置成功
        """
        self._target = target_text
        self._target_features = target_text
        logger.info(f"设置目标文本: {target_text}")
        return True

