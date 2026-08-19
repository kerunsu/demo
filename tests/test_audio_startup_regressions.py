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


def test_initialize_falls_back_to_voice_service_when_torch_missing(monkeypatch):
    """主 venv 无 torch 时，连续 ASR 应回退到已就绪的 voice-service。"""
    import builtins

    analyzer = RealSpeechAnalyzer(config={"sample_rate_audio": 16000, "device": "cpu"})
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "torch" or name.startswith("torch."):
            raise ModuleNotFoundError("No module named 'torch'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(
        "app.dialogue.stt.voice_service_ready",
        lambda timeout=2.0: True,
    )
    assert analyzer.initialize() is True
    assert analyzer._backend == "voice-service"
    assert analyzer.is_ready is True


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


class _DummyCtx:
    session_id = "s1"
    aux_data = {}
    frame_index = None


def test_low_energy_noise_skips_asr_even_if_peak_norm_would_pass(monkeypatch):
    """Regression: peak-norm before VAD made ambient noise always look like speech."""
    analyzer = RealSpeechAnalyzer(config={"sample_rate_audio": 16000})
    analyzer._is_initialized = True
    analyzer._backend = "voice-service"
    calls = []
    monkeypatch.setattr(
        analyzer,
        "_recognize_text",
        lambda *_a, **_k: calls.append(1) or ("Gyggny.", "voice-service-funasr"),
    )
    # Quiet ambient: raw rms≈0.01 / peak≈0.03 — below gate, but old code
    # peak-normalized to 0.95 and always called FunASR.
    rng = np.random.default_rng(0)
    quiet = (rng.standard_normal(16000).astype(np.float32) * 0.01).clip(-0.03, 0.03)
    result = analyzer.analyze_audio(quiet, _DummyCtx())
    assert calls == []
    assert result is not None
    assert result.data.get("transcript") == ""
    assert result.data.get("is_speech") is False


def test_short_handling_noise_does_not_trigger_asr(monkeypatch):
    """A loud click/handling burst must not satisfy sustained voice activity."""
    analyzer = RealSpeechAnalyzer(config={"sample_rate_audio": 16000})
    analyzer._is_initialized = True
    analyzer._backend = "voice-service"
    calls = []
    monkeypatch.setattr(
        analyzer,
        "_recognize_text",
        lambda *_a, **_k: calls.append(1) or ("这是什么", "voice-service-funasr"),
    )
    audio = np.zeros(32000, dtype=np.float32)
    audio[8000:8800] = 0.2  # 50ms burst inside a 2s ASR window
    result = analyzer.analyze_audio(audio, _DummyCtx())
    assert calls == []
    assert result.data["vad"]["voiced_ratio"] < 0.12


def test_speech_level_audio_still_reaches_asr(monkeypatch):
    analyzer = RealSpeechAnalyzer(config={"sample_rate_audio": 16000})
    analyzer._is_initialized = True
    analyzer._backend = "voice-service"
    calls = []
    monkeypatch.setattr(
        analyzer,
        "_recognize_text",
        lambda *_a, **_k: calls.append(1) or ("老虎", "voice-service-funasr"),
    )
    speech = (np.sin(np.linspace(0, 40 * np.pi, 16000)).astype(np.float32) * 0.2)
    result = analyzer.analyze_audio(speech, _DummyCtx())
    assert calls == [1]
    assert result.data.get("transcript") == "老虎"


def test_quiet_child_speech_still_reaches_maimai_asr(monkeypatch):
    """The ambient gate must not undo MaiMaiCtrl's quiet-speech accuracy."""
    analyzer = RealSpeechAnalyzer(config={"sample_rate_audio": 16000})
    analyzer._is_initialized = True
    analyzer._backend = "voice-service"
    calls = []
    monkeypatch.setattr(
        analyzer,
        "_recognize_text",
        lambda *_a, **_k: calls.append(1) or ("老虎", "voice-service-funasr"),
    )
    speech = np.sin(np.linspace(0, 40 * np.pi, 16000)).astype(np.float32) * 0.025
    result = analyzer.analyze_audio(speech, _DummyCtx())
    assert calls == [1]
    assert result.data.get("transcript") == "老虎"


def test_quiet_speech_uses_bounded_gain_instead_of_peak_normalization(monkeypatch):
    analyzer = RealSpeechAnalyzer(config={"sample_rate_audio": 16000})
    analyzer._is_initialized = True
    analyzer._backend = "voice-service"
    captured = []
    monkeypatch.setattr(
        analyzer,
        "_recognize_text",
        lambda audio: captured.append(audio.copy()) or ("猫", "voice-service-funasr"),
    )
    speech = np.sin(np.linspace(0, 40 * np.pi, 16000)).astype(np.float32) * 0.025
    result = analyzer.analyze_audio(speech, _DummyCtx())
    assert result.data["transcript"] == "猫"
    assert len(captured) == 1
    # 0.025 * max gain 3 is about 0.075, not the previous full-scale 0.95.
    assert int(np.max(np.abs(captured[0]))) < 4000


def test_plausible_asr_text_rejects_latin_gibberish():
    assert RealSpeechAnalyzer._is_plausible_asr_text("Gyggny.") is False
    assert RealSpeechAnalyzer._is_plausible_asr_text("嗯") is False
    assert RealSpeechAnalyzer._is_plausible_asr_text("老虎") is True
    assert RealSpeechAnalyzer._is_plausible_asr_text("这是苹果。") is True


def test_repeated_asr_windows_do_not_reemit_same_sentence(monkeypatch):
    analyzer = RealSpeechAnalyzer(config={"sample_rate_audio": 16000})
    analyzer._is_initialized = True
    analyzer._backend = "voice-service"
    monkeypatch.setattr(
        analyzer,
        "_recognize_text",
        lambda *_a, **_k: ("这是老虎", "voice-service-funasr"),
    )
    speech = (np.sin(np.linspace(0, 40 * np.pi, 16000)).astype(np.float32) * 0.2)
    first = analyzer.analyze_audio(speech, _DummyCtx())
    second = analyzer.analyze_audio(speech, _DummyCtx())
    assert first.data.get("transcript") == "这是老虎"
    assert second.data.get("transcript") == ""


def test_ingest_preroll_is_consumed_by_next_asr_window(monkeypatch):
    analyzer = RealSpeechAnalyzer(config={
        "sample_rate_audio": 16000,
        "accumulation_duration": 2,
    })
    calls = []
    monkeypatch.setattr(
        analyzer,
        "analyze_audio",
        lambda audio, context: calls.append(len(audio)) or "done",
    )
    analyzer.ingest_preroll(np.ones(8000, dtype=np.float32), max_seconds=1.0)
    # 8000 already in preroll; 6 more 4096-sample chunks = 24576, total 32576 >= 32000
    for _ in range(5):
        assert analyzer.analyze_chunk(np.ones(4096, dtype=np.float32), None) is None
    assert analyzer.analyze_chunk(np.ones(4096, dtype=np.float32), None) == "done"
    assert calls and calls[0] >= 32000
