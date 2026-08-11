"""
视觉分析模块

提供各种视觉分析器的 Mock 和 Real 实现
"""

from app.core.vision.pose_analyzer import (
    MockPoseAnalyzer,
    MockPoseNormalizer,
    COCO_KEYPOINTS
)

from app.core.vision.real_pose_analyzer import (
    RealPoseAnalyzer,
    RealPoseNormalizer,
    MEDIAPIPE_KEYPOINTS
)

from app.core.vision.face_analyzer import (
    MockFaceAnalyzer,
    EMOTIONS,
    ATTENTION_EMOTION_WEIGHTS
)

from app.core.vision.attention_analyzer import (
    MockAttentionAnalyzer
)

__all__ = [
    # Pose - Mock
    'MockPoseAnalyzer',
    'MockPoseNormalizer',
    'COCO_KEYPOINTS',
    
    # Pose - Real
    'RealPoseAnalyzer',
    'RealPoseNormalizer',
    'MEDIAPIPE_KEYPOINTS',
    
    # Face
    'MockFaceAnalyzer',
    'EMOTIONS',
    'ATTENTION_EMOTION_WEIGHTS',
    
    # Attention
    'MockAttentionAnalyzer',
]
