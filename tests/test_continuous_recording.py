"""整场连续录制（方案 B）回归。"""
from pathlib import Path
import shutil

from app.behavior.service import BehaviorService
from app.behavior.store import BehaviorStore
from app.behavior.timeline import BehaviorTimeline
from app.session import get_session_manager
from app.sockets import handlers as handlers_mod
from app.sockets.handlers import (
    PrepareTrainingHandler,
    CancelPrepareTrainingHandler,
    PlayResourceHandler,
    FinalizeTrainingHandler,
    _close_runtime_session,
)
from app.services import recording_timeline as rt

_SESSIONS_TMP = Path("tests/_tmp_continuous_sessions")


def _sessions_root() -> Path:
    _SESSIONS_TMP.mkdir(parents=True, exist_ok=True)
    return _SESSIONS_TMP


def _reset_sessions_tmp():
    if _SESSIONS_TMP.exists():
        shutil.rmtree(_SESSIONS_TMP, ignore_errors=True)
    _SESSIONS_TMP.mkdir(parents=True, exist_ok=True)


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


def _patch_media(monkeypatch):
    calls = {"start": [], "stop": []}

    class _Media:
        def start_recording(self, sid, *a, **k):
            calls["start"].append(sid)
            return True

        def stop_recording(self, sid, *a, **k):
            calls["stop"].append(sid)
            return True

    monkeypatch.setattr(handlers_mod, "get_media_service", lambda: _Media())
    return calls


def _patch_analysis(monkeypatch):
    calls = {"start": [], "reconfigure": [], "end": []}

    class _Analysis:
        def start_session(self, sid, *a, **k):
            calls["start"].append(sid)
            return True

        def reconfigure_session(self, sid, *a, **k):
            calls["reconfigure"].append(sid)
            return True

        def set_speech_target(self, *a, **k):
            return True

        def set_pose_target_from_path(self, *a, **k):
            return True

        def end_session(self, sid, *a, **k):
            calls["end"].append(sid)
            return None

    monkeypatch.setattr(handlers_mod, "get_analysis_service", lambda: _Analysis())
    return calls


def _patch_audio(monkeypatch):
    import types
    import sys

    audio_mod = types.ModuleType("app.audio")
    audio_mod.get_audio_service = lambda: type(
        "A", (), {"process_play_resource": lambda *a, **k: None}
    )()
    monkeypatch.setitem(sys.modules, "app.audio", audio_mod)


def test_prepare_training_creates_warmup_without_analysis_session(monkeypatch):
    root = Path("tests/_tmp_prepare_behavior") / "t1"
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    _reset_sessions_tmp()
    _patch_behavior(monkeypatch, root)
    _clear_student_sessions(9001)
    _patch_media(monkeypatch)
    monkeypatch.setattr(rt, "sessions_root", _sessions_root)
    monkeypatch.setattr(handlers_mod, "load_student_label", lambda sid: ("测试生", 6))

    result = PrepareTrainingHandler.handle({
        "studentId": 9001,
        "mode": "assessment",
    })
    assert result["success"] is True
    assert result["training_session_id"]
    assert result["question_id"].endswith("_warmup")
    assert result["session_id"]
    assert result.get("recording_mode") == "continuous"
    assert result.get("human_dir_name", "").startswith("测试生-6-")
    assert result["human_dir_name"].endswith("-1")
    behavior_dir = root / result["human_dir_name"]
    assert (behavior_dir / "training.json").is_file()
    assert not (root / result["training_session_id"]).exists()

    session = get_session_manager().get_session(result["session_id"])
    assert session is not None
    assert session.is_active()
    assert (session.metadata or {}).get("warmup") is True
    assert (session.metadata or {}).get("continuous_recording") is True

    from app.services import get_analysis_service
    assert result["session_id"] not in get_analysis_service()._sessions

    rs = rt.get_recording_session(result["session_id"])
    assert rs is not None
    assert len(rs.segments) == 1
    assert rs.segments[0].seg_kind == "warmup"
    assert (rs.dir_path / "timeline.csv").exists()

    _clear_student_sessions(9001)


def test_cancel_prepare_stops_warmup(monkeypatch):
    root = Path("tests/_tmp_prepare_behavior") / "t2"
    root.mkdir(parents=True, exist_ok=True)
    _reset_sessions_tmp()
    _patch_behavior(monkeypatch, root)
    _clear_student_sessions(9002)
    _patch_media(monkeypatch)
    monkeypatch.setattr(rt, "sessions_root", _sessions_root)
    monkeypatch.setattr(handlers_mod, "load_student_label", lambda sid: ("取消生", 5))

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


def test_play_resource_reuses_media_session_no_restart(monkeypatch):
    """切题复用同一 media session，不 stop/start 录制。"""
    root = Path("tests/_tmp_prepare_behavior") / "t3"
    root.mkdir(parents=True, exist_ok=True)
    _reset_sessions_tmp()
    service, _ = _patch_behavior(monkeypatch, root)
    _clear_student_sessions(9003)
    media_calls = _patch_media(monkeypatch)
    analysis_calls = _patch_analysis(monkeypatch)
    _patch_audio(monkeypatch)
    monkeypatch.setattr(rt, "sessions_root", _sessions_root)
    monkeypatch.setattr(handlers_mod, "load_student_label", lambda sid: ("连录生", 7))
    monkeypatch.setattr(handlers_mod, "resolve_course_type_id", lambda course_id: 1)
    monkeypatch.setattr(
        PlayResourceHandler,
        "_resolve_course_type",
        staticmethod(lambda course_id, fallback="default": "naming"),
    )

    prepared = PrepareTrainingHandler.handle({"studentId": 9003, "mode": "training"})
    ts = prepared["training_session_id"]
    media_sid = prepared["session_id"]
    assert media_calls["start"] == [media_sid]

    result1 = PlayResourceHandler.handle({
        "action": "play",
        "studentId": 9003,
        "courseId": 1,
        "itemId": 10,
        "courseType": "naming",
        "questionIndex": 0,
        "trainingSessionId": ts,
        "aux": {"targetText": "苹果"},
    })
    assert result1 is not None
    assert result1["training_session_id"] == ts
    assert result1["session_id"] == media_sid
    assert result1.get("recording_mode") == "continuous"
    assert result1.get("mode") == "training"
    assert get_session_manager().get_session(media_sid) is not None
    assert service.store.get_window(ts, result1["question_id"]) is not None
    assert media_calls["start"] == [media_sid]
    assert media_calls["stop"] == []
    assert analysis_calls["reconfigure"] == [media_sid]

    result2 = PlayResourceHandler.handle({
        "action": "play",
        "studentId": 9003,
        "courseId": 1,
        "itemId": 11,
        "courseType": "naming",
        "questionIndex": 1,
        "trainingSessionId": ts,
        "aux": {"targetText": "香蕉"},
    })
    assert result2["session_id"] == media_sid
    assert media_calls["start"] == [media_sid]
    assert media_calls["stop"] == []
    assert analysis_calls["reconfigure"] == [media_sid, media_sid]
    assert analysis_calls["end"] == []

    rs = rt.get_recording_session(media_sid)
    assert rs is not None
    assert len(rs.segments) == 3
    assert rs.segments[0].seg_kind == "warmup"
    assert rs.segments[1].seg_kind == "course"
    assert rs.segments[2].seg_kind == "course"
    assert rs.segments[0].t_end_sec is not None
    assert rs.segments[1].t_end_sec is not None
    assert rs.segments[2].t_end_sec is None

    finalized = FinalizeTrainingHandler.handle({
        "studentId": 9003,
        "trainingSessionId": ts,
    })
    assert finalized["success"] is True
    assert media_sid in (finalized.get("stoppedRuntimeSessions") or [])
    assert media_calls["stop"] == [media_sid]

    timeline = _SESSIONS_TMP / prepared["human_dir_name"] / "timeline.csv"
    assert timeline.exists()
    text = timeline.read_text(encoding="utf-8")
    assert "warmup" in text
    assert "course" in text


def test_human_dir_n_increments(monkeypatch):
    _reset_sessions_tmp()
    monkeypatch.setattr(rt, "sessions_root", _sessions_root)
    (_SESSIONS_TMP / "同名-6-20260713-1").mkdir()
    name, n = rt.allocate_human_dir_name(
        student_id=1,
        student_name="同名",
        student_age=6,
        date_str="20260713",
    )
    assert n == 2
    assert name == "同名-6-20260713-2"


def test_sanitize_and_timeline_csv(monkeypatch):
    _reset_sessions_tmp()
    monkeypatch.setattr(rt, "sessions_root", _sessions_root)
    assert rt.sanitize_student_name("张/小*明", 1) == "张_小_明"
    assert rt.sanitize_student_name("", 42) == "student42"
    assert rt.format_age(None) == "NA"

    human, n = rt.allocate_human_dir_name(
        student_id=1, student_name="甲", student_age=8, date_str="20260713"
    )
    rs = rt.begin_recording_session(
        media_session_id="media-1",
        training_session_id="train-1",
        student_id=1,
        human_dir_name=human,
        n=n,
    )
    rt.mark_course_segment(
        "media-1",
        course_id=1,
        course_item_id=10,
        course_type_id=2,
        question_id="1_10_0",
    )
    path = rt.finalize_recording_session("media-1", status="finalized")
    assert path is not None
    assert path.exists()
    rows = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 3  # header + warmup + course
    assert (rs.dir_path / "session_meta.json").exists()
