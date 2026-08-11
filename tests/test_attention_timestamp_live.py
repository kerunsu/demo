"""毫秒时间戳归一化与实时注意力近窗聚合。"""
import time

import numpy as np

from app.core.buffer import DataBuffer, normalize_media_timestamp
from app.core.models import AnalysisContext, AnalysisMode, AnalysisResult
from app.core.vision.real_attention_analyzer import RealAttentionAnalyzer


def test_normalize_media_timestamp_ms_to_seconds():
    now = time.time()
    ms = int(now * 1000)
    got = normalize_media_timestamp(ms, now=now)
    assert abs(got - now) < 0.05


def test_normalize_media_timestamp_seconds_passthrough():
    now = time.time()
    assert abs(normalize_media_timestamp(now, now=now) - now) < 1e-6


def test_buffer_expires_ms_timestamped_frames():
    buf = DataBuffer("ts-ms", window_size=1.0)
    now = time.time()
    # 模拟 agent 毫秒戳：3 秒前的帧应被清掉
    old_ms = int((now - 3.0) * 1000)
    new_ms = int(now * 1000)
    buf.add_video_frame(np.zeros((8, 8, 3), dtype=np.uint8), old_ms)
    buf.add_video_frame(np.full((8, 8, 3), 40, dtype=np.uint8), new_ms)
    frames = buf.get_video_frames()
    assert len(frames) == 1
    assert abs(frames[0][0] - now) < 0.2


class _StubAttention(RealAttentionAnalyzer):
    def analyze_frame(self, frame, context):
        mean = float(np.mean(frame))
        face = mean > 10
        return AnalysisResult(
            session_id=context.session_id,
            analyzer_type="attention",
            mode=AnalysisMode.REALTIME,
            timestamp=time.time(),
            data={
                "score": 90.0 if face else 0.0,
                "face_present": face,
                "has_face": face,
                "emotion": "Neutral",
                "emotion_scores": {
                    "positiveScore": 0.2,
                    "focusedScore": 0.6,
                    "frustratedScore": 0.2,
                },
            },
            confidence=0.9 if face else 0.0,
        )


def test_live_window_drops_old_high_scores():
    analyzer = _StubAttention(
        mode=AnalysisMode.WINDOW,
        config={"live_window_sec": 1.2, "live_max_frames": 10},
    )
    analyzer._is_initialized = True
    now = time.time()
    old_face = (now - 8.0, np.full((24, 24, 3), 120, dtype=np.uint8))
    new_blank = (now - 0.1, np.zeros((24, 24, 3), dtype=np.uint8))
    result = analyzer.analyze_window(
        [old_face, new_blank],
        [],
        AnalysisContext(session_id="cov"),
    )
    assert result.data["face_present"] is False
    assert result.data["score"] == 0.0


def test_live_window_recovers_to_high_without_old_zeros():
    analyzer = _StubAttention(
        mode=AnalysisMode.WINDOW,
        config={"live_window_sec": 1.2, "live_max_frames": 10},
    )
    analyzer._is_initialized = True
    now = time.time()
    old_blank = (now - 5.0, np.zeros((24, 24, 3), dtype=np.uint8))
    new_face = (now - 0.1, np.full((24, 24, 3), 120, dtype=np.uint8))
    result = analyzer.analyze_window(
        [old_blank, new_face],
        [],
        AnalysisContext(session_id="rec"),
    )
    assert result.data["face_present"] is True
    assert result.data["score"] >= 85.0
