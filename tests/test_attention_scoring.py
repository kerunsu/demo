"""注意力打分组件：死区与 Landmark 左右映射回归。"""
from app.core.vision.real_attention_analyzer import RealAttentionAnalyzer
from app.core.models import AnalysisMode


def test_pose_score_full_in_deadzone():
    a = RealAttentionAnalyzer(mode=AnalysisMode.REALTIME, config={"pose_deadzone_deg": 15})
    assert a._score_pose_component(0, 0) == 40.0
    assert a._score_pose_component(10, 10) == 40.0  # sqrt(200)≈14.1 < 15


def test_pose_score_falls_off_outside_deadzone():
    a = RealAttentionAnalyzer(mode=AnalysisMode.REALTIME, config={
        "pose_deadzone_deg": 15,
        "pose_zero_at_deg": 55,
    })
    mid = a._score_pose_component(0, 35)  # |yaw|=35
    assert 0 < mid < 40
    assert a._score_pose_component(0, 55) == 0.0


def test_gaze_score_center_is_full():
    a = RealAttentionAnalyzer(mode=AnalysisMode.REALTIME)
    assert a._score_gaze_component(0.5) == 40.0
    assert a._score_gaze_component(0.52) == 40.0


def test_emotion_no_longer_crushes_attention_on_sad():
    assert RealAttentionAnalyzer._score_emotion_component("Sad") >= 12
    assert RealAttentionAnalyzer._score_emotion_component("Neutral") == 15
    assert RealAttentionAnalyzer._score_emotion_component("Happy") == 20


def test_normalize_euler_wraps_pitch():
    p, y, r = RealAttentionAnalyzer._normalize_euler(170, -20, 5)
    assert -90 <= p <= 90
    assert abs(y + 20) < 1e-6
