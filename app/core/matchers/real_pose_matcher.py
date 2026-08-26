"""
真实姿态比对器
使用 MediaPipe 进行实际姿态检测和比对
"""
import time
import os
from typing import Optional, Dict, Any, List
import numpy as np

from app.core.base_matcher import BasePoseMatcher
from app.core.models import MatchResult, AnalysisResult, AnalysisContext
from app.core.vision.real_pose_analyzer import (
    RealPoseAnalyzer, 
    RealPoseNormalizer, 
    MEDIAPIPE_KEYPOINTS
)
from app.utils.logger import setup_logger

logger = setup_logger('real_pose_matcher')


class RealPoseMatcher(BasePoseMatcher):
    """
    真实姿态比对器
    
    使用 MediaPipe 检测姿态并进行真实比对
    与前端 pose_similarity.js 算法一致
    
    Type A：实时分析与控制
    """
    
    def __init__(
        self,
        threshold: float = 0.85,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        初始化真实姿态比对器
        
        Args:
            threshold: 匹配阈值（超过此值视为匹配成功）
            config: 配置参数，支持:
                - model_path: 模型路径
                - min_detection_confidence: 最小检测置信度
        """
        super().__init__(threshold, config)
        
        self._config = config or {}
        self._min_keypoint_visibility = float(
            self._config.get('min_keypoint_visibility', 0.35)
        )
        self._action_sigma = float(self._config.get('action_sigma', 0.55))
        self._allow_mirror = bool(self._config.get('allow_mirror', True))
        self._stable_frames = max(1, int(self._config.get('stable_frames', 4)))
        self._stable_hold_seconds = max(
            0.0,
            float(self._config.get('stable_hold_seconds', 0.6)),
        )
        self._max_frame_gap_seconds = max(
            0.05,
            float(self._config.get('max_frame_gap_seconds', 0.55)),
        )
        
        # 目标姿态（归一化后）
        self._target_keypoints: Optional[List[Dict]] = None  # 原始关键点
        self._target_normalized: Optional[List[List[float]]] = None  # 归一化后
        self._target_action_features: Optional[Dict[int, Dict[str, float]]] = None
        self._target_pose_name: str = "default"
        self._target_image_path: Optional[str] = None
        
        # 姿态分析器（用于从图片提取目标姿态）
        self._pose_analyzer: Optional[RealPoseAnalyzer] = None
        
        # 比对统计
        self._match_count = 0
        self._total_count = 0
        self._score_history: List[float] = []
        self._stability_by_session: Dict[str, Dict[str, Any]] = {}
        self._last_similarity_details: Dict[str, Any] = {}
        
        logger.info(f"真实姿态比对器已创建: threshold={threshold}")
    
    def _get_analyzer(self) -> RealPoseAnalyzer:
        """获取或创建姿态分析器"""
        if self._pose_analyzer is None:
            self._pose_analyzer = RealPoseAnalyzer(config=self._config)
            if not self._pose_analyzer.initialize():
                raise RuntimeError("无法初始化姿态分析器")
        return self._pose_analyzer
    
    def set_target(self, target_image: np.ndarray) -> bool:
        """
        设置目标姿态图片
        
        Args:
            target_image: 目标图片（BGR numpy 数组）
        
        Returns:
            True如果设置成功
        """
        try:
            analyzer = self._get_analyzer()
            
            # 从图片检测姿态
            keypoints = analyzer.detect_from_image(target_image)
            if not keypoints:
                logger.warning("无法从目标图片检测到姿态")
                return False
            
            # 归一化
            normalized = RealPoseNormalizer.normalize(keypoints)
            if not normalized:
                logger.warning("姿态归一化失败")
                return False
            action_features = RealPoseNormalizer.normalize_action(keypoints)
            if not action_features:
                logger.warning("动作关节归一化失败")
                return False
            
            self._target_keypoints = keypoints
            self._target_normalized = normalized
            self._target_action_features = action_features
            self._target = target_image
            self._target_features = action_features
            self._target_pose_name = "target_from_image"
            self.reset_stability()
            
            # 标记为已初始化
            self._is_initialized = True
            
            logger.info(f"设置目标姿态成功: {len(keypoints)} 关键点")
            return True
            
        except Exception as e:
            logger.error(f"设置目标姿态失败: {e}")
            return False
    
    def set_target_from_path(self, image_path: str) -> bool:
        """
        从文件路径设置目标姿态
        
        Args:
            image_path: 目标图片路径
        
        Returns:
            True如果设置成功
        """
        import cv2
        
        if not os.path.exists(image_path):
            logger.error(f"目标图片不存在: {image_path}")
            return False
        
        try:
            image = cv2.imread(image_path)
            if image is None:
                logger.error(f"无法读取目标图片: {image_path}")
                return False
            
            success = self.set_target(image)
            if success:
                self._target_image_path = image_path
                self._target_pose_name = os.path.basename(image_path)
            
            return success
            
        except Exception as e:
            logger.error(f"设置目标姿态失败: {e}")
            return False
    
    def set_target_keypoints(
        self,
        keypoints: List[Dict],
        name: str = "target"
    ) -> bool:
        """
        直接设置目标姿态关键点
        
        Args:
            keypoints: 目标姿态的关键点列表（33个）
            name: 目标姿态名称
        
        Returns:
            True如果设置成功
        """
        try:
            # 归一化
            normalized = RealPoseNormalizer.normalize(keypoints)
            if not normalized:
                logger.warning("姿态归一化失败")
                return False
            action_features = RealPoseNormalizer.normalize_action(keypoints)
            if not action_features:
                logger.warning("动作关节归一化失败")
                return False
            
            self._target_keypoints = keypoints
            self._target_normalized = normalized
            self._target_action_features = action_features
            self._target = keypoints
            self._target_features = action_features
            self._target_pose_name = name
            self.reset_stability()
            
            # 标记为已初始化
            self._is_initialized = True
            
            logger.info(f"设置目标姿态: {name}, {len(keypoints)} 关键点")
            return True
            
        except Exception as e:
            logger.error(f"设置目标关键点失败: {e}")
            return False
    
    def extract_features(
        self,
        data: Any,
    ) -> Optional[Dict[int, Dict[str, float]]]:
        """
        提取特征（归一化坐标）
        
        Args:
            data: 输入数据，支持:
                - AnalysisResult: 从姿态分析结果提取
                - List[Dict]: 直接传入关键点列表
                - np.ndarray: 图片，自动检测姿态
        
        Returns:
            归一化后的坐标列表 [[x, y], ...]
        """
        try:
            keypoints = None
            
            if isinstance(data, AnalysisResult):
                # 从分析结果提取
                keypoints = data.data.get('keypoints', [])
            elif isinstance(data, list):
                # 直接使用关键点列表
                keypoints = data
            elif isinstance(data, np.ndarray):
                # 图像输入，需要先分析
                analyzer = self._get_analyzer()
                keypoints = analyzer.detect_from_image(data)
            else:
                logger.warning(f"不支持的数据类型: {type(data)}")
                return None
            
            if not keypoints:
                return None
            
            action_features = RealPoseNormalizer.normalize_action(keypoints)
            return action_features if action_features else None
            
        except Exception as e:
            logger.error(f"提取特征失败: {e}")
            return None
    
    def compute_similarity(
        self, 
        features1: Dict[int, Dict[str, float]],
        features2: Dict[int, Dict[str, float]],
    ) -> float:
        """
        计算两个归一化姿态的相似度
        
        使用与前端 pose_similarity.js 一致的算法
        
        Args:
            features1: 归一化坐标1
            features2: 归一化坐标2
        
        Returns:
            相似度 (0-1)
        """
        if not features1 or not features2:
            return 0.0
        
        self._last_similarity_details = (
            RealPoseNormalizer.compute_action_similarity_details(
                features1,
                features2,
                min_visibility=self._min_keypoint_visibility,
                sigma=self._action_sigma,
                allow_mirror=self._allow_mirror,
            )
        )
        return float(self._last_similarity_details.get('score') or 0.0)
    
    def _get_match_details(
        self, 
        features: Dict[int, Dict[str, float]],
        score: float
    ) -> Dict[str, Any]:
        """
        获取匹配详细信息
        
        Args:
            features: 输入特征（归一化坐标）
            score: 匹配分数
        
        Returns:
            详细信息字典
        """
        keypoint_details: Dict[str, Dict[str, float]] = {}
        target = self._target_action_features or {}
        mirrored = bool(self._last_similarity_details.get('mirrored'))
        used = set(self._last_similarity_details.get('keypoints_used') or [])
        for target_index in sorted(used):
            live_index = (
                RealPoseNormalizer.MIRROR_PAIRS.get(target_index, target_index)
                if mirrored
                else target_index
            )
            live_point = features.get(live_index)
            target_point = target.get(target_index)
            if not live_point or not target_point:
                continue
            live_x = float(live_point.get('x', 0.0))
            if mirrored:
                live_x = -live_x
            distance = float(np.hypot(
                live_x - float(target_point.get('x', 0.0)),
                float(live_point.get('y', 0.0))
                - float(target_point.get('y', 0.0)),
            ))
            kp_name = (
                MEDIAPIPE_KEYPOINTS[target_index]
                if target_index < len(MEDIAPIPE_KEYPOINTS)
                else f"point_{target_index}"
            )
            keypoint_details[kp_name] = {
                'distance': round(distance, 3),
                'visibility': round(float(live_point.get('visibility', 0.0)), 3),
            }
        
        return {
            'score': score,
            'threshold': self._threshold,
            'target_pose_name': self._target_pose_name,
            'target_image_path': self._target_image_path,
            'algorithm_version': 'mediapipe-action-joints-v2',
            'coverage': round(float(self._last_similarity_details.get('coverage') or 0.0), 3),
            'mirrored': mirrored,
            'average_distance': self._last_similarity_details.get('distance'),
            'matched_keypoints': len(keypoint_details),
            'total_keypoints': len(keypoint_details),
            'keypoint_details': keypoint_details,
            'statistics': {
                'total_matches': self._match_count,
                'total_attempts': self._total_count,
                'match_rate': round(self._match_count / max(self._total_count, 1), 3)
            }
        }
    
    def match_from_result(
        self,
        analysis_result: AnalysisResult,
        context: Optional[AnalysisContext] = None
    ) -> Optional[MatchResult]:
        """
        从分析结果执行匹配
        
        Args:
            analysis_result: 姿态分析结果
            context: 分析上下文（可选）
        
        Returns:
            匹配结果，如果无法匹配返回 None
        """
        # 检查是否设置了目标
        if not self._target_action_features:
            logger.debug("未设置目标姿态，跳过匹配")
            return None
        
        if context is None:
            context = AnalysisContext(
                session_id=analysis_result.session_id,
                frame_index=analysis_result.frame_index
            )
        
        # 更新统计
        self._total_count += 1
        
        # 使用基类的match方法
        result = super().match(analysis_result, context)
        
        if result:
            raw_passed = bool(result.passed)
            stable = self._apply_stability(
                context.session_id,
                raw_passed=raw_passed,
                timestamp=float(result.timestamp),
            )
            result.passed = bool(stable['passed'])
            result.details.update({
                'raw_passed': raw_passed,
                'stable_passed': result.passed,
                'stable_frames': stable['frames'],
                'required_stable_frames': self._stable_frames,
                'hold_ms': round(stable['hold_seconds'] * 1000.0),
                'required_hold_ms': round(self._stable_hold_seconds * 1000.0),
            })
            if result.passed:
                self._match_count += 1
            self._score_history.append(result.score)
            if len(self._score_history) > 100:
                self._score_history.pop(0)
        
        return result

    def _apply_stability(
        self,
        session_id: str,
        *,
        raw_passed: bool,
        timestamp: float,
    ) -> Dict[str, Any]:
        """Require a continuous pose hold before exposing a successful match."""
        key = str(session_id or 'default')
        state = self._stability_by_session.get(key)
        if (
            not raw_passed
            or state is None
            or timestamp < float(state.get('last_timestamp', 0.0))
            or timestamp - float(state.get('last_timestamp', 0.0))
            > self._max_frame_gap_seconds
        ):
            if not raw_passed:
                self._stability_by_session.pop(key, None)
                return {'passed': False, 'frames': 0, 'hold_seconds': 0.0}
            state = {
                'first_timestamp': timestamp,
                'last_timestamp': timestamp,
                'frames': 1,
            }
            self._stability_by_session[key] = state
        else:
            state['last_timestamp'] = timestamp
            state['frames'] = int(state.get('frames', 0)) + 1

        hold_seconds = max(
            0.0,
            float(state['last_timestamp']) - float(state['first_timestamp']),
        )
        passed = (
            int(state['frames']) >= self._stable_frames
            and hold_seconds >= self._stable_hold_seconds
        )
        return {
            'passed': passed,
            'frames': int(state['frames']),
            'hold_seconds': hold_seconds,
        }

    def reset_stability(self, session_id: Optional[str] = None) -> None:
        """Clear temporal pose state after target/audio/course transitions."""
        if session_id is None:
            self._stability_by_session.clear()
            return
        self._stability_by_session.pop(str(session_id), None)
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取比对统计"""
        return {
            'total_matches': self._match_count,
            'total_attempts': self._total_count,
            'match_rate': round(self._match_count / max(self._total_count, 1), 3),
            'average_score': round(
                sum(self._score_history) / max(len(self._score_history), 1), 3
            ),
            'score_history': self._score_history[-10:],
            'has_target': self._target_action_features is not None,
            'target_name': self._target_pose_name
        }
    
    def reset_statistics(self) -> None:
        """重置统计"""
        self._match_count = 0
        self._total_count = 0
        self._score_history.clear()
    
    def reset_target(self) -> None:
        """重置目标姿态"""
        self._target_keypoints = None
        self._target_normalized = None
        self._target_action_features = None
        self._target = None
        self._target_features = None
        self._target_pose_name = "default"
        self._target_image_path = None
        self.reset_stability()
        logger.info("目标姿态已重置")
    
    def cleanup(self) -> None:
        """清理资源"""
        if self._pose_analyzer:
            self._pose_analyzer.cleanup()
            self._pose_analyzer = None
        logger.info("真实姿态比对器资源已清理")

