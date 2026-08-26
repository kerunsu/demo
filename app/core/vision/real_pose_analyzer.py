"""
真实姿态分析器
使用 MediaPipe PoseLandmarker 进行姿态检测
"""
import os
import time
from pathlib import Path
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

logger = setup_logger('real_pose_analyzer')


# MediaPipe 33关键点定义
MEDIAPIPE_KEYPOINTS = [
    'nose',                     # 0
    'left_eye_inner',           # 1
    'left_eye',                 # 2
    'left_eye_outer',           # 3
    'right_eye_inner',          # 4
    'right_eye',                # 5
    'right_eye_outer',          # 6
    'left_ear',                 # 7
    'right_ear',                # 8
    'mouth_left',               # 9
    'mouth_right',              # 10
    'left_shoulder',            # 11
    'right_shoulder',           # 12
    'left_elbow',               # 13
    'right_elbow',              # 14
    'left_wrist',               # 15
    'right_wrist',              # 16
    'left_pinky',               # 17
    'right_pinky',              # 18
    'left_index',               # 19
    'right_index',              # 20
    'left_thumb',               # 21
    'right_thumb',              # 22
    'left_hip',                 # 23
    'right_hip',                # 24
    'left_knee',                # 25
    'right_knee',               # 26
    'left_ankle',               # 27
    'right_ankle',              # 28
    'left_heel',                # 29
    'right_heel',               # 30
    'left_foot_index',          # 31
    'right_foot_index'          # 32
]


class RealPoseAnalyzer(BaseVisionAnalyzer):
    """
    真实姿态分析器
    
    使用 MediaPipe PoseLandmarker 检测33个关键点
    """
    
    # 默认模型路径
    DEFAULT_MODEL_PATH = "models/pose_landmarker_lite.task"
    
    def __init__(
        self,
        mode: AnalysisMode = AnalysisMode.REALTIME,
        config: Optional[Dict[str, Any]] = None
    ):
        """
        初始化真实姿态分析器
        
        Args:
            mode: 分析模式
            config: 配置参数，支持:
                - model_path: 模型路径
                - min_detection_confidence: 最小检测置信度
                - num_poses: 最大检测人数
        """
        super().__init__(AnalyzerType.POSE, mode, config)
        
        self._config = config or {}
        configured_model_path = Path(
            str(self._config.get('model_path', self.DEFAULT_MODEL_PATH))
        ).expanduser()
        if not configured_model_path.is_absolute():
            configured_model_path = Path(__file__).resolve().parents[3] / configured_model_path
        self._model_path = str(configured_model_path.resolve())
        self._min_detection_confidence = self._config.get('min_detection_confidence', 0.5)
        self._num_poses = self._config.get('num_poses', 1)
        
        # MediaPipe 组件
        self._pose_landmarker = None
        self._mp_image_class = None
        self._mp_image_format = None
        
        
        logger.info("真实姿态分析器已创建")
    
    def initialize(self) -> bool:
        """
        初始化 MediaPipe PoseLandmarker
        
        Returns:
            是否成功初始化
        """
        if self._is_initialized:
            return True
        
        try:
            import mediapipe as mp
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision
            
            # 检查模型文件
            if not os.path.exists(self._model_path):
                logger.error(f"模型文件不存在: {self._model_path}")
                # 尝试下载模型
                if not self._download_model():
                    return False
            
            # MediaPipe's native Windows loader can interpret a drive-letter
            # absolute path as relative to site-packages. Loading the reviewed
            # local model as bytes avoids that platform-specific path rewrite.
            with open(self._model_path, 'rb') as model_file:
                model_asset_buffer = model_file.read()
            base_options = python.BaseOptions(model_asset_buffer=model_asset_buffer)
            options = vision.PoseLandmarkerOptions(
                base_options=base_options,
                output_segmentation_masks=False,
                num_poses=self._num_poses
            )
            
            self._pose_landmarker = vision.PoseLandmarker.create_from_options(options)
            self._mp_image_class = mp.Image
            self._mp_image_format = mp.ImageFormat
            
            self._is_initialized = True
            logger.info(f"真实姿态分析器初始化成功，模型: {self._model_path}")
            return True
            
        except Exception as e:
            logger.error(f"真实姿态分析器初始化失败: {e}")
            return False
    
    def _download_model(self) -> bool:
        """下载模型文件"""
        import urllib.request
        
        model_url = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"
        
        try:
            os.makedirs(os.path.dirname(self._model_path), exist_ok=True)
            logger.info(f"下载模型: {model_url}")
            urllib.request.urlretrieve(model_url, self._model_path)
            logger.info(f"模型下载成功: {self._model_path}")
            return True
        except Exception as e:
            logger.error(f"模型下载失败: {e}")
            return False
    
    def detect_from_image(self, image: np.ndarray) -> Optional[List[Dict[str, Any]]]:
        """
        从图片检测姿态（用于目标设置）
        
        Args:
            image: BGR 格式的图片
        
        Returns:
            关键点列表，每个关键点包含 {x, y, z, visibility, name}
        """
        if not self.is_ready:
            if not self.initialize():
                return None
        
        try:
            import cv2
            
            # 转换为 RGB
            if len(image.shape) == 3 and image.shape[2] == 3:
                image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            else:
                image_rgb = image
            
            # 创建 MediaPipe Image
            mp_image = self._mp_image_class(
                image_format=self._mp_image_format.SRGB,
                data=image_rgb
            )
            
            # 检测
            results = self._pose_landmarker.detect(mp_image)
            
            if not results.pose_landmarks or len(results.pose_landmarks) == 0:
                logger.warning("图片中未检测到姿态")
                return None
            
            # 转换第一个人的姿态
            landmarks = results.pose_landmarks[0]
            keypoints = self._convert_landmarks_to_keypoints(landmarks)
            
            return keypoints
            
        except Exception as e:
            logger.error(f"图片姿态检测失败: {e}")
            return None
    
    def _convert_landmarks_to_keypoints(
        self, 
        landmarks,
        image_width: int = 1,
        image_height: int = 1
    ) -> List[Dict[str, Any]]:
        """
        将 MediaPipe landmarks 转换为关键点格式
        
        Args:
            landmarks: MediaPipe 检测结果
            image_width: 图片宽度（用于像素坐标转换）
            image_height: 图片高度
        
        Returns:
            关键点列表
        """
        keypoints = []
        
        for i, lm in enumerate(landmarks):
            name = MEDIAPIPE_KEYPOINTS[i] if i < len(MEDIAPIPE_KEYPOINTS) else f"point_{i}"
            
            keypoints.append({
                'id': i,
                'name': name,
                'x': float(lm.x),  # 归一化坐标 [0, 1]
                'y': float(lm.y),
                'z': float(lm.z),
                'visibility': float(lm.visibility),
                # 像素坐标（如果需要）
                'pixel_x': float(lm.x * image_width),
                'pixel_y': float(lm.y * image_height)
            })
        
        return keypoints
    
    def analyze_frame(
        self,
        frame: np.ndarray,
        context: AnalysisContext
    ) -> Optional[AnalysisResult]:
        """
        分析单帧视频的姿态
        
        Args:
            frame: 视频帧（BGR 格式 numpy 数组）
            context: 分析上下文
        
        Returns:
            姿态分析结果
        """
        if not self.is_ready:
            if not self.initialize():
                return None
        
        try:
            import cv2
            
            height, width = frame.shape[:2]
            
            # 转换为 RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # 创建 MediaPipe Image
            mp_image = self._mp_image_class(
                image_format=self._mp_image_format.SRGB,
                data=frame_rgb
            )
            
            # 检测
            start_time = time.time()
            results = self._pose_landmarker.detect(mp_image)
            detection_time = (time.time() - start_time) * 1000
            
            # 检查结果
            if not results.pose_landmarks or len(results.pose_landmarks) == 0:
                return None
            
            # 转换关键点
            landmarks = results.pose_landmarks[0]
            keypoints = self._convert_landmarks_to_keypoints(landmarks, width, height)
            
            # 计算姿态评分（基于关键点可见性）
            pose_score = self._calculate_pose_score(keypoints)
            
            # 估计姿态类型
            pose_type = self._estimate_pose_type(keypoints)
            
            # 构建结果数据
            data = {
                'keypoints': keypoints,
                'pose_type': pose_type,
                'pose_score': pose_score,
                'keypoint_count': len(keypoints),
                'visible_keypoints': sum(1 for kp in keypoints if kp['visibility'] > 0.5),
                'detection_time_ms': round(detection_time, 1)
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
    
    def _calculate_pose_score(self, keypoints: List[Dict]) -> float:
        """
        计算姿态评分
        
        基于关键点的可见性
        """
        if not keypoints:
            return 0.0
        
        total_visibility = sum(kp.get('visibility', 0) for kp in keypoints)
        return round(total_visibility / len(keypoints), 3)
    
    def _estimate_pose_type(self, keypoints: List[Dict]) -> str:
        """
        估计姿态类型
        
        基于关键点位置关系判断
        """
        if len(keypoints) < 33:
            return "unknown"
        
        try:
            # 获取关键点
            left_hip = keypoints[23]
            right_hip = keypoints[24]
            left_knee = keypoints[25]
            right_knee = keypoints[26]
            left_shoulder = keypoints[11]
            right_shoulder = keypoints[12]
            
            # 检查可见性
            hip_visible = left_hip['visibility'] > 0.3 and right_hip['visibility'] > 0.3
            knee_visible = left_knee['visibility'] > 0.3 and right_knee['visibility'] > 0.3
            
            if not hip_visible:
                return "partial"
            
            # 计算躯干和腿的相对位置
            hip_y = (left_hip['y'] + right_hip['y']) / 2
            shoulder_y = (left_shoulder['y'] + right_shoulder['y']) / 2
            
            if knee_visible:
                knee_y = (left_knee['y'] + right_knee['y']) / 2
                
                # 膝盖比髋部低很多 -> 站立
                if knee_y > hip_y + 0.15:
                    return "standing"
                # 膝盖和髋部差不多高 -> 坐着
                elif abs(knee_y - hip_y) < 0.1:
                    return "sitting"
            
            # 髋部和肩部差不多高 -> 躺着
            if abs(hip_y - shoulder_y) < 0.1:
                return "lying"
            
            return "other"
            
        except Exception:
            return "unknown"
    
    def cleanup(self) -> None:
        """清理资源"""
        if self._pose_landmarker:
            try:
                self._pose_landmarker.close()
            except Exception:
                pass
            self._pose_landmarker = None
        
        self._is_initialized = False
        logger.info("真实姿态分析器资源已清理")


class RealPoseNormalizer:
    """
    真实姿态归一化工具
    
    移植自前端 pose_similarity.js 的归一化算法
    """

    # 模仿课程当前以及预期扩展都以可观察的关节动作为主。旧实现把脸部
    # 轮廓等 33 个点等权平均，手臂动作只占很小比例，导致“举双手”和
    # “双手托脸”也会得到很高的相似度。这里保留旧 normalize API 供历史
    # 调用，同时为动作比对提供独立的、可见性加权的特征。
    ACTION_KEYPOINT_WEIGHTS = {
        11: 0.5,  # left shoulder
        12: 0.5,  # right shoulder
        13: 2.0,  # left elbow
        14: 2.0,  # right elbow
        15: 3.0,  # left wrist
        16: 3.0,  # right wrist
        23: 0.75,  # left hip (full-body targets)
        24: 0.75,  # right hip
        25: 2.0,  # left knee
        26: 2.0,  # right knee
        27: 3.0,  # left ankle
        28: 3.0,  # right ankle
    }
    MIRROR_PAIRS = {
        11: 12,
        12: 11,
        13: 14,
        14: 13,
        15: 16,
        16: 15,
        23: 24,
        24: 23,
        25: 26,
        26: 25,
        27: 28,
        28: 27,
    }
    
    @staticmethod
    def normalize(keypoints: List[Dict]) -> List[List[float]]:
        """
        姿态归一化
        
        以髋部中点为原点，以躯干长度为尺度
        
        Args:
            keypoints: 33个关键点列表
        
        Returns:
            归一化后的坐标列表 [[x, y], ...]
        """
        if not keypoints or len(keypoints) < 25:
            return []
        
        try:
            # 髋部中点 (点23, 24)
            left_hip = keypoints[23]
            right_hip = keypoints[24]
            hip_x = (left_hip['x'] + right_hip['x']) / 2
            hip_y = (left_hip['y'] + right_hip['y']) / 2
            
            # 肩部中点 (点11, 12)
            left_shoulder = keypoints[11]
            right_shoulder = keypoints[12]
            shoulder_x = (left_shoulder['x'] + right_shoulder['x']) / 2
            shoulder_y = (left_shoulder['y'] + right_shoulder['y']) / 2
            
            # 躯干长度
            dx = hip_x - shoulder_x
            dy = hip_y - shoulder_y
            torso = np.sqrt(dx*dx + dy*dy)
            if torso < 1e-6:
                torso = 1e-6
            
            # 归一化
            normalized = []
            for kp in keypoints:
                normalized.append([
                    (kp['x'] - hip_x) / torso,
                    (kp['y'] - hip_y) / torso
                ])
            
            return normalized
            
        except Exception as e:
            logger.error(f"姿态归一化失败: {e}")
            return []
    
    @staticmethod
    def compute_similarity(norm_a: List[List[float]], norm_b: List[List[float]]) -> float:
        """
        计算两个归一化姿态的相似度
        
        移植自前端 pose_similarity.js 的算法
        
        Args:
            norm_a: 第一个归一化姿态
            norm_b: 第二个归一化姿态
        
        Returns:
            相似度 (0-1)
        """
        if not norm_a or not norm_b:
            return 0.0
        
        n = min(len(norm_a), len(norm_b))
        if n == 0:
            return 0.0
        
        # 计算平均点距
        total_dist = 0.0
        for i in range(n):
            dx = norm_a[i][0] - norm_b[i][0]
            dy = norm_a[i][1] - norm_b[i][1]
            total_dist += np.sqrt(dx*dx + dy*dy)
        
        avg_dist = total_dist / n
        
        # 高斯映射到 [0, 1]
        sigma = 0.6  # 与前端一致
        similarity = np.exp(-(avg_dist ** 2) / (2 * sigma ** 2))
        
        return float(similarity)

    @staticmethod
    def normalize_action(
        keypoints: List[Dict[str, Any]],
    ) -> Dict[int, Dict[str, float]]:
        """Build translation/scale invariant action-joint features.

        Shoulder width is a more stable scale for the current upper-body mimic
        cards than hip-to-shoulder length (hips are often outside the child
        camera). Visibility is retained so hallucinated/off-screen joints do
        not silently contribute to a successful match.
        """
        if not keypoints or len(keypoints) <= 16:
            return {}
        try:
            left_shoulder = keypoints[11]
            right_shoulder = keypoints[12]
            origin_x = (float(left_shoulder['x']) + float(right_shoulder['x'])) / 2.0
            origin_y = (float(left_shoulder['y']) + float(right_shoulder['y'])) / 2.0
            shoulder_width = float(np.hypot(
                float(left_shoulder['x']) - float(right_shoulder['x']),
                float(left_shoulder['y']) - float(right_shoulder['y']),
            ))
            if shoulder_width < 1e-4:
                return {}

            normalized: Dict[int, Dict[str, float]] = {}
            for index in RealPoseNormalizer.ACTION_KEYPOINT_WEIGHTS:
                if index >= len(keypoints):
                    continue
                point = keypoints[index]
                normalized[index] = {
                    'x': (float(point.get('x', 0.0)) - origin_x) / shoulder_width,
                    'y': (float(point.get('y', 0.0)) - origin_y) / shoulder_width,
                    'visibility': float(point.get('visibility', 0.0) or 0.0),
                }
            return normalized
        except (KeyError, TypeError, ValueError) as exc:
            logger.debug("动作特征归一化失败: %s", exc)
            return {}

    @staticmethod
    def compute_action_similarity_details(
        live: Dict[int, Dict[str, float]],
        target: Dict[int, Dict[str, float]],
        *,
        min_visibility: float = 0.35,
        sigma: float = 0.55,
        allow_mirror: bool = True,
    ) -> Dict[str, Any]:
        """Compare action joints and return auditable match diagnostics."""
        if not live or not target:
            return {
                'score': 0.0,
                'distance': None,
                'coverage': 0.0,
                'mirrored': False,
                'keypoints_used': [],
            }

        weights = RealPoseNormalizer.ACTION_KEYPOINT_WEIGHTS
        target_indices = [
            index
            for index, point in target.items()
            if index in weights
            and float(point.get('visibility', 0.0)) >= min_visibility
        ]
        target_weight = sum(weights[index] for index in target_indices)
        if target_weight <= 0:
            return {
                'score': 0.0,
                'distance': None,
                'coverage': 0.0,
                'mirrored': False,
                'keypoints_used': [],
            }

        def compare(mirrored: bool) -> Dict[str, Any]:
            weighted_distance = 0.0
            used_weight = 0.0
            used_indices: List[int] = []
            for target_index in target_indices:
                live_index = (
                    RealPoseNormalizer.MIRROR_PAIRS.get(target_index, target_index)
                    if mirrored
                    else target_index
                )
                live_point = live.get(live_index)
                target_point = target.get(target_index)
                if not live_point or not target_point:
                    continue
                if float(live_point.get('visibility', 0.0)) < min_visibility:
                    continue
                live_x = float(live_point.get('x', 0.0))
                if mirrored:
                    live_x = -live_x
                distance = float(np.hypot(
                    live_x - float(target_point.get('x', 0.0)),
                    float(live_point.get('y', 0.0))
                    - float(target_point.get('y', 0.0)),
                ))
                weight = weights[target_index]
                weighted_distance += weight * distance
                used_weight += weight
                used_indices.append(target_index)

            coverage = used_weight / target_weight if target_weight else 0.0
            if used_weight <= 0 or coverage < 0.65:
                score = 0.0
                avg_distance = None
            else:
                avg_distance = weighted_distance / used_weight
                base_score = float(np.exp(
                    -(avg_distance ** 2) / (2.0 * max(sigma, 1e-3) ** 2)
                ))
                # Incomplete visibility may never look better than a fully
                # observed pose. Full score is reached from 85% weighted
                # coverage upward to tolerate one briefly obscured elbow.
                score = base_score * min(1.0, coverage / 0.85)
            return {
                'score': max(0.0, min(1.0, float(score))),
                'distance': avg_distance,
                'coverage': float(coverage),
                'mirrored': mirrored,
                'keypoints_used': used_indices,
            }

        candidates = [compare(False)]
        if allow_mirror:
            candidates.append(compare(True))
        return max(candidates, key=lambda item: float(item.get('score') or 0.0))

    @staticmethod
    def compute_action_similarity(
        live: Dict[int, Dict[str, float]],
        target: Dict[int, Dict[str, float]],
        **kwargs: Any,
    ) -> float:
        """Compatibility wrapper returning only the 0..1 action score."""
        return float(
            RealPoseNormalizer.compute_action_similarity_details(
                live,
                target,
                **kwargs,
            ).get('score')
            or 0.0
        )

