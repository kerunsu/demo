"""
表情/头部姿态分析器（Mock）
返回模拟的表情和头部姿态数据，用于验证流程
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

logger = setup_logger('face_analyzer')


# 7类基本情绪
EMOTIONS = [
    'neutral',      # 中性
    'happy',        # 开心
    'sad',          # 悲伤
    'angry',        # 愤怒
    'fearful',      # 恐惧
    'disgusted',    # 厌恶
    'surprised'     # 惊讶
]

# 注意力相关的表情权重
ATTENTION_EMOTION_WEIGHTS = {
    'neutral': 0.6,
    'happy': 0.8,
    'sad': 0.3,
    'angry': 0.4,
    'fearful': 0.2,
    'disgusted': 0.3,
    'surprised': 0.7
}


class MockFaceAnalyzer(BaseVisionAnalyzer):
    """
    Mock表情/头部姿态分析器
    
    返回模拟的表情识别和头部姿态数据
    用于在没有真实模型时验证整个分析流程
    """
    
    def __init__(
        self,
        mode: AnalysisMode = AnalysisMode.REALTIME,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        初始化Mock表情/头部分析器
        
        Args:
            mode: 分析模式
            config: 配置参数
        """
        super().__init__(AnalyzerType.FACE, mode, config)
        
        # Mock配置
        self._dominant_emotion = config.get('dominant_emotion', 'neutral') if config else 'neutral'
        self._noise_level = config.get('noise_level', 0.1) if config else 0.1
        
        logger.info("Mock表情/头部分析器已创建")
    
    def _generate_emotion_scores(self) -> Dict[str, float]:
        """
        生成模拟的情绪分数
        
        Returns:
            各情绪的分数字典
        """
        scores = {}
        remaining = 1.0
        
        # 主要情绪获得较高分数
        dominant_score = random.uniform(0.5, 0.8)
        scores[self._dominant_emotion] = round(dominant_score, 3)
        remaining -= dominant_score
        
        # 其他情绪分配剩余分数
        other_emotions = [e for e in EMOTIONS if e != self._dominant_emotion]
        for i, emotion in enumerate(other_emotions):
            if i == len(other_emotions) - 1:
                # 最后一个获得剩余全部
                scores[emotion] = round(max(0, remaining), 3)
            else:
                # 随机分配
                score = random.uniform(0, remaining / 2)
                scores[emotion] = round(score, 3)
                remaining -= score
        
        return scores
    
    def _generate_head_pose(self) -> Dict[str, float]:
        """
        生成模拟的头部姿态（欧拉角）
        
        Returns:
            头部姿态字典 (yaw, pitch, roll)
        """
        # 生成小范围的头部偏转（面向摄像头）
        return {
            'yaw': round(random.uniform(-15, 15), 2),      # 左右摇头 (-90 ~ 90)
            'pitch': round(random.uniform(-10, 10), 2),    # 上下点头 (-90 ~ 90)
            'roll': round(random.uniform(-5, 5), 2)        # 左右倾斜 (-90 ~ 90)
        }
    
    def _calculate_attention_score(
        self,
        emotion_scores: Dict[str, float],
        head_pose: Dict[str, float]
    ) -> float:
        """
        根据表情和头部姿态计算注意力评分
        
        Args:
            emotion_scores: 情绪分数
            head_pose: 头部姿态
        
        Returns:
            注意力评分 (0-1)
        """
        # 基于情绪的注意力
        emotion_attention = 0.0
        for emotion, score in emotion_scores.items():
            weight = ATTENTION_EMOTION_WEIGHTS.get(emotion, 0.5)
            emotion_attention += score * weight
        
        # 基于头部姿态的注意力（头部偏转越小，注意力越高）
        yaw_factor = 1.0 - min(abs(head_pose['yaw']) / 45, 1.0)
        pitch_factor = 1.0 - min(abs(head_pose['pitch']) / 30, 1.0)
        head_attention = (yaw_factor + pitch_factor) / 2
        
        # 综合评分
        attention = 0.6 * emotion_attention + 0.4 * head_attention
        
        return round(attention, 3)
    
    def _detect_face(self, frame: np.ndarray) -> Optional[Dict[str, Any]]:
        """
        模拟人脸检测
        
        Returns:
            人脸边界框，如果未检测到返回None
        """
        # Mock: 大多数情况检测到人脸
        if random.random() < 0.95:
            height, width = frame.shape[:2]
            # 生成模拟的人脸边界框（居中偏上）
            face_width = int(width * random.uniform(0.2, 0.4))
            face_height = int(face_width * 1.2)
            x = int((width - face_width) / 2 + random.uniform(-50, 50))
            y = int(height * 0.1 + random.uniform(-20, 20))
            
            return {
                'x': max(0, x),
                'y': max(0, y),
                'width': face_width,
                'height': face_height,
                'confidence': round(random.uniform(0.85, 0.99), 3)
            }
        return None
    
    def analyze_frame(
        self,
        frame: np.ndarray,
        context: AnalysisContext
    ) -> Optional[AnalysisResult]:
        """
        分析单帧视频的表情和头部姿态
        
        Args:
            frame: 视频帧（numpy数组）
            context: 分析上下文
        
        Returns:
            分析结果
        """
        if not self.is_ready:
            if not self.initialize():
                return None
        
        try:
            # 检测人脸
            face_bbox = self._detect_face(frame)
            
            if face_bbox is None:
                # 未检测到人脸
                data = {
                    'face_detected': False,
                    'emotion': None,
                    'emotion_scores': {},
                    'head_pose': None,
                    'attention_score': 0.0
                }
            else:
                # 生成模拟数据
                emotion_scores = self._generate_emotion_scores()
                head_pose = self._generate_head_pose()
                attention_score = self._calculate_attention_score(emotion_scores, head_pose)
                
                # 获取主要情绪
                dominant_emotion = max(emotion_scores, key=emotion_scores.get)
                
                data = {
                    'face_detected': True,
                    'face_bbox': face_bbox,
                    'emotion': dominant_emotion,
                    'emotion_scores': emotion_scores,
                    'emotion_confidence': emotion_scores[dominant_emotion],
                    'head_pose': head_pose,
                    'attention_score': attention_score
                }
            
            result = AnalysisResult(
                session_id=context.session_id,
                analyzer_type=self._analyzer_type.value,
                mode=self._mode,
                timestamp=time.time(),
                data=data,
                confidence=face_bbox['confidence'] if face_bbox else 0.0,
                frame_index=context.frame_index
            )
            
            return result
            
        except Exception as e:
            logger.error(f"表情/头部分析失败: {e}")
            return None
    
    def set_dominant_emotion(self, emotion: str) -> None:
        """设置主要情绪（用于测试）"""
        if emotion in EMOTIONS:
            self._dominant_emotion = emotion

