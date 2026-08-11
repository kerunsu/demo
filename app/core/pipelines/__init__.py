"""
分析流水线模块

提供各种分析流水线的实现
"""

from app.core.pipelines.base_pipeline import (
    BasePipeline,
    PipelineManager,
    get_pipeline_manager
)

from app.core.pipelines.vision_pipeline import VisionPipeline
from app.core.pipelines.audio_pipeline import (
    AudioPipeline,
    ImitationAudioPipeline
)

__all__ = [
    # 基类
    'BasePipeline',
    'PipelineManager',
    'get_pipeline_manager',
    
    # 视觉流水线
    'VisionPipeline',
    
    # 音频流水线
    'AudioPipeline',
    'ImitationAudioPipeline',
]
