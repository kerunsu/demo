"""
视觉分析流水线
处理视频帧的分析和比对
支持 Mock/Real 分析器切换
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
from app.core.registry import AnalyzerRegistry, AnalyzerMode
from app.core.config_manager import get_config_manager
from app.utils.logger import setup_logger

logger = setup_logger('vision_pipeline')


class VisionPipeline(BasePipeline):
    """
    视觉分析流水线
    
    支持：
    - Type A: 实时姿态分析 + 姿态比对
    - Type B: 滑动窗口注意力分析
    - Type C: 会话统计（面部表情统计等）
    
    支持 Mock/Real 模式切换
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化视觉流水线
        
        Args:
            config: 配置参数（可选，如果不提供则从配置管理器读取）
        """
        super().__init__('vision', config)
        
        # 获取配置管理器
        config_mgr = get_config_manager()
        
        # 创建姿态分析器（Type A）
        pose_mode = config_mgr.get_analyzer_mode('pose')
        pose_config = config_mgr.get_analyzer_config('pose')
        
        try:
            self._pose_analyzer = AnalyzerRegistry.create_analyzer(
                'pose',
                mode=pose_mode,
                config=pose_config
            )
            mode_str = "Real" if pose_mode.value == 'real' else "Mock"
            sample_rate = pose_config.get('sample_rate', 1.0)
            logger.info(
                f"使用 {mode_str} 姿态分析器, "
                f"采样率={sample_rate} (每{int(1.0/sample_rate) if sample_rate > 0 else 'N/A'}帧分析1次)"
            )
            self.add_realtime_analyzer(self._pose_analyzer)
        except Exception as e:
            logger.error(f"创建姿态分析器失败: {e}")
            self._pose_analyzer = None
            self.record_initialization_failure('pose', e, required=True)
        
        # 表情分析器（Type A，可选）
        if config_mgr.is_analyzer_enabled('face'):
            face_mode = config_mgr.get_analyzer_mode('face')
            face_config = config_mgr.get_analyzer_config('face')
            
            try:
                self._face_analyzer = AnalyzerRegistry.create_analyzer(
                    'face',
                    mode=face_mode,
                    config=face_config
                )
                self._face_analyzer._health_required = False
                logger.info("表情分析器已启用")
                self.add_realtime_analyzer(self._face_analyzer)
            except Exception as e:
                logger.warning(f"创建表情分析器失败: {e}")
                self._face_analyzer = None
                self.record_initialization_failure('face', e, required=False)
        else:
            self._face_analyzer = None
        
        # 注意力分析器（Type B）
        if config_mgr.is_analyzer_enabled('attention'):
            attention_mode = config_mgr.get_analyzer_mode('attention')
            attention_config = config_mgr.get_analyzer_config('attention')
            
            try:
                self._attention_analyzer = AnalyzerRegistry.create_analyzer(
                    'attention',
                    mode=attention_mode,
                    config=attention_config
                )
                logger.info("注意力分析器已启用")
                self.add_window_analyzer(self._attention_analyzer)
            except Exception as e:
                logger.warning(f"创建注意力分析器失败: {e}")
                self._attention_analyzer = None
                self.record_initialization_failure('attention', e, required=True)
        else:
            self._attention_analyzer = None
        
        # 创建姿态比对器（Type A）
        # 注意：比对器模式应该与分析器模式保持一致，避免格式不匹配
        if config_mgr.is_matcher_enabled('pose'):
            matcher_mode = config_mgr.get_matcher_mode('pose')
            # 如果比对器模式未明确设置，自动使用与分析器相同的模式
            if matcher_mode == AnalyzerMode.MOCK and pose_mode == AnalyzerMode.REAL:
                logger.warning(
                    "姿态比对器模式为 Mock，但分析器为 Real，"
                    "可能导致格式不匹配。建议设置比对器模式为 Real"
                )
            
            matcher_config = config_mgr.get_matcher_config('pose')
            threshold = matcher_config.get('threshold', 0.85)
            
            try:
                self._pose_matcher = AnalyzerRegistry.create_matcher(
                    'pose',
                    mode=matcher_mode,
                    threshold=threshold,
                    config=matcher_config
                )
                mode_str = "Real" if matcher_mode.value == 'real' else "Mock"
                logger.info(f"使用 {mode_str} 姿态比对器")
                self.add_matcher('pose', self._pose_matcher)
            except Exception as e:
                logger.error(f"创建姿态比对器失败: {e}")
                self._pose_matcher = None
                self.record_initialization_failure(
                    'matcher:pose', e, required=False
                )
        else:
            self._pose_matcher = None
        
        # 统计数据
        self._frame_count = 0
        self._analysis_results: List[AnalysisResult] = []
        
        logger.info("视觉流水线已创建")
    
    @property
    def use_real_pose(self) -> bool:
        """是否使用真实姿态分析"""
        config_mgr = get_config_manager()
        return config_mgr.get_analyzer_mode('pose').value == 'real'
    
    @property
    def pose_analyzer(self):
        """获取姿态分析器"""
        return self._pose_analyzer
    
    @property
    def face_analyzer(self):
        """获取表情分析器"""
        return self._face_analyzer
    
    @property
    def attention_analyzer(self):
        """获取注意力分析器"""
        return self._attention_analyzer
    
    @property
    def pose_matcher(self):
        """获取姿态比对器"""
        return self._pose_matcher
    
    def set_pose_target(
        self,
        target_keypoints: List[Dict],
        name: str = "target"
    ) -> bool:
        """
        设置姿态比对目标
        
        Args:
            target_keypoints: 目标姿态关键点
            name: 目标名称
        
        Returns:
            是否成功
        """
        if not self._pose_matcher:
            logger.warning("姿态比对器未启用")
            return False
        
        if hasattr(self._pose_matcher, 'set_target_keypoints'):
            return self._pose_matcher.set_target_keypoints(target_keypoints, name)
        elif hasattr(self._pose_matcher, 'set_target_pose'):
            self._pose_matcher.set_target_pose(target_keypoints, name)
            return True
        else:
            logger.error("姿态比对器不支持设置目标")
            return False
    
    def set_pose_target_from_image(self, image: np.ndarray) -> bool:
        """
        从图片设置姿态比对目标
        
        Args:
            image: 目标图片（BGR numpy 数组）
        
        Returns:
            是否成功
        """
        if not self._pose_matcher:
            logger.warning("姿态比对器未启用")
            return False
        
        if hasattr(self._pose_matcher, 'set_target'):
            return self._pose_matcher.set_target(image)
        else:
            logger.error("姿态比对器不支持从图片设置目标")
            return False
    
    def set_pose_target_from_path(self, image_path: str) -> bool:
        """
        从图片路径设置姿态比对目标
        
        Args:
            image_path: 目标图片路径
        
        Returns:
            是否成功
        """
        if not self._pose_matcher:
            logger.warning("姿态比对器未启用")
            return False
        
        if hasattr(self._pose_matcher, 'set_target_from_path'):
            return self._pose_matcher.set_target_from_path(image_path)
        else:
            # Mock 版本
            import cv2
            image = cv2.imread(image_path)
            if image is None:
                logger.error(f"无法读取目标图片: {image_path}")
                return False
            return self._pose_matcher.set_target(image)
    
    def reset_pose_target(self) -> None:
        """重置姿态比对目标"""
        if not self._pose_matcher:
            return
        
        if hasattr(self._pose_matcher, 'reset_target'):
            self._pose_matcher.reset_target()
        else:
            # Mock 版本手动重置
            self._pose_matcher._target = None
            self._pose_matcher._target_pose = None
            self._pose_matcher._target_features = None
            self._pose_matcher._target_pose_name = "default"
        logger.debug("姿态比对目标已重置")

    def reset_pose_stability(self, session_id: Optional[str] = None) -> None:
        """Reset multi-frame pose hold state without removing the target."""
        if self._pose_matcher and hasattr(self._pose_matcher, 'reset_stability'):
            self._pose_matcher.reset_stability(session_id)
    
    def process_realtime(
        self,
        frame: np.ndarray,
        context: AnalysisContext
    ) -> Tuple[List[AnalysisResult], List[MatchResult]]:
        """
        实时处理视频帧（Type A）
        
        Args:
            frame: 视频帧
            context: 分析上下文
        
        Returns:
            (分析结果列表, 匹配结果列表)
        """
        if not self._is_initialized:
            logger.warning("流水线未初始化")
            return [], []
        
        analysis_results = []
        match_results = []
        
        self._frame_count += 1
        context.update_frame_index(self._frame_count)
        
        # 1. 姿态分析（使用采样控制）
        if self._pose_analyzer:
            pose_result = self._pose_analyzer.analyze_with_sampling(frame, context)
            if pose_result:
                analysis_results.append(pose_result)
                self._analysis_results.append(pose_result)
                
                # 姿态比对（如果有目标）
                if self._pose_matcher and self._pose_matcher.has_target:
                    match_result = self._pose_matcher.match_from_result(pose_result, context)
                    if match_result:
                        match_results.append(match_result)
        
        # 2. 表情分析（可选，使用采样控制）
        if self._face_analyzer:
            face_result = self._face_analyzer.analyze_with_sampling(frame, context)
            if face_result:
                analysis_results.append(face_result)
                self._analysis_results.append(face_result)
        
        return analysis_results, match_results
    
    def process_window(
        self,
        video_frames: List[Tuple[float, np.ndarray]],
        audio_chunks: List[Tuple[float, np.ndarray]],
        context: AnalysisContext
    ) -> List[AnalysisResult]:
        """
        窗口处理（Type B）- 注意力分析
        
        Args:
            video_frames: 视频帧列表 [(timestamp, frame), ...]
            audio_chunks: 音频块列表 [(timestamp, chunk), ...]
            context: 分析上下文
        
        Returns:
            分析结果列表
        """
        if not self._is_initialized:
            logger.warning("流水线未初始化")
            return []
        
        results = []
        
        # 注意力分析
        if self._attention_analyzer:
            attention_result = self._attention_analyzer.analyze_window(
                video_frames, audio_chunks, context
            )
            if attention_result:
                results.append(attention_result)
                self._analysis_results.append(attention_result)
        
        return results
    
    def process_session(
        self,
        all_results: List[AnalysisResult],
        context: AnalysisContext
    ) -> List[AnalysisResult]:
        """
        会话结束处理（Type C）
        
        统计整个会话的视觉分析数据
        
        Args:
            all_results: 会话中所有的分析结果
            context: 分析上下文
        
        Returns:
            会话总结结果列表
        """
        if not self._is_initialized:
            logger.warning("流水线未初始化")
            return []
        
        # 统计姿态分析结果
        pose_results = [r for r in all_results if r.analyzer_type == 'pose']
        face_results = [r for r in all_results if r.analyzer_type == 'face']
        attention_results = [r for r in all_results if r.analyzer_type == 'attention']
        
        # 计算统计指标
        avg_pose_score = 0.0
        if pose_results:
            scores = [r.data.get('pose_score', 0) for r in pose_results]
            avg_pose_score = sum(scores) / len(scores)
        
        avg_attention = 0.0
        if attention_results:
            scores = [r.data.get('score', 0) for r in attention_results]
            avg_attention = sum(scores) / len(scores)
        
        # 统计情绪分布
        emotion_counts: Dict[str, int] = {}
        for r in face_results:
            emotion = r.data.get('emotion')
            if emotion:
                emotion_counts[emotion] = emotion_counts.get(emotion, 0) + 1
        
        # 构建总结结果
        matcher_stats = {}
        if self._pose_matcher and hasattr(self._pose_matcher, 'get_statistics'):
            matcher_stats = self._pose_matcher.get_statistics()
        
        summary_data = {
            'summary_type': 'vision',
            'total_frames': self._frame_count,
            'pose_analysis': {
                'count': len(pose_results),
                'average_score': round(avg_pose_score, 3)
            },
            'face_analysis': {
                'count': len(face_results),
                'emotion_distribution': emotion_counts
            },
            'attention_analysis': {
                'count': len(attention_results),
                'average_score': round(avg_attention, 3)
            },
            'matcher_statistics': matcher_stats
        }
        
        summary_result = AnalysisResult(
            session_id=context.session_id,
            analyzer_type='vision_summary',
            mode=AnalysisMode.SESSION,
            timestamp=time.time(),
            data=summary_data,
            confidence=1.0
        )
        
        logger.info(
            f"视觉会话总结: frames={self._frame_count}, "
            f"avg_attention={avg_attention:.3f}"
        )
        
        return [summary_result]
    
    def reset_session(self) -> None:
        """重置会话统计和目标"""
        self._frame_count = 0
        self._analysis_results.clear()
        self._pose_matcher.reset_statistics()
        # 重置姿态目标（切换课程时清除之前的目标）
        self.reset_pose_target()
        if self._attention_analyzer is not None and hasattr(self._attention_analyzer, 'reset_history'):
            self._attention_analyzer.reset_history()
        logger.debug("视觉流水线会话已重置（包括姿态目标）")
    
    def get_analysis_results(self) -> List[AnalysisResult]:
        """获取所有分析结果"""
        return self._analysis_results.copy()

