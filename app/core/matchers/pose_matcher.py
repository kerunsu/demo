"""
姿态比对器（Mock）
用于比较儿童姿态与目标姿态的相似度
"""
import time
import random
from typing import Optional, Dict, Any, List
import numpy as np

from app.core.base_matcher import BasePoseMatcher
from app.core.models import MatchResult, AnalysisResult, AnalysisContext
from app.core.vision.pose_analyzer import MockPoseNormalizer, COCO_KEYPOINTS
from app.utils.logger import setup_logger

logger = setup_logger('pose_matcher')


class MockPoseMatcher(BasePoseMatcher):
    """
    Mock姿态比对器
    
    比较儿童的姿态与目标姿态，返回匹配分数
    用于"模仿"课程等需要姿态比对的场景
    
    Type A：实时分析与控制
    """
    
    def __init__(
        self,
        threshold: float = 0.85,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        初始化Mock姿态比对器
        
        Args:
            threshold: 匹配阈值（超过此值视为匹配成功）
            config: 配置参数
        """
        super().__init__(threshold, config)
        
        # 目标姿态（可以动态设置）
        self._target_pose: Optional[List[Dict]] = None
        self._target_pose_name: str = "default"
        
        # Mock配置
        self._base_match_score = config.get('base_match_score', 0.8) if config else 0.8
        self._noise_level = config.get('noise_level', 0.15) if config else 0.15
        
        # 比对统计
        self._match_count = 0
        self._total_count = 0
        self._score_history: List[float] = []
        
        logger.info(f"Mock姿态比对器已创建: threshold={threshold}")
    
    def set_target(self, target_image: np.ndarray) -> bool:
        """
        设置目标姿态图片（实现抽象方法）
        
        Mock实现：从图片提取姿态关键点
        
        Args:
            target_image: 目标图片（numpy数组）
        
        Returns:
            True如果设置成功
        """
        try:
            # Mock: 从图片"提取"姿态（实际生成模拟数据）
            from app.core.vision.pose_analyzer import MockPoseAnalyzer
            
            mock_analyzer = MockPoseAnalyzer()
            self._target_pose = mock_analyzer._generate_mock_keypoints(target_image.shape)
            self._target = target_image
            self._target_features = MockPoseNormalizer.normalize(self._target_pose)
            self._target_pose_name = "target_from_image"
            
            logger.info(f"设置目标姿态: {len(self._target_pose)} 关键点")
            return True
        except Exception as e:
            logger.error(f"设置目标姿态失败: {e}")
            return False
    
    def set_target_pose(
        self,
        keypoints: List[Dict],
        name: str = "target"
    ) -> None:
        """
        直接设置目标姿态关键点
        
        Args:
            keypoints: 目标姿态的关键点列表
            name: 目标姿态名称
        """
        self._target_pose = keypoints
        self._target = keypoints
        self._target_features = MockPoseNormalizer.normalize(keypoints)
        self._target_pose_name = name
        logger.info(f"设置目标姿态: {name}, keypoints={len(keypoints) if keypoints else 0}")
    
    def extract_features(self, data: Any) -> Optional[List[Dict]]:
        """
        提取特征（实现抽象方法）
        
        从分析结果中提取姿态关键点并归一化
        
        Args:
            data: 输入数据（AnalysisResult或关键点列表）
        
        Returns:
            归一化后的关键点列表
        """
        try:
            if isinstance(data, AnalysisResult):
                keypoints = data.data.get('keypoints', [])
            elif isinstance(data, list):
                keypoints = data
            elif isinstance(data, np.ndarray):
                # 图像输入，需要先分析
                from app.core.vision.pose_analyzer import MockPoseAnalyzer
                analyzer = MockPoseAnalyzer()
                keypoints = analyzer._generate_mock_keypoints(data.shape)
            else:
                logger.warning(f"不支持的数据类型: {type(data)}")
                return None
            
            if not keypoints:
                return None
            
            return MockPoseNormalizer.normalize(keypoints)
            
        except Exception as e:
            logger.error(f"提取特征失败: {e}")
            return None
    
    def compute_similarity(self, features1: Any, features2: Any) -> float:
        """
        计算两个特征的相似度（实现抽象方法）
        
        Args:
            features1: 特征1（归一化关键点）
            features2: 特征2（归一化关键点）
        
        Returns:
            相似度 (0-1)
        """
        if not features1 or not features2:
            return 0.0
        
        # 使用归一化器计算相似度
        similarity = MockPoseNormalizer.compute_similarity(features1, features2)
        
        # 添加噪声使结果更真实
        similarity += random.uniform(-self._noise_level, self._noise_level)
        similarity = max(0.0, min(1.0, similarity))
        
        return round(similarity, 3)
    
    def _get_match_details(self, features: Any, score: float) -> Dict[str, Any]:
        """
        获取匹配详细信息
        
        Args:
            features: 输入特征
            score: 匹配分数
        
        Returns:
            详细信息字典
        """
        # 计算各关键点的匹配情况
        keypoint_scores = {}
        matched_count = 0
        
        if features and self._target_features:
            for i, (child_kp, target_kp) in enumerate(zip(features, self._target_features)):
                kp_name = COCO_KEYPOINTS[i] if i < len(COCO_KEYPOINTS) else f"kp_{i}"
                
                if child_kp.get('confidence', 0) > 0.5 and target_kp.get('confidence', 0) > 0.5:
                    dx = child_kp['x'] - target_kp['x']
                    dy = child_kp['y'] - target_kp['y']
                    distance = (dx**2 + dy**2) ** 0.5
                    kp_score = max(0, 1 - distance * 2)
                    keypoint_scores[kp_name] = round(kp_score, 3)
                    
                    if kp_score > 0.7:
                        matched_count += 1
        
        return {
            'score': score,
            'threshold': self._threshold,
            'target_pose_name': self._target_pose_name,
            'matched_keypoints': matched_count,
            'total_keypoints': len(keypoint_scores),
            'keypoint_scores': keypoint_scores,
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
    ) -> MatchResult:
        """
        从分析结果执行匹配（便捷方法）
        
        Args:
            analysis_result: 姿态分析结果
            context: 分析上下文（可选）
        
        Returns:
            匹配结果
        """
        if context is None:
            context = AnalysisContext(
                session_id=analysis_result.session_id,
                frame_index=analysis_result.frame_index
            )
        
        # 更新统计
        self._total_count += 1
        
        # 使用基类的match方法
        result = super().match(analysis_result, context)
        
        if result and result.passed:
            self._match_count += 1
        
        if result:
            self._score_history.append(result.score)
            if len(self._score_history) > 100:
                self._score_history.pop(0)
        
        return result
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取比对统计"""
        return {
            'total_matches': self._match_count,
            'total_attempts': self._total_count,
            'match_rate': round(self._match_count / max(self._total_count, 1), 3),
            'average_score': round(
                sum(self._score_history) / max(len(self._score_history), 1), 3
            ),
            'score_history': self._score_history[-10:]
        }
    
    def reset_statistics(self) -> None:
        """重置统计"""
        self._match_count = 0
        self._total_count = 0
        self._score_history.clear()
