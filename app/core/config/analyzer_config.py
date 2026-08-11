"""
分析器配置模块

管理 Mock/Real 分析器的切换和配置
"""
import os
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from app.utils.logger import setup_logger

logger = setup_logger('analyzer_config')


class AnalyzerMode(str, Enum):
    """分析器模式"""
    MOCK = "mock"
    REAL = "real"


# ==========================================
# 姿态 (Pose) 相关配置
# ==========================================

@dataclass
class PoseAnalyzerConfig:
    """姿态分析器配置"""
    mode: AnalyzerMode = AnalyzerMode.MOCK
    model_path: str = "models/pose_landmarker_lite.task"
    min_detection_confidence: float = 0.5
    num_poses: int = 1
    # Mock 专用
    base_confidence: float = 0.85
    noise_level: float = 0.1
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'mode': self.mode.value,
            'model_path': self.model_path,
            'min_detection_confidence': self.min_detection_confidence,
            'num_poses': self.num_poses,
            'base_confidence': self.base_confidence,
            'noise_level': self.noise_level
        }


@dataclass
class PoseMatcherConfig:
    """姿态比对器配置"""
    mode: AnalyzerMode = AnalyzerMode.MOCK
    threshold: float = 0.85
    sigma: float = 0.6  # 高斯核参数
    # Mock 专用
    base_match_score: float = 0.8
    noise_level: float = 0.15
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'mode': self.mode.value,
            'threshold': self.threshold,
            'sigma': self.sigma,
            'base_match_score': self.base_match_score,
            'noise_level': self.noise_level
        }


# ==========================================
# 语音 (Speech) 相关配置 - 新增
# ==========================================

@dataclass
class SpeechAnalyzerConfig:
    """语音分析器配置"""
    mode: AnalyzerMode = AnalyzerMode.REAL
    model_name: str = "fa-zh"  # FunASR 模型名称
    sample_rate: int = 16000   # 采样率要求
    device: str = "cuda"       # 推荐使用 CUDA
    # Mock 专用
    base_confidence: float = 0.90
    noise_level: float = 0.05

    def to_dict(self) -> Dict[str, Any]:
        return {
            'mode': self.mode.value,
            'model_name': self.model_name,
            'sample_rate': self.sample_rate,
            'device': self.device,
            'base_confidence': self.base_confidence
        }


@dataclass
class SpeechMatcherConfig:
    """语音比对器配置"""
    mode: AnalyzerMode = AnalyzerMode.MOCK
    passing_threshold: float = 60.0 # 及格分数线 (0-100)
    # Mock 专用
    base_score: float = 85.0
    noise_level: float = 5.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            'mode': self.mode.value,
            'passing_threshold': self.passing_threshold,
            'base_score': self.base_score
        }


# ==========================================
# 全局配置管理
# ==========================================

@dataclass
class AnalyzerConfiguration:
    """
    全局分析器配置
    
    通过环境变量或配置文件控制 Mock/Real 切换
    包含 姿态(Pose) 和 语音(Speech) 的所有配置
    """
    # 姿态
    pose_analyzer: PoseAnalyzerConfig = field(default_factory=PoseAnalyzerConfig)
    pose_matcher: PoseMatcherConfig = field(default_factory=PoseMatcherConfig)
    
    # 语音 (新增)
    speech_analyzer: SpeechAnalyzerConfig = field(default_factory=SpeechAnalyzerConfig)
    speech_matcher: SpeechMatcherConfig = field(default_factory=SpeechMatcherConfig)
    
    # 全局开关
    use_real_analyzers: bool = False
    
    @classmethod
    def from_env(cls) -> 'AnalyzerConfiguration':
        """
        从环境变量加载配置
        
        环境变量:
            - USE_REAL_ANALYZERS: "true" 启用真实分析器
            - POSE_MODEL_PATH: 姿态模型路径
            - POSE_THRESHOLD: 姿态匹配阈值
            - SPEECH_MODEL_NAME: 语音模型名称 (如 fa-zh)
            - SPEECH_THRESHOLD: 语音及格分 (如 60.0)
        """
        config = cls()
        
        # 全局开关
        use_real = os.environ.get('USE_REAL_ANALYZERS', '').lower() == 'true'
        config.use_real_analyzers = use_real
        
        if use_real:
            # 姿态模式
            config.pose_analyzer.mode = AnalyzerMode.REAL
            config.pose_matcher.mode = AnalyzerMode.REAL
            # 语音模式
            config.speech_analyzer.mode = AnalyzerMode.REAL
            config.speech_matcher.mode = AnalyzerMode.REAL
        
        # === 姿态配置读取 ===
        model_path = os.environ.get('POSE_MODEL_PATH')
        if model_path:
            config.pose_analyzer.model_path = model_path
        
        pose_threshold_str = os.environ.get('POSE_THRESHOLD')
        if pose_threshold_str:
            try:
                config.pose_matcher.threshold = float(pose_threshold_str)
            except ValueError:
                pass

        # === 语音配置读取 (新增) ===
        speech_model = os.environ.get('SPEECH_MODEL_NAME')
        if speech_model:
            config.speech_analyzer.model_name = speech_model

        speech_threshold_str = os.environ.get('SPEECH_THRESHOLD')
        if speech_threshold_str:
            try:
                config.speech_matcher.passing_threshold = float(speech_threshold_str)
            except ValueError:
                pass
        
        logger.info(
            f"分析器配置已加载: use_real={config.use_real_analyzers}, "
            f"pose_model={config.pose_analyzer.model_path}, "
            f"speech_model={config.speech_analyzer.model_name}"
        )
        
        return config
    
    @classmethod
    def create_mock(cls) -> 'AnalyzerConfiguration':
        """创建 Mock 配置"""
        config = cls()
        config.use_real_analyzers = False
        # 设置所有子模块为 MOCK
        config.pose_analyzer.mode = AnalyzerMode.MOCK
        config.pose_matcher.mode = AnalyzerMode.MOCK
        config.speech_analyzer.mode = AnalyzerMode.MOCK
        config.speech_matcher.mode = AnalyzerMode.MOCK
        return config
    
    @classmethod
    def create_real(cls) -> 'AnalyzerConfiguration':
        """创建 Real 配置"""
        config = cls()
        config.use_real_analyzers = True
        # 设置所有子模块为 REAL
        config.pose_analyzer.mode = AnalyzerMode.REAL
        config.pose_matcher.mode = AnalyzerMode.REAL
        config.speech_analyzer.mode = AnalyzerMode.REAL
        config.speech_matcher.mode = AnalyzerMode.REAL
        return config
    
    def set_mode(self, mode: AnalyzerMode) -> None:
        """设置分析器模式"""
        # 姿态
        self.pose_analyzer.mode = mode
        self.pose_matcher.mode = mode
        # 语音
        self.speech_analyzer.mode = mode
        self.speech_matcher.mode = mode
        
        self.use_real_analyzers = (mode == AnalyzerMode.REAL)
        logger.info(f"所有分析器模式已切换: {mode.value}")


# 全局配置实例
_global_config: Optional[AnalyzerConfiguration] = None


def get_analyzer_config() -> AnalyzerConfiguration:
    """获取全局分析器配置"""
    global _global_config
    if _global_config is None:
        _global_config = AnalyzerConfiguration.from_env()
    return _global_config


def set_analyzer_config(config: AnalyzerConfiguration) -> None:
    """设置全局分析器配置"""
    global _global_config
    _global_config = config
    logger.info(f"全局分析器配置已手动更新: use_real={config.use_real_analyzers}")


def enable_real_analyzers() -> None:
    """启用真实分析器"""
    config = get_analyzer_config()
    config.set_mode(AnalyzerMode.REAL)


def enable_mock_analyzers() -> None:
    """启用 Mock 分析器"""
    config = get_analyzer_config()
    config.set_mode(AnalyzerMode.MOCK)