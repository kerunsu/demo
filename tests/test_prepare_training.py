"""prepare_training / 连续录制 warmup 回归（与 test_continuous_recording 互补）。"""
from pathlib import Path

from app.behavior.service import BehaviorService
from app.behavior.store import BehaviorStore
from app.behavior.timeline import BehaviorTimeline
from app.session import get_session_manager
from app.sockets import handlers as handlers_mod
from app.sockets.handlers import (
    PrepareTrainingHandler,
    CancelPrepareTrainingHandler,
    PlayResourceHandler,
    _close_runtime_session,
)
from app.services import recording_timeline as rt


def _sessions_root() -> Path:
    p = Path("tests/_tmp_continuous_sessions")
    p.mkdir(parents=True, exist_ok=True)
    return p


def _patch_behavior(monkeypatch, root: Path):
    store = BehaviorStore(root)
    service = BehaviorService()
    service.store = store
    service.timeline = BehaviorTimeline(store)
    monkeypatch.setattr(handlers_mod, "get_behavior_service", lambda: service)
    return service, store


def _clear_student_sessions(student_id: int):
    sm = get_session_manager()
    for sess in list(sm.get_sessions_by_student(student_id)):
        try:
            _close_runtime_session(sess.session_id, send_summary=False)
        except Exception:
            pass


def test_prepare_training_creates_warmup_without_analysis_session(monkeypatch):
    root = Path("tests/_tmp_prepare_behavior") / "t1"
    root.mkdir(parents=True, exist_ok=True)
    _patch_behavior(monkeypatch, root)
    _clear_student_sessions(9001)
    monkeypatch.setattr(rt, "sessions_root", _sessions_root)
    monkeypatch.setattr(handlers_mod, "load_student_label", lambda sid: ("测试生", 6))

    class _Media:
        def start_recording(self, *a, **k):
            return True

        def stop_recording(self, *a, **k):
            return True

    monkeypatch.setattr(handlers_mod, "get_media_service", lambda: _Media())

    result = PrepareTrainingHandler.handle({
        "studentId": 9001,
        "mode": "assessment",
    })
    assert result["success"] is True
    assert result["training_session_id"]
    assert result["question_id"].endswith("_warmup")
    assert result["session_id"]
    assert result.get("recording_mode") == "continuous"

    session = get_session_manager().get_session(result["session_id"])
    assert session is not None
    assert session.is_active()
    assert (session.metadata or {}).get("warmup") is True

    from app.services import get_analysis_service
    assert result["session_id"] not in get_analysis_service()._sessions
    _clear_student_sessions(9001)


def test_prepare_training_auto_uses_strict_preflight_for_agent_mode(monkeypatch):
    root = Path("tests/_tmp_prepare_behavior") / "auto-strict"
    root.mkdir(parents=True, exist_ok=True)
    _patch_behavior(monkeypatch, root)
    _clear_student_sessions(9010)
    monkeypatch.setattr(rt, "sessions_root", _sessions_root)
    monkeypatch.setattr(handlers_mod, "load_student_label", lambda sid: ("严格预检生", 6))
    monkeypatch.setattr("app.config.Config.get_child_media_mode", lambda: "agent")

    result = PrepareTrainingHandler.handle({
        "studentId": 9010,
        "mode": "training",
        "preflightMode": "auto",
    })

    assert result["success"] is True
    assert result["preflight_mode"] == "strict"
    assert result["preflight_only"] is True
    assert result["capture_started"] is False
    session = get_session_manager().get_session(result["session_id"])
    assert (session.metadata or {})["strict_preflight"] is True

    CancelPrepareTrainingHandler.handle({
        "studentId": 9010,
        "trainingSessionId": result["training_session_id"],
    })
    assert get_session_manager().get_session(result["session_id"]) is None


def test_start_preflight_capture_legacy_session_is_idempotent(monkeypatch):
    """readiness always calls start_preflight_capture; legacy prepare already recorded."""
    root = Path("tests/_tmp_prepare_behavior") / "legacy-idempotent"
    root.mkdir(parents=True, exist_ok=True)
    _patch_behavior(monkeypatch, root)
    _clear_student_sessions(9013)
    monkeypatch.setattr(rt, "sessions_root", _sessions_root)
    monkeypatch.setattr(handlers_mod, "load_student_label", lambda sid: ("遗留路径生", 6))
    monkeypatch.setattr("app.config.Config.get_child_media_mode", lambda: "browser")

    prepared = PrepareTrainingHandler.handle({
        "studentId": 9013,
        "mode": "training",
        "preflightMode": "auto",
        "requestId": "legacy-capture-1",
    })
    assert prepared["success"] is True
    assert prepared["preflight_mode"] == "legacy"
    started = handlers_mod.start_preflight_capture(prepared["training_session_id"])
    assert started["ok"] is True
    assert started.get("legacy") is True
    assert started["sessionId"] == prepared["session_id"]

    CancelPrepareTrainingHandler.handle({
        "studentId": 9013,
        "trainingSessionId": prepared["training_session_id"],
    })


def test_start_preflight_capture_missing_session_is_actionable():
    missing = handlers_mod.start_preflight_capture("training-does-not-exist")
    assert missing["ok"] is False
    assert missing["error"] == "strict_preflight_session_not_found"
    assert "重新点击开始评估" in missing["message"]


def test_prepare_training_reuses_logical_duplicate_with_new_request_id(monkeypatch):
    root = Path("tests/_tmp_prepare_behavior") / "logical-idempotency"
    root.mkdir(parents=True, exist_ok=True)
    _patch_behavior(monkeypatch, root)
    _clear_student_sessions(9011)
    handlers_mod._prepare_idempotency_cache.clear()
    handlers_mod._prepare_logical_cache.clear()
    monkeypatch.setattr(rt, "sessions_root", _sessions_root)
    monkeypatch.setattr(handlers_mod, "load_student_label", lambda sid: ("幂等生", 6))
    monkeypatch.setattr("app.config.Config.get_child_media_mode", lambda: "agent")

    first = PrepareTrainingHandler.handle({
        "studentId": 9011,
        "mode": "assessment",
        "preflightMode": "auto",
        "requestId": "prepare-logical-1",
    })
    second = PrepareTrainingHandler.handle({
        "studentId": 9011,
        "mode": "assessment",
        "preflightMode": "auto",
        "requestId": "prepare-logical-2",
    })

    assert second["success"] is True
    assert second["idempotentReplay"] is True
    assert second["session_id"] == first["session_id"]
    assert second["training_session_id"] == first["training_session_id"]
    assert len(get_session_manager().get_sessions_by_student(9011)) == 1

    CancelPrepareTrainingHandler.handle({
        "studentId": 9011,
        "trainingSessionId": first["training_session_id"],
    })


def test_cancel_prepare_stops_warmup(monkeypatch):
    root = Path("tests/_tmp_prepare_behavior") / "t2"
    root.mkdir(parents=True, exist_ok=True)
    _patch_behavior(monkeypatch, root)
    _clear_student_sessions(9002)
    monkeypatch.setattr(rt, "sessions_root", _sessions_root)
    monkeypatch.setattr(handlers_mod, "load_student_label", lambda sid: ("取消生", 5))

    class _Media:
        def start_recording(self, *a, **k):
            return True

        def stop_recording(self, *a, **k):
            return True

    monkeypatch.setattr(handlers_mod, "get_media_service", lambda: _Media())

    prepared = PrepareTrainingHandler.handle({"studentId": 9002, "mode": "training"})
    assert prepared["success"] is True
    sid = prepared["session_id"]

    cancelled = CancelPrepareTrainingHandler.handle({
        "studentId": 9002,
        "trainingSessionId": prepared["training_session_id"],
    })
    assert cancelled["success"] is True
    assert sid in (cancelled.get("stoppedSessions") or [])
    assert get_session_manager().get_session(sid) is None


def test_play_resource_reuses_prepared_training(monkeypatch):
    """方案 B：play_resource 复用 prepare 的 media session_id。"""
    root = Path("tests/_tmp_prepare_behavior") / "t3"
    root.mkdir(parents=True, exist_ok=True)
    service, _ = _patch_behavior(monkeypatch, root)
    _clear_student_sessions(9003)
    monkeypatch.setattr(rt, "sessions_root", _sessions_root)
    monkeypatch.setattr(handlers_mod, "load_student_label", lambda sid: ("连录生", 7))
    monkeypatch.setattr(handlers_mod, "resolve_course_type_id", lambda course_id: 1)

    class _Media:
        def start_recording(self, *a, **k):
            return True

        def stop_recording(self, *a, **k):
            return True

    class _Analysis:
        def start_session(self, *a, **k):
            return True

        def reconfigure_session(self, *a, **k):
            return True

        def set_speech_target(self, *a, **k):
            return True

        def set_pose_target_from_path(self, *a, **k):
            return True

        def end_session(self, *a, **k):
            return None

    monkeypatch.setattr(handlers_mod, "get_media_service", lambda: _Media())
    monkeypatch.setattr(handlers_mod, "get_analysis_service", lambda: _Analysis())
    monkeypatch.setattr(
        PlayResourceHandler,
        "_resolve_course_type",
        staticmethod(lambda course_id, fallback="default": "naming"),
    )

    import types
    import sys
    audio_mod = types.ModuleType("app.audio")
    audio_mod.get_audio_service = lambda: type(
        "A", (), {"process_play_resource": lambda *a, **k: None}
    )()
    monkeypatch.setitem(sys.modules, "app.audio", audio_mod)

    prepared = PrepareTrainingHandler.handle({"studentId": 9003, "mode": "training"})
    ts = prepared["training_session_id"]
    warmup_sid = prepared["session_id"]

    result = PlayResourceHandler.handle({
        "action": "play",
        "studentId": 9003,
        "courseId": 1,
        "itemId": 10,
        "courseType": "naming",
        "questionIndex": 0,
        "trainingSessionId": ts,
        "aux": {"targetText": "苹果"},
    })
    assert result is not None
    assert result["training_session_id"] == ts
    assert result["session_id"] == warmup_sid  # 连续录制：同一 media session
    assert get_session_manager().get_session(warmup_sid) is not None
    assert service.store.get_window(ts, result["question_id"]) is not None
    _clear_student_sessions(9003)
