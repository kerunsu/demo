import numpy as np

from app.core.audio.real_speech_analyzer import RealSpeechAnalyzer
from app.core.matchers.real_speech_matcher import RealSpeechMatcher
from app.core.models import AnalysisMode, AnalysisResult, MatchResult
from app.core.trigger import TriggerFactory, TriggerEvaluator, TriggerType
from app.utils.server_runtime import resolve_server_run_options


def test_audio_sample_rate_uses_audio_specific_config():
    analyzer = RealSpeechAnalyzer(config={
        "sample_rate": 1,
        "sample_rate_audio": 16000,
        "accumulation_duration": 2,
    })
    assert analyzer._target_sample_rate == 16000


def test_invalid_audio_sample_rate_falls_back_to_16khz():
    analyzer = RealSpeechAnalyzer(config={"sample_rate_audio": 1})
    assert analyzer._target_sample_rate == 16000


def test_short_pcm_chunks_are_accumulated_before_asr(monkeypatch):
    analyzer = RealSpeechAnalyzer(config={
        "sample_rate_audio": 16000,
        "accumulation_duration": 2,
    })
    calls = []
    monkeypatch.setattr(analyzer, "analyze_audio", lambda audio, context: calls.append(len(audio)) or "done")

    for _ in range(7):
        assert analyzer.analyze_chunk(np.ones(4096, dtype=np.float32), None) is None
    assert analyzer.analyze_chunk(np.ones(4096, dtype=np.float32), None) == "done"
    assert calls == [32768]


def test_real_matcher_compares_recognized_text_not_generic_confidence():
    matcher = RealSpeechMatcher(threshold=60)
    matcher.set_target("苹果")
    unrelated = AnalysisResult(
        session_id="s1",
        analyzer_type="speech",
        mode=AnalysisMode.REALTIME,
        timestamp=0,
        data={"transcript": "今天天气非常不错", "scores": [0.9]},
        confidence=0.99,
    )
    matched = AnalysisResult(
        session_id="s1",
        analyzer_type="speech",
        mode=AnalysisMode.REALTIME,
        timestamp=0,
        data={"transcript": "这是苹果", "scores": [0.9]},
        confidence=0.1,
    )
    assert matcher.match_from_result(unrelated).passed is False
    assert matcher.match_from_result(matched).passed is True


def test_speech_praise_trigger_requires_matcher_passed():
    """Regression: 旧阈值 0.80 对 0–100 分几乎恒真，会误触发表扬。"""
    trigger = TriggerFactory.speech_match_success(threshold=0.80)
    assert trigger.condition.trigger_type == TriggerType.MATCH_SUCCESS

    low_score = MatchResult(
        session_id="s1",
        timestamp=0,
        matcher_type="speech_matcher",
        passed=False,
        score=15.0,
        threshold=60.0,
        details={},
    )
    high_score_but_failed = MatchResult(
        session_id="s1",
        timestamp=0,
        matcher_type="speech_matcher",
        passed=False,
        score=55.0,
        threshold=60.0,
        details={},
    )
    passed = MatchResult(
        session_id="s1",
        timestamp=0,
        matcher_type="speech_matcher",
        passed=True,
        score=88.0,
        threshold=60.0,
        details={},
    )
    assert TriggerEvaluator.evaluate(trigger.condition, low_score, trigger) is False
    assert TriggerEvaluator.evaluate(trigger.condition, high_score_but_failed, trigger) is False
    assert TriggerEvaluator.evaluate(trigger.condition, passed, trigger) is True


def test_server_reloader_is_opt_in(monkeypatch):
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    monkeypatch.delenv("FLASK_USE_RELOADER", raising=False)
    assert resolve_server_run_options() == {"debug": False, "use_reloader": False}

    monkeypatch.setenv("FLASK_DEBUG", "1")
    assert resolve_server_run_options() == {"debug": True, "use_reloader": False}

    monkeypatch.setenv("FLASK_USE_RELOADER", "1")
    assert resolve_server_run_options() == {"debug": True, "use_reloader": True}
