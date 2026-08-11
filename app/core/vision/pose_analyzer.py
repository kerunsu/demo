"""
姿态分析器（Mock）
返回模拟的姿态数据，用于验证流程
"""
import random
import time
from typing import Optional, Dict, Any, List
import numpy as np

from app.core.base_analyzer import BaseVisionAnalyzer
from app.core.models import (
    AnalysisMode,
    AnalyzerType,
    AnalysisResult,
    AnalysisContext
)
from app.utils.logger import setup_logger

logger = setup_logger('pose_analyzer')


# COCO 17关键点定义
COCO_KEYPOINTS = [
    'nose',
    'left_eye', 'right_eye',
    'left_ear', 'right_ear',
    'left_shoulder', 'right_shoulder',
    'left_elbow', 'right_elbow',
    'left_wrist', 'right_wrist',
    'left_hip', 'right_hip',
    'left_knee', 'right_knee',
    'left_ankle', 'right_ankle'
]


class MockPoseAnalyzer(BaseVisionAnalyzer):
    """
    Mock姿态分析器
    
    返回模拟的17关键点姿态数据（COCO格式）
    用于在没有真实模型时验证整个分析流程
    """
    
    def __init__(
        self,
        mode: AnalysisMode = AnalysisMode.REALTIME,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        初始化Mock姿态分析器
        
        Args:
            mode: 分析模式
            config: 配置参数
        """
        super().__init__(AnalyzerType.POSE, mode, config)
        
        # Mock配置
        self._base_confidence = config.get('base_confidence', 0.85) if config else 0.85
        self._noise_level = config.get('noise_level', 0.1) if config else 0.1
        
        # 基准姿态（站立姿势的归一化坐标）
        self._base_pose = self._generate_standing_pose()
        
        logger.info("Mock姿态分析器已创建")
    
    def _generate_standing_pose(self) -> Dict[str, Dict[str, float]]:
        """生成标准站立姿势的关键点"""
        return {
            'nose': {'x': 0.5, 'y': 0.1},
            'left_eye': {'x': 0.48, 'y': 0.08},
            'right_eye': {'x': 0.52, 'y': 0.08},
            'left_ear': {'x': 0.45, 'y': 0.1},
            'right_ear': {'x': 0.55, 'y': 0.1},
            'left_shoulder': {'x': 0.4, 'y': 0.2},
            'right_shoulder': {'x': 0.6, 'y': 0.2},
            'left_elbow': {'x': 0.35, 'y': 0.35},
            'right_elbow': {'x': 0.65, 'y': 0.35},
            'left_wrist': {'x': 0.32, 'y': 0.5},
            'right_wrist': {'x': 0.68, 'y': 0.5},
            'left_hip': {'x': 0.45, 'y': 0.5},
            'right_hip': {'x': 0.55, 'y': 0.5},
            'left_knee': {'x': 0.43, 'y': 0.7},
            'right_knee': {'x': 0.57, 'y': 0.7},
            'left_ankle': {'x': 0.42, 'y': 0.9},
            'right_ankle': {'x': 0.58, 'y': 0.9}
        }
    
    def _add_noise(self, value: float, noise_level: float) -> float:
        """添加随机噪声"""
        return value + random.uniform(-noise_level, noise_level)
    
    def _generate_mock_keypoints(self, frame_shape: tuple) -> List[Dict[str, Any]]:
        """
        生成模拟的关键点数据
        
        Args:
            frame_shape: 视频帧尺寸 (height, width, channels)
        
        Returns:
            关键点列表
        """
        height, width = frame_shape[:2]
        keypoints = []
        
        for i, name in enumerate(COCO_KEYPOINTS):
            base = self._base_pose[name]
            
            # 添加噪声并转换为像素坐标
            x = self._add_noise(base['x'], self._noise_level) * width
            y = self._add_noise(base['y'], self._noise_level) * height
            
            # 生成置信度（带随机波动）
            confidence = self._base_confidence + random.uniform(-0.1, 0.1)
            confidence = max(0.0, min(1.0, confidence))
            
            keypoints.append({
                'id': i,
                'name': name,
                'x': round(x, 2),
                'y': round(y, 2),
                'confidence': round(confidence, 3)
            })
        
        return keypoints
    
    def _estimate_pose_type(self, keypoints: List[Dict]) -> str:
        """
        估计姿态类型
        
        Returns:
            姿态类型: "standing", "sitting", "lying", "other"
        """
        # Mock: 随机返回姿态类型，但以standing为主
        r = random.random()
        if r < 0.7:
            return "standing"
        elif r < 0.9:
            return "sitting"
        else:
            return "other"
    
    def _calculate_pose_score(self, keypoints: List[Dict]) -> float:
        """
        计算姿态评分
        
        基于关键点的可见性和置信度
        """
        if not keypoints:
            return 0.0
        
        # 计算平均置信度作为评分
        total_conf = sum(kp['confidence'] for kp in keypoints)
        return round(total_conf / len(keypoints), 3)
    
    def analyze_frame(
        self,
        frame: np.ndarray,
        context: AnalysisContext
    ) -> Optional[AnalysisResult]:
        """
        分析单帧视频的姿态
        
        Args:
            frame: 视频帧（numpy数组）
            context: 分析上下文
        
        Returns:
            姿态分析结果
        """
        if not self.is_ready:
            if not self.initialize():
                return None
        
        try:
            # 生成模拟的关键点
            keypoints = self._generate_mock_keypoints(frame.shape)
            
            # 估计姿态类型
            pose_type = self._estimate_pose_type(keypoints)
            
            # 计算姿态评分
            pose_score = self._calculate_pose_score(keypoints)
            
            # 构建结果数据
            data = {
                'keypoints': keypoints,
                'pose_type': pose_type,
                'pose_score': pose_score,
                'keypoint_count': len(keypoints),
                'visible_keypoints': sum(1 for kp in keypoints if kp['confidence'] > 0.5)
            }
            
            result = AnalysisResult(
                session_id=context.session_id,
                analyzer_type=self._analyzer_type.value,
                mode=self._mode,
                timestamp=time.time(),
                data=data,
                confidence=pose_score,
                frame_index=context.frame_index
            )
            
            return result
            
        except Exception as e:
            logger.error(f"姿态分析失败: {e}")
            return None


class MockPoseNormalizer:
    """
    姿态归一化工具
    
    用于将关键点坐标归一化，便于比对
    """
    
    @staticmethod
    def normalize(keypoints: List[Dict]) -> List[Dict]:
        """
        归一化关键点坐标
        
        以左肩-右肩距离为基准进行归一化
        """
        if not keypoints or len(keypoints) < 17:
            return keypoints
        
        # 找到左肩和右肩
        left_shoulder = next((kp for kp in keypoints if kp['name'] == 'left_shoulder'), None)
        right_shoulder = next((kp for kp in keypoints if kp['name'] == 'right_shoulder'), None)
        
        if not left_shoulder or not right_shoulder:
            return keypoints
        
        # 计算肩宽
        shoulder_width = abs(right_shoulder['x'] - left_shoulder['x'])
        if shoulder_width < 1:
            shoulder_width = 100  # 默认值
        
        # 计算中心点
        center_x = (left_shoulder['x'] + right_shoulder['x']) / 2
        center_y = (left_shoulder['y'] + right_shoulder['y']) / 2
        
        # 归一化
        normalized = []
        for kp in keypoints:
            normalized.append({
                'id': kp['id'],
                'name': kp['name'],
                'x': (kp['x'] - center_x) / shoulder_width,
                'y': (kp['y'] - center_y) / shoulder_width,
                'confidence': kp['confidence']
            })
        
        return normalized
    
    @staticmethod
    def compute_similarity(pose1: List[Dict], pose2: List[Dict]) -> float:
        """
        计算两个姿态的相似度
        
        Args:
            pose1: 第一个姿态的关键点
            pose2: 第二个姿态的关键点
        
        Returns:
            相似度 (0-1)
        """
        if not pose1 or not pose2:
            return 0.0
        
        if len(pose1) != len(pose2):
            return 0.0
        
        # 计算欧氏距离的平均值
        total_distance = 0.0
        valid_count = 0
        
        for kp1, kp2 in zip(pose1, pose2):
            if kp1['confidence'] > 0.5 and kp2['confidence'] > 0.5:
                dx = kp1['x'] - kp2['x']
                dy = kp1['y'] - kp2['y']
                distance = (dx**2 + dy**2) ** 0.5
                total_distance += distance
                valid_count += 1
        
        if valid_count == 0:
            return 0.0
        
        avg_distance = total_distance / valid_count
        
        # 将距离转换为相似度（距离越小，相似度越高）
        # 使用高斯函数进行转换
        similarity = np.exp(-avg_distance * 2)
        
        return round(float(similarity), 3)

