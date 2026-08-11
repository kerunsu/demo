"""
配置模块
"""

from app.core.config.analyzer_config import (
    AnalyzerMode,
    PoseAnalyzerConfig,
    PoseMatcherConfig,
    AnalyzerConfiguration,
    get_analyzer_config,
    set_analyzer_config,
    enable_real_analyzers,
    enable_mock_analyzers
)

__all__ = [
    'AnalyzerMode',
    'PoseAnalyzerConfig',
    'PoseMatcherConfig',
    'AnalyzerConfiguration',
    'get_analyzer_config',
    'set_analyzer_config',
    'enable_real_analyzers',
    'enable_mock_analyzers'
]

