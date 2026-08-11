"""
核心算法模块
包含视觉分析、音频分析、比对器等核心算法

模块结构：
- models: 核心数据模型
- base_analyzer: 分析器基类
- base_matcher: 比对器基类
- registry: 分析器注册表（新）
- config_manager: 配置管理器（新）
- auto_register: 自动注册模块（新）
- buffer: 滑动窗口数据缓冲区
- accumulator: 会话累积器
- vision/: 视觉分析器
- audio/: 音频分析器
- pipelines/: 分析流水线
"""

from app.core.models import (
    # 枚举
    AnalysisMode,
    AnalyzerStatus,
    AnalyzerType,
    # 数据模型
    AnalysisContext,
    AnalysisResult,
    MatchResult,
    WindowData,
    SessionSummary,
    AnalyzerConfig,
    Action,
    Trigger
)

from app.core.base_analyzer import (
    BaseAnalyzer,
    BaseVisionAnalyzer,
    BaseAudioAnalyzer,
    BaseWindowAnalyzer
)

from app.core.base_matcher import (
    BaseMatcher,
    BasePoseMatcher,
    BaseSpeechMatcher
)

# 新增：注册表和配置管理
from app.core.registry import (
    AnalyzerRegistry,
    AnalyzerMode as RegistryMode,
    register_analyzer,
    register_matcher,
    get_registry
)

from app.core.config_manager import (
    AnalyzerConfigManager,
    get_config_manager,
    reset_config_manager
)

from app.core.auto_register import (
    auto_register,
    register_all_analyzers,
    register_all_matchers
)

from app.core.buffer import (
    BufferConfig,
    DataBuffer,
    MultiSessionBuffer,
    get_buffer_manager
)

from app.core.accumulator import (
    AccumulatorConfig,
    Accumulator,
    MultiSessionAccumulator,
    get_accumulator_manager
)

from app.core.actions import (
    ActionType,
    ActionTarget,
    ActionResult,
    ActionDefinition,
    ActionFactory,
    ActionExecutor
)

from app.core.trigger import (
    TriggerType,
    TriggerCondition,
    TriggerDefinition,
    TriggerEvaluator,
    TriggerSystem,
    TriggerFactory,
    get_trigger_system
)

# Mock分析器
from app.core.vision import (
    MockPoseAnalyzer,
    MockPoseNormalizer,
    MockFaceAnalyzer,
    MockAttentionAnalyzer,
    COCO_KEYPOINTS,
    EMOTIONS
)

from app.core.audio import (
    MockSpeechAnalyzer,
    MockSessionSpeechAnalyzer
)

# Mock比对器
from app.core.matchers import (
    MockPoseMatcher,
    MockSpeechMatcher
)

# 流水线
from app.core.pipelines import (
    BasePipeline,
    PipelineManager,
    get_pipeline_manager,
    VisionPipeline,
    AudioPipeline,
    ImitationAudioPipeline
)

__all__ = [
    # 枚举
    'AnalysisMode',
    'AnalyzerStatus',
    'AnalyzerType',
    # 数据模型
    'AnalysisContext',
    'AnalysisResult',
    'MatchResult',
    'WindowData',
    'SessionSummary',
    'AnalyzerConfig',
    'Action',
    'Trigger',
    # 基类
    'BaseAnalyzer',
    'BaseVisionAnalyzer',
    'BaseAudioAnalyzer',
    'BaseWindowAnalyzer',
    'BaseMatcher',
    'BasePoseMatcher',
    'BaseSpeechMatcher',
    # 注册表和配置（新）
    'AnalyzerRegistry',
    'RegistryMode',
    'register_analyzer',
    'register_matcher',
    'get_registry',
    'AnalyzerConfigManager',
    'get_config_manager',
    'reset_config_manager',
    'auto_register',
    'register_all_analyzers',
    'register_all_matchers',
    # 缓冲区
    'BufferConfig',
    'DataBuffer',
    'MultiSessionBuffer',
    'get_buffer_manager',
    # 累积器
    'AccumulatorConfig',
    'Accumulator',
    'MultiSessionAccumulator',
    'get_accumulator_manager',
    # 动作
    'ActionType',
    'ActionTarget',
    'ActionResult',
    'ActionDefinition',
    'ActionFactory',
    'ActionExecutor',
    # 触发器
    'TriggerType',
    'TriggerCondition',
    'TriggerDefinition',
    'TriggerEvaluator',
    'TriggerSystem',
    'TriggerFactory',
    'get_trigger_system',
    # Mock视觉分析器
    'MockPoseAnalyzer',
    'MockPoseNormalizer',
    'MockFaceAnalyzer',
    'MockAttentionAnalyzer',
    'COCO_KEYPOINTS',
    'EMOTIONS',
    # Mock音频分析器
    'MockSpeechAnalyzer',
    'MockSessionSpeechAnalyzer',
    # Mock比对器
    'MockPoseMatcher',
    'MockSpeechMatcher',
    # 流水线
    'BasePipeline',
    'PipelineManager',
    'get_pipeline_manager',
    'VisionPipeline',
    'AudioPipeline',
    'ImitationAudioPipeline'
]
