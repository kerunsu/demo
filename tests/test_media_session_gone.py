"""会话已结束后媒体上行应返回 410，缺失会话日志应限流。"""
from __future__ import annotations

import time

from flask import Flask

from app.routes import media_upload as media_mod
from app.sockets import handlers as handlers_mod
from app.sockets.handlers import AudioChunkHandler, VideoFrameHandler


def test_upload_frames_returns_410_when_session_missing(monkeypatch):
    class _SM:
        def get_session(self, _sid):
            return None

    monkeypatch.setattr(media_mod, "get_session_manager", lambda: _SM())

    app = Flask(__name__)
    app.register_blueprint(media_mod.media_bp)
    client = app.test_client()

    resp = client.post(
        "/api/media/dead-session/frames",
        json={"frame": "abc", "seq": 1},
    )
    assert resp.status_code == 410
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error"] == "session_gone"


def test_upload_audio_returns_410_when_session_missing(monkeypatch):
    class _SM:
        def get_session(self, _sid):
            return None

    monkeypatch.setattr(media_mod, "get_session_manager", lambda: _SM())

    app = Flask(__name__)
    app.register_blueprint(media_mod.media_bp)
    client = app.test_client()

    resp = client.post(
        "/api/media/dead-session/audio-chunks",
        json={"chunk": "abc", "seq": 1},
    )
    assert resp.status_code == 410
    assert resp.get_json()["error"] == "session_gone"


def test_missing_session_warning_is_rate_limited(monkeypatch, caplog):
    class _SM:
        def get_session(self, _sid):
            return None

    monkeypatch.setattr(handlers_mod, "get_session_manager", lambda: _SM())
    handlers_mod._missing_session_log_at.clear()
    handlers_mod._MISSING_SESSION_LOG_INTERVAL_SEC = 60.0

    with caplog.at_level("WARNING", logger="socket_handlers"):
        assert VideoFrameHandler.handle({
            "sessionId": "s1",
            "frame": "x",
        }) is False
        assert VideoFrameHandler.handle({
            "sessionId": "s1",
            "frame": "y",
        }) is False
        assert AudioChunkHandler.handle({
            "sessionId": "s1",
            "chunk": "z",
        }) is False

    video_warns = [r for r in caplog.records if "video_frame" in r.getMessage()]
    audio_warns = [r for r in caplog.records if "audio_chunk" in r.getMessage()]
    assert len(video_warns) == 1
    assert len(audio_warns) == 1

    # 过期后应再打一次
    handlers_mod._missing_session_log_at["video_frame:s1"] = time.time() - 120
    with caplog.at_level("WARNING", logger="socket_handlers"):
        assert VideoFrameHandler.handle({
            "sessionId": "s1",
            "frame": "again",
        }) is False
    video_warns = [r for r in caplog.records if "video_frame" in r.getMessage()]
    assert len(video_warns) == 2
