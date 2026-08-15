"""
音频分析流水线
处理音频块的分析和比对
支持 Mock/Real 分析器切换（对齐 VisionPipeline）
"""
from typing import Dict, List, Any, Optional, Tuple
import numpy as np
import time

from app.core.pipelines.base_pipeline import BasePipeline
from app.core.models import (
    AnalysisMode,
    AnalysisContext,
    AnalysisResult,
    MatchResult
)
from app.core.registry import AnalyzerRegistry
from app.core.config_manager import get_config_manager
from app.core.audio import MockSessionSpeechAnalyzer
from app.utils.logger import setup_logger

logger = setup_logger('audio_pipeline')


class AudioPipeline(BasePipeline):
    """
    音频分析流水线

    支持：
    - Type A: 实时语音分析 + 语音比对
    - Type C: 会话统计（总词数、语音时长等）
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__('audio', config)

        config_mgr = get_config_manager()

        # 语音分析器（Type A）
        try:
            speech_mode = config_mgr.get_analyzer_mode('speech')
            speech_config = config_mgr.get_analyzer_config('speech')
            if config and config.get('speech'):
                speech_config = {**speech_config, **config.get('speech', {})}
            self._speech_analyzer = AnalyzerRegistry.create_analyzer(
                'speech',
                mode=speech_mode,
                config=speech_config,
            )
            mode_str = "Real" if getattr(speech_mode, 'value', speech_mode) == 'real' else "Mock"
            logger.info("使用 %s 语音分析器", mode_str)
            self.add_realtime_analyzer(self._speech_analyzer)
        except Exception as e:
            logger.error("创建语音分析器失败，回退 Mock: %s", e)
            from app.core.audio import MockSpeechAnalyzer
            self.record_initialization_failure('speech', e, required=True)
            self._speech_analyzer = MockSpeechAnalyzer(
                mode=AnalysisMode.REALTIME,
                config=config.get('speech', {}) if config else {}
            )
            self.add_realtime_analyzer(self._speech_analyzer)

        # 会话语音分析器（Type C）仍用 Mock 汇总器（消费 AnalysisResult 列表）
        self._session_speech_analyzer = MockSessionSpeechAnalyzer(
            config=config.get('session_speech', {}) if config else {}
        )
        self.add_session_analyzer(self._session_speech_analyzer)

        # 语音比对器
        try:
            matcher_mode = config_mgr.get_matcher_mode('speech') if hasattr(config_mgr, 'get_matcher_mode') else None
            matcher_config = {}
            if hasattr(config_mgr, 'get_matcher_config'):
                matcher_config = config_mgr.get_matcher_config('speech') or {}
            speech_threshold = (
                (config or {}).get('speech_threshold')
                or matcher_config.get('threshold')
                or 0.80
            )
            # threshold 若为百分制则归一化
            if isinstance(speech_threshold, (int, float)) and speech_threshold > 1:
                speech_threshold = float(speech_threshold) / 100.0

            self._speech_matcher = AnalyzerRegistry.create_matcher(
                'speech',
                mode=matcher_mode,
                threshold=float(speech_threshold),
                config=matcher_config or ((config or {}).get('speech_matcher') or {}),
            )
            self.add_matcher('speech', self._speech_matcher)
        except Exception as e:
            logger.warning("创建 speech matcher 失败，回退 Mock: %s", e)
            from app.core.matchers import MockSpeechMatcher
            speech_threshold = config.get('speech_threshold', 0.80) if config else 0.80
            if isinstance(speech_threshold, (int, float)) and speech_threshold > 1:
                speech_threshold = float(speech_threshold) / 100.0
            self._speech_matcher = MockSpeechMatcher(
                threshold=float(speech_threshold),
                config=config.get('speech_matcher', {}) if config else {}
            )
            self.add_matcher('speech', self._speech_matcher)

        self._chunk_count = 0
        self._analysis_results: List[AnalysisResult] = []
        self._uninit_warn_at = 0.0

        logger.info("音频流水线已创建")

    @property
    def speech_analyzer(self):
        return self._speech_analyzer

    @property
    def session_speech_analyzer(self):
        return self._session_speech_analyzer

    @property
    def speech_matcher(self):
        return self._speech_matcher

    def set_speech_target(
        self,
        text: str,
        phonemes: Optional[List[str]] = None
    ) -> None:
        if hasattr(self._speech_matcher, 'set_target_text_extended'):
            self._speech_matcher.set_target_text_extended(text, phonemes)
        elif hasattr(self._speech_matcher, 'set_target'):
            self._speech_matcher.set_target(text)

    def process_realtime(
        self,
        audio_chunk: np.ndarray,
        context: AnalysisContext
    ) -> Tuple[List[AnalysisResult], List[MatchResult]]:
        if not self._is_initialized:
            now = time.time()
            if now - float(getattr(self, '_uninit_warn_at', 0.0) or 0.0) >= 5.0:
                self._uninit_warn_at = now
                logger.warning("流水线未初始化（连续音频分析跳过；检查 FunASR/torch 或 voice-service）")
            return [], []

        analysis_results = []
        match_results = []

        self._chunk_count += 1
        context.update_audio_chunk_index(self._chunk_count)

        speech_result = self._speech_analyzer.analyze_chunk(audio_chunk, context)
        if speech_result:
            analysis_results.append(speech_result)
            self._analysis_results.append(speech_result)

            if getattr(self._speech_matcher, 'has_target', False):
                vad = speech_result.data.get('vad', {})
                is_speech = vad.get('is_speech', speech_result.data.get('is_speech'))
                if is_speech:
                    if hasattr(self._speech_matcher, 'match_from_result'):
                        match_result = self._speech_matcher.match_from_result(
                            speech_result, context
                        )
                    else:
                        match_result = None
                    if match_result:
                        match_results.append(match_result)

        return analysis_results, match_results

    def process_window(
        self,
        video_frames: List[Tuple[float, np.ndarray]],
        audio_chunks: List[Tuple[float, np.ndarray]],
        context: AnalysisContext
    ) -> List[AnalysisResult]:
        return []

    def process_session(
        self,
        all_results: List[AnalysisResult],
        context: AnalysisContext
    ) -> List[AnalysisResult]:
        if not self._is_initialized:
            logger.warning("流水线未初始化")
            return []

        results = []
        speech_results = [r for r in all_results if r.analyzer_type == 'speech']

        session_summary = self._session_speech_analyzer.analyze_session(
            speech_results, context
        )
        if session_summary:
            results.append(session_summary)

        matcher_stats = {}
        if hasattr(self._speech_matcher, 'get_statistics'):
            matcher_stats = self._speech_matcher.get_statistics()

        analyzer_stats = {}
        if hasattr(self._speech_analyzer, 'get_statistics'):
            analyzer_stats = self._speech_analyzer.get_statistics()

        summary_data = {
            'summary_type': 'audio',
            'total_chunks': self._chunk_count,
            'speech_analysis': {
                'total_results': len(speech_results),
                'analyzer_statistics': analyzer_stats
            },
            'matcher_statistics': matcher_stats
        }

        summary_result = AnalysisResult(
            session_id=context.session_id,
            analyzer_type='audio_summary',
            mode=AnalysisMode.SESSION,
            timestamp=time.time(),
            data=summary_data,
            confidence=1.0
        )
        results.append(summary_result)

        logger.info(
            f"音频会话总结: chunks={self._chunk_count}, "
            f"speech_results={len(speech_results)}"
        )

        return results

    def reset_session(self) -> None:
        self._chunk_count = 0
        self._analysis_results.clear()
        if hasattr(self._speech_analyzer, 'reset_statistics'):
            self._speech_analyzer.reset_statistics()
        if hasattr(self._speech_matcher, 'reset_statistics'):
            self._speech_matcher.reset_statistics()
        # 必须清掉上一课的语音目标，否则配对/排序仍会持续 match → 误触发表扬
        if hasattr(self._speech_matcher, 'reset_target'):
            self._speech_matcher.reset_target()
        elif hasattr(self._speech_matcher, 'clear_target'):
            self._speech_matcher.clear_target()
        else:
            for attr in ('_target', '_target_text', '_target_features', '_target_phonemes'):
                if hasattr(self._speech_matcher, attr):
                    setattr(self._speech_matcher, attr, None if attr != '_target_phonemes' else [])
        logger.debug("音频流水线会话已重置")

    def get_analysis_results(self) -> List[AnalysisResult]:
        return self._analysis_results.copy()


class ImitationAudioPipeline(AudioPipeline):
    """模仿课程音频流水线（命名课）"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        default_config = {
            'speech_threshold': 0.80,
            'speech_matcher': {
                'weights': {
                    'text': 0.6,
                    'phoneme': 0.3,
                    'prosody': 0.1
                }
            }
        }
        if config:
            default_config.update(config)

        super().__init__(default_config)
        self._name = 'imitation_audio'
        logger.info("模仿课程音频流水线已创建")
