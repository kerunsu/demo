"""
真实注意力分析器 (Attention Analyzer) 
基于 MediaPipe Face Mesh 计算头部姿态 + 视线 + 情绪
"""
import time
import cv2
import numpy as np
import math
from typing import Optional, Dict, Any, List

# 确保导入了正确的类型
from app.core.models import (
    AnalysisMode, 
    AnalyzerType, 
    AnalysisResult, 
    AnalysisContext,
    AnalyzerStatus
)
from app.utils.logger import setup_logger

# 尝试导入基类
try:
    from app.core.base_analyzer import BaseVisionAnalyzer
    ParentClass = BaseVisionAnalyzer
except ImportError:
    # 本地调试时的临时基类 (防止 IDE 报错)
    class ParentClass:
        def __init__(self, analyzer_type, mode, config):
            self._analyzer_type = analyzer_type
            self._mode = mode
            self._config = config
            self._is_initialized = False
            # 模拟基类日志
            print(f"基类初始化: {analyzer_type}")

logger = setup_logger('real_attention_analyzer')

class RealAttentionAnalyzer(ParentClass):
    def __init__(self, mode: AnalysisMode = AnalysisMode.REALTIME, config: Optional[Dict[str, Any]] = None):
        # ====================================================
        # [核心修复] 直接使用 AnalyzerType.ATTENTION
        # 前提：请确保 app/core/models.py 中已添加 ATTENTION = "attention"
        # ====================================================
        super().__init__(AnalyzerType.ATTENTION, mode, config)
            
        self._config = config or {}
        self._face_mesh = None
        self.POSE_THRESHOLD = 20.0
        # 姿态死区（度）：正视摄像头时 solvePnP 仍常有小幅非零角；
        # 机器人机位常略偏侧/偏低，死区略宽于桌面摄像头。
        self.POSE_DEADZONE_DEG = float(self._config.get("pose_deadzone_deg", 15.0))
        self.POSE_ZERO_AT_DEG = float(self._config.get("pose_zero_at_deg", 55.0))
        self.GAZE_DEADZONE = float(self._config.get("gaze_deadzone", 0.06))
        # 可选机位校准：若摄像头固定偏侧，可设 yaw_offset≈实测中位 yaw
        self.PITCH_OFFSET = float(self._config.get("pitch_offset", 0.0))
        self.YAW_OFFSET = float(self._config.get("yaw_offset", 0.0))
        
        logger.info("真实注意力分析器 (完整版) 已创建")

    def initialize(self) -> bool:
        if self._is_initialized: return True
        try:
            from mediapipe import solutions
            
            # 使用 mediapipe.solutions.face_mesh
            self.mp_face_mesh = solutions.face_mesh
            self._face_mesh = self.mp_face_mesh.FaceMesh(
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
                max_num_faces=1,
                refine_landmarks=True
            )
            self._is_initialized = True
            self._last_error = None
            self._status = AnalyzerStatus.READY
            logger.info("MediaPipe Face Mesh 初始化成功")
            return True
        except Exception as e:
            self._last_error = str(e)
            self._status = AnalyzerStatus.ERROR
            logger.error(f"初始化失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    # ... (后续算法代码保持不变，直接复制之前的即可) ...
    # 为了方便，我把后面的核心算法部分再次完整贴在下面，您可以直接全选覆盖
    
    # ==========================================
    # 核心算法 1: 头部姿态 (Head Pose)
    # ==========================================
    def _get_head_pose(self, shape, landmarks):
        h, w, _ = shape
        model_points = np.array([
            (0.0, 0.0, 0.0),             # 鼻尖
            (0.0, -330.0, -65.0),        # 下巴
            (-225.0, 170.0, -135.0),     # 左眼角
            (225.0, 170.0, -135.0),      # 右眼角
            (-150.0, -150.0, -125.0),    # 左嘴角
            (150.0, -150.0, -125.0)      # 右嘴角
        ], dtype=np.float64)

        # 与 OpenCV 经典 3D 模型一致：图像左侧点 → 模型负 X
        # MediaPipe：33=右眼外眦(图像左)，263=左眼外眦(图像右)；
        # 61=右嘴角(图像左)，291=左嘴角(图像右)。
        # 旧版误用 [263,33,291,61]，左右对调 → yaw 系统性偏约 -20°~-30°。
        idx_list = [1, 152, 33, 263, 61, 291]
        image_points = []
        for idx in idx_list:
            lm = landmarks.landmark[idx]
            image_points.append([lm.x * w, lm.y * h])
        image_points = np.array(image_points, dtype=np.float64)

        focal_length = w
        center = (w / 2, h / 2)
        camera_matrix = np.array([
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1]
        ], dtype=np.float64)
        dist_coeffs = np.zeros((4, 1))

        success, rotation_vector, translation_vector = cv2.solvePnP(
            model_points, image_points, camera_matrix, dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        
        nose_end_point2D, _ = cv2.projectPoints(
            np.array([(0.0, 0.0, 500.0)]), rotation_vector, translation_vector, camera_matrix, dist_coeffs
        )
        
        rmat, _ = cv2.Rodrigues(rotation_vector)
        proj_matrix = np.hstack((rmat, translation_vector))
        _, _, _, _, _, _, euler_angles = cv2.decomposeProjectionMatrix(proj_matrix)
        pitch, yaw, roll = [float(item[0]) for item in euler_angles]
        pitch, yaw, roll = self._normalize_euler(pitch, yaw, roll)

        return (pitch, yaw, roll), nose_end_point2D[0][0], image_points[0]

    @staticmethod
    def _normalize_euler(pitch: float, yaw: float, roll: float):
        """把 decomposeProjectionMatrix 的欧拉角收束到更可解释的朝向范围。"""
        def _wrap180(a: float) -> float:
            a = (a + 180.0) % 360.0 - 180.0
            return a

        pitch = _wrap180(pitch)
        yaw = _wrap180(yaw)
        roll = _wrap180(roll)
        # pitch 偶发落在 ±180 附近，折到俯仰常用区间
        if pitch > 90.0:
            pitch = 180.0 - pitch
        elif pitch < -90.0:
            pitch = -180.0 - pitch
        return pitch, yaw, roll

    # ==========================================
    # 核心算法 2: 视线落点 (Gaze Estimation)
    # ==========================================
    def _get_iris_analysis(self, shape, landmarks):
        h, w, _ = shape

        def iris_x_ratio(left_idx, right_idx, iris_idx):
            """图像坐标系下虹膜水平比例：0=靠左眼角，1=靠右眼角，正视约 0.5。"""
            lx = landmarks.landmark[left_idx].x
            rx = landmarks.landmark[right_idx].x
            ix = landmarks.landmark[iris_idx].x
            ratio = (ix - lx) / ((rx - lx) + 1e-6)
            pixel_pos = (int(landmarks.landmark[iris_idx].x * w),
                         int(landmarks.landmark[iris_idx].y * h))
            return float(ratio), pixel_pos

        # 右眼（图像左侧）：外眦 33 → 内眦 133，虹膜 468
        # 左眼（图像右侧）：内眦 362 → 外眦 263，虹膜 473
        r_right, pos_right = iris_x_ratio(33, 133, 468)
        r_left, pos_left = iris_x_ratio(362, 263, 473)

        avg_ratio_x = (r_left + r_right) / 2.0

        gaze_dir = "CENTER"
        if avg_ratio_x < 0.42:
            gaze_dir = "RIGHT"  # 虹膜偏图像左 → 看向人物右侧
        elif avg_ratio_x > 0.58:
            gaze_dir = "LEFT"

        return gaze_dir, avg_ratio_x, pos_left, pos_right

    # ==========================================
    # 核心算法 3: 几何情绪 (Geometric Emotion)
    # ==========================================
    def _get_emotion_analysis(self, landmarks):
        def dist(idx1, idx2):
            p1 = np.array([landmarks.landmark[idx1].x, landmarks.landmark[idx1].y])
            p2 = np.array([landmarks.landmark[idx2].x, landmarks.landmark[idx2].y])
            return np.linalg.norm(p1 - p2)

        mar = dist(13, 14) / (dist(61, 291) + 1e-6)

        mouth_y = (landmarks.landmark[13].y + landmarks.landmark[14].y) / 2
        corner_y = (landmarks.landmark[61].y + landmarks.landmark[291].y) / 2
        smile_ratio = mouth_y - corner_y

        # 旧阈值 smile_ratio < -0.01 极易把中性脸打成 Sad
        emotion = "Neutral"
        if mar > 0.5:
            emotion = "Surprise"
        elif smile_ratio > 0.015:
            emotion = "Happy"
        elif smile_ratio < -0.025:
            emotion = "Sad"

        return emotion, mar, smile_ratio

    def _score_pose_component(self, pitch: float, yaw: float) -> float:
        """姿态分 0–40：死区内满分，超出后线性降到 0。"""
        pose_dev = math.sqrt(pitch * pitch + yaw * yaw)
        dead = self.POSE_DEADZONE_DEG
        zero_at = max(self.POSE_ZERO_AT_DEG, dead + 1.0)
        if pose_dev <= dead:
            return 40.0
        if pose_dev >= zero_at:
            return 0.0
        return 40.0 * (1.0 - (pose_dev - dead) / (zero_at - dead))

    def _score_gaze_component(self, gaze_ratio: float) -> float:
        """视线分 0–40：虹膜水平比接近 0.5 满分。"""
        gaze_dev = abs(float(gaze_ratio) - 0.5)
        dead = self.GAZE_DEADZONE
        if gaze_dev <= dead:
            return 40.0
        # 偏差到 0.22 时归零（约 ratio 0.28 / 0.72）
        span = 0.22 - dead
        if gaze_dev >= 0.22:
            return 0.0
        return 40.0 * (1.0 - (gaze_dev - dead) / span)

    @staticmethod
    def _score_emotion_component(emotion: str) -> float:
        """情绪对注意力仅作轻量加成，避免假 Sad 把总分压到 60 以下。"""
        if emotion in ("Happy", "Surprise"):
            return 20.0
        if emotion == "Sad":
            return 12.0
        return 15.0

    def analyze_frame(self, frame: np.ndarray, context: AnalysisContext) -> Optional[AnalysisResult]:
        if not self.is_ready:
            if not self.initialize(): return None
        
        try:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self._face_mesh.process(frame_rgb)
            
            data = {}
            total_score = 0.0
            
            if results.multi_face_landmarks:
                landmarks = results.multi_face_landmarks[0]
                
                (pitch, yaw, roll), nose_end, nose_start = self._get_head_pose(frame.shape, landmarks)
                pitch = float(pitch) - self.PITCH_OFFSET
                yaw = float(yaw) - self.YAW_OFFSET
                gaze_dir, gaze_ratio, iris_l, iris_r = self._get_iris_analysis(frame.shape, landmarks)
                emotion, mar, smile = self._get_emotion_analysis(landmarks)

                score_pose = self._score_pose_component(pitch, yaw)
                score_gaze = self._score_gaze_component(gaze_ratio)
                score_emotion = self._score_emotion_component(emotion)
                total_score = min(score_pose + score_gaze + score_emotion, 100.0)

                if total_score >= 70:
                    state = 'high'
                elif total_score >= 40:
                    state = 'medium'
                else:
                    state = 'low'

                from app.behavior.emotion_scoring import map_label_to_emotion_scores
                emotion_scores = map_label_to_emotion_scores(
                    emotion, smile_ratio=float(smile), mar=float(mar)
                )

                data = {
                    'has_face': True,
                    'face_present': True,
                    'score': float(total_score),
                    'state': state,
                    'trend': 'stable',
                    'data_quality': 'VALID',
                    'algorithm_version': 'server-attention-v2',
                    'head_pose': {
                        'pitch': round(float(pitch), 1),
                        'yaw': round(float(yaw), 1),
                        'roll': round(float(roll), 1),
                    },
                    'gaze': {'direction': gaze_dir, 'ratio': round(float(gaze_ratio), 2)},
                    'emotion': emotion,
                    'mar': float(mar),
                    'smile_ratio': float(smile),
                    'emotion_scores': emotion_scores,
                    'score_breakdown': {
                        'pose': int(round(score_pose)),
                        'gaze': int(round(score_gaze)),
                        'emotion': int(round(score_emotion)),
                    },
                    'visuals': {
                        'nose_tip': (int(nose_start[0]), int(nose_start[1])),
                        'nose_end': (int(nose_end[0]), int(nose_end[1])),
                        'iris_left': iris_l,
                        'iris_right': iris_r
                    }
                }
            else:
                data = {
                    'has_face': False,
                    'face_present': False,
                    'score': 0.0,
                    'state': 'low',
                    'trend': 'stable',
                    'data_quality': 'MISSING',
                }
                total_score = 0.0

            return AnalysisResult(
                session_id=context.session_id,
                analyzer_type="attention",
                mode=self._mode,
                timestamp=time.time(),
                data=data,
                confidence=total_score / 100.0,
                frame_index=context.frame_index
            )

        except Exception as e:
            logger.error(f"分析失败: {e}")
            return None

    def analyze_window(
        self,
        video_frames: List,
        audio_chunks: List = None,
        context: AnalysisContext = None,
    ) -> Optional[AnalysisResult]:
        """窗口注意力分析：采样帧后聚合。"""
        if not self._is_initialized:
            if not self.initialize():
                return None

        if context is None:
            context = AnalysisContext(session_id='unknown')

        if not video_frames:
            return AnalysisResult(
                session_id=context.session_id,
                analyzer_type='attention',
                mode=AnalysisMode.WINDOW,
                timestamp=time.time(),
                data={
                    'score': 0.0,
                    'state': 'low',
                    'trend': 'stable',
                    'data_quality': 'MISSING',
                    'face_present': False,
                    'frame_count': 0,
                },
                confidence=0.0,
            )

        # 教师端实时显示：只看「最近一小段」。
        # 双保险：① 时间窗 ② 末尾 N 帧（即使时间戳异常也能响应）。
        live_window = float(self._config.get('live_window_sec', 1.2))
        max_frames = int(self._config.get('live_max_frames', 10))
        now = time.time()
        recent_frames = []
        for item in video_frames:
            if isinstance(item, (tuple, list)) and len(item) >= 2:
                ts, frame = item[0], item[1]
                try:
                    age = now - float(ts)
                    # 未归一化的毫秒戳：age 会是约 -1e12
                    if abs(age) > 1e6:
                        age = now - float(ts) / 1000.0
                    # 仅允许极小时钟超前；过大负值直接丢弃
                    if -0.5 <= age <= live_window:
                        recent_frames.append(item)
                except (TypeError, ValueError):
                    recent_frames.append(item)
            else:
                recent_frames.append(item)
        if recent_frames:
            video_frames = recent_frames
        elif max_frames > 0:
            # 时间过滤异常时退回按到达顺序的末尾帧
            video_frames = video_frames[-max_frames:]
        if max_frames > 0 and len(video_frames) > max_frames:
            video_frames = video_frames[-max_frames:]

        scores = []
        face_flags = []
        emotion_accum = []
        last_data = {}
        # 近帧少时尽量每帧都算，避免 8 等分抽到大量旧态
        sample_step = 1 if len(video_frames) <= 12 else max(1, len(video_frames) // 8)

        for i in range(0, len(video_frames), sample_step):
            item = video_frames[i]
            frame = item[1] if isinstance(item, (tuple, list)) and len(item) >= 2 else item
            if frame is None:
                continue
            frame_ctx = AnalysisContext(
                session_id=context.session_id,
                course_type=getattr(context, 'course_type', None),
                frame_index=i,
                start_time=getattr(context, 'start_time', None),
            )
            result = self.analyze_frame(frame, frame_ctx)
            if not result:
                continue
            score = result.data.get('score')
            if score is None and result.confidence is not None:
                score = float(result.confidence) * 100.0
            if score is not None:
                scores.append(float(score))
            face_flags.append(bool(result.data.get('face_present') or result.data.get('has_face')))
            last_data = result.data
            emo = (result.data or {}).get('emotion_scores')
            if emo and not emo.get('unavailable'):
                emotion_accum.append(emo)

        if not scores:
            avg_score = 0.0
            quality = 'MISSING'
            state = 'low'
            face_present = False
        else:
            face_ratio = sum(1 for f in face_flags if f) / max(1, len(face_flags))
            # 近窗内多数无脸 → 视为离开/遮挡，立刻低分（勿被旧高分拖着）
            if face_ratio < 0.35:
                avg_score = 0.0
                face_present = False
                quality = 'MISSING'
                state = 'low'
            else:
                # 有脸时只用有脸帧计分，避免遮挡过渡期的 0 分把正视锁在 70
                face_scores = [s for s, f in zip(scores, face_flags) if f]
                avg_score = sum(face_scores) / len(face_scores) if face_scores else 0.0
                face_present = True
                quality = 'VALID'
                if avg_score >= 70:
                    state = 'high'
                elif avg_score >= 40:
                    state = 'medium'
                else:
                    state = 'low'

        trend = 'stable'
        if len(scores) >= 3:
            mid = len(scores) // 2
            first_avg = sum(scores[:mid]) / max(1, mid)
            second_avg = sum(scores[mid:]) / max(1, len(scores) - mid)
            if second_avg - first_avg > 5:
                trend = 'increasing'
            elif first_avg - second_avg > 5:
                trend = 'decreasing'

        emotion_scores = last_data.get('emotion_scores')
        if emotion_accum:
            p = sum(e.get('positiveScore', 0) for e in emotion_accum) / len(emotion_accum)
            f = sum(e.get('focusedScore', 0) for e in emotion_accum) / len(emotion_accum)
            r = sum(e.get('frustratedScore', 0) for e in emotion_accum) / len(emotion_accum)
            tot = p + f + r
            if tot > 0:
                p, f, r = p / tot, f / tot, r / tot
            emotion_scores = {
                'positiveScore': round(p, 3),
                'focusedScore': round(f, 3),
                'frustratedScore': round(r, 3),
                'confidence': round(
                    sum(e.get('confidence', 0) for e in emotion_accum) / len(emotion_accum), 3
                ),
                'degraded': False,
                'algorithmVersion': 'server-emotion-v1',
                'unavailable': False,
            }

        data = {
            'score': round(avg_score, 2),
            'state': state,
            'trend': trend,
            'data_quality': quality,
            'face_present': face_present,
            'frame_count': len(video_frames),
            'sample_count': len(scores),
            'algorithm_version': 'server-attention-v2',
            'live_window_sec': live_window,
            'live_max_frames': max_frames,
            'emotion': last_data.get('emotion'),
            'mar': last_data.get('mar'),
            'smile_ratio': last_data.get('smile_ratio'),
            'emotion_scores': emotion_scores,
            'head_pose': last_data.get('head_pose'),
            'gaze': last_data.get('gaze'),
        }

        return AnalysisResult(
            session_id=context.session_id,
            analyzer_type='attention',
            mode=AnalysisMode.WINDOW,
            timestamp=time.time(),
            data=data,
            confidence=avg_score / 100.0,
            frame_index=context.frame_index,
        )

    def cleanup(self):
        if self._face_mesh:
            self._face_mesh.close()
        self._is_initialized = False
