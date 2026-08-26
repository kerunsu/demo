from __future__ import annotations

from pathlib import Path

import cv2
import pytest

from app.core.matchers.real_pose_matcher import RealPoseMatcher
from app.core.models import AnalysisContext, AnalysisMode, AnalysisResult, MatchResult
from app.core.vision.real_pose_analyzer import RealPoseAnalyzer, RealPoseNormalizer
from app.services.pose_auto_praise import PoseAutoPraiseService


ROOT = Path(__file__).resolve().parents[1]


def _pose(*, left_wrist=(-0.7, -1.4), right_wrist=(0.7, -1.4)):
    """Build visible MediaPipe-like joints normalized around the shoulders."""
    points = [
        {'x': 0.0, 'y': 0.0, 'visibility': 1.0}
        for _ in range(33)
    ]
    points[11].update(x=-0.5, y=0.0)
    points[12].update(x=0.5, y=0.0)
    points[13].update(x=-0.65, y=-0.7)
    points[14].update(x=0.65, y=-0.7)
    points[15].update(x=left_wrist[0], y=left_wrist[1])
    points[16].update(x=right_wrist[0], y=right_wrist[1])
    # The synthetic unit pose is upper-body only, like the two current cards.
    for index in (23, 24, 25, 26, 27, 28):
        points[index]['visibility'] = 0.0
    return points


def test_action_similarity_distinguishes_hands_up_from_hands_under_chin():
    hands_up = RealPoseNormalizer.normalize_action(_pose())
    under_chin = RealPoseNormalizer.normalize_action(
        _pose(left_wrist=(-0.15, -0.25), right_wrist=(0.15, -0.25))
    )

    assert RealPoseNormalizer.compute_action_similarity(hands_up, hands_up) == 1.0
    assert RealPoseNormalizer.compute_action_similarity(hands_up, under_chin) < 0.5


def test_action_similarity_accepts_a_mirrored_action_and_rejects_missing_arms():
    target = RealPoseNormalizer.normalize_action(
        _pose(left_wrist=(-0.9, -1.3), right_wrist=(0.55, -0.8))
    )
    mirrored = RealPoseNormalizer.normalize_action(
        _pose(left_wrist=(-0.55, -0.8), right_wrist=(0.9, -1.3))
    )
    details = RealPoseNormalizer.compute_action_similarity_details(
        mirrored,
        target,
        allow_mirror=True,
    )
    assert details['score'] > 0.95
    assert details['mirrored'] is True

    hidden = _pose()
    for index in (13, 14, 15, 16):
        hidden[index]['visibility'] = 0.0
    hidden_score = RealPoseNormalizer.compute_action_similarity(
        RealPoseNormalizer.normalize_action(hidden),
        target,
    )
    assert hidden_score == 0.0


def test_pose_match_requires_continuous_frames_and_hold_time():
    matcher = RealPoseMatcher(config={
        'stable_frames': 4,
        'stable_hold_seconds': 0.6,
        'max_frame_gap_seconds': 0.55,
    })

    assert matcher._apply_stability('session-1', raw_passed=True, timestamp=0.0)['passed'] is False
    assert matcher._apply_stability('session-1', raw_passed=True, timestamp=0.2)['passed'] is False
    assert matcher._apply_stability('session-1', raw_passed=True, timestamp=0.4)['passed'] is False
    stable = matcher._apply_stability('session-1', raw_passed=True, timestamp=0.65)
    assert stable['passed'] is True
    assert stable['frames'] == 4

    reset = matcher._apply_stability('session-1', raw_passed=False, timestamp=0.7)
    assert reset == {'passed': False, 'frames': 0, 'hold_seconds': 0.0}
    assert matcher._apply_stability('session-1', raw_passed=True, timestamp=1.0)['frames'] == 1


def test_pose_match_result_exposes_stable_success_details(monkeypatch):
    matcher = RealPoseMatcher(threshold=0.72, config={
        'stable_frames': 4,
        'stable_hold_seconds': 0.6,
        'max_frame_gap_seconds': 0.55,
    })
    keypoints = _pose()
    assert matcher.set_target_keypoints(keypoints, 'hands-up') is True
    clock = iter((0.0, 0.2, 0.4, 0.65))
    monkeypatch.setattr('app.core.base_matcher.time.time', lambda: next(clock))

    results = []
    for frame_index in range(4):
        results.append(matcher.match_from_result(
            AnalysisResult(
                session_id='session-1',
                analyzer_type='pose',
                mode=AnalysisMode.REALTIME,
                timestamp=frame_index,
                data={'keypoints': keypoints},
                frame_index=frame_index,
            ),
            AnalysisContext(
                session_id='session-1',
                course_type='mimic',
                frame_index=frame_index,
            ),
        ))

    assert [result.passed for result in results] == [False, False, False, True]
    assert results[-1].details['algorithm_version'] == 'mediapipe-action-joints-v2'
    assert results[-1].details['stable_frames'] == 4
    assert results[-1].details['hold_ms'] == 650
    assert 'left_wrist' in results[-1].details['keypoint_details']


def test_packaged_model_separates_the_two_real_mimic_cards():
    analyzer = RealPoseAnalyzer(config={
        'model_path': str(ROOT / 'models' / 'pose_landmarker_lite.task'),
    })
    assert analyzer.initialize() is True
    try:
        features = []
        for name in ('pose_1.png', 'pose_2.png'):
            image = cv2.imread(str(ROOT / 'static' / 'resources' / 'images' / 'mimic' / name))
            assert image is not None
            keypoints = analyzer.detect_from_image(image)
            assert len(keypoints) == 33
            features.append(RealPoseNormalizer.normalize_action(keypoints))
        score = RealPoseNormalizer.compute_action_similarity(features[0], features[1])
        assert score < 0.5
    finally:
        analyzer.cleanup()


def _passed_result(session_id='runtime-1'):
    return MatchResult(
        session_id=session_id,
        matcher_type='pose_matcher',
        timestamp=1.0,
        score=0.91,
        passed=True,
        threshold=0.72,
        details={
            'algorithm_version': 'mediapipe-action-joints-v2',
            'stable_frames': 5,
            'hold_ms': 700,
            'coverage': 1.0,
            'mirrored': False,
        },
    )


def test_pose_auto_praise_reuses_full_package_and_deduplicates(monkeypatch):
    from app.sockets import events

    service = PoseAutoPraiseService()
    context = {
        'course_type': 'mimic',
        'training_session_id': 'training-1',
        'question_id': 'question-1',
        'item_id': 11,
        'course_id': 1,
        'student_id': 2,
    }
    monkeypatch.setattr(service, '_runtime_context', lambda _sid: dict(context))
    monkeypatch.setattr(service, '_record_child_response', lambda *args, **kwargs: None)
    monkeypatch.setattr(service, '_record_monitor_event', lambda *args, **kwargs: None)

    emitted = []
    monkeypatch.setattr(
        service,
        '_emit_teacher',
        lambda sid, payload: emitted.append((sid, dict(payload))) or True,
    )
    played = []

    def fake_parity(session_id, **kwargs):
        played.append((session_id, kwargs))
        kwargs['on_before_child_play']({
            'behaviorId': 'behavior-1',
            'behaviorAnimation': '/static/praise.mp4',
            'hasAnimation': True,
        })
        return {
            'ok': True,
            'serverPlayed': True,
            'behaviorId': 'behavior-1',
            'behaviorAnimation': '/static/praise.mp4',
            'hasAnimation': True,
        }

    monkeypatch.setattr(events, 'trigger_keyword_parity_praise', fake_parity)

    result = _passed_result()
    assert service.try_auto_praise('runtime-1', result) is True
    assert service.try_auto_praise('runtime-1', result) is False
    assert len(played) == 1
    assert played[0][1]['source'] == 'pose_match'
    assert emitted[0][1]['serverPlayed'] is True
    assert emitted[0][1]['source'] == 'pose_match'

    context['question_id'] = 'question-2'
    context['item_id'] = 12
    assert service.try_auto_praise('runtime-1', result) is True
    assert len(played) == 2


def test_pose_auto_praise_rejects_wrong_session_and_non_pose_match(monkeypatch):
    service = PoseAutoPraiseService()
    monkeypatch.setattr(
        service,
        '_runtime_context',
        lambda _sid: pytest.fail('context must not be resolved'),
    )
    assert service.try_auto_praise('runtime-2', _passed_result('runtime-1')) is False
    result = _passed_result('runtime-2')
    result.matcher_type = 'speech_matcher'
    assert service.try_auto_praise('runtime-2', result) is False
