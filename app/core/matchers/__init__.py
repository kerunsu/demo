"""
比对器模块

提供各种比对器的Mock和Real实现
"""

from app.core.matchers.pose_matcher import MockPoseMatcher
from app.core.matchers.speech_matcher import MockSpeechMatcher
from app.core.matchers.real_pose_matcher import RealPoseMatcher

__all__ = [
    'MockPoseMatcher',
    'MockSpeechMatcher',
    'RealPoseMatcher',
]

