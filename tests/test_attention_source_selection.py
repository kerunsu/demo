"""behavior 注意力选源：prefer_browser vs server。"""
from types import SimpleNamespace

from app.behavior.emotion_scoring import select_attention_observations


def _obs(provider, quality="VALID", face=True, score=80.0):
    return SimpleNamespace(
        provider=provider,
        data_quality=quality,
        face_present=face,
        score=score,
    )


def test_prefer_browser_uses_valid_browser_only():
    items = [
        _obs("server", score=90),
        _obs("browser", score=70),
        _obs("browser", quality="MISSING", score=0),
    ]
    selected = select_attention_observations(items, prefer_browser=True)
    assert len(selected) == 1
    assert selected[0].provider == "browser"
    assert selected[0].score == 70


def test_prefer_browser_falls_back_to_server_when_browser_invalid():
    items = [
        _obs("server", score=88),
        _obs("browser", quality="MISSING", score=0, face=False),
    ]
    selected = select_attention_observations(items, prefer_browser=True)
    assert len(selected) == 1
    assert selected[0].provider == "server"
    assert selected[0].score == 88


def test_prefer_server_ignores_browser_when_server_valid():
    items = [
        _obs("browser", score=99),
        _obs("server", score=55),
    ]
    selected = select_attention_observations(items, prefer_browser=False)
    assert len(selected) == 1
    assert selected[0].provider == "server"


def test_empty_input():
    assert select_attention_observations([], prefer_browser=True) == []
