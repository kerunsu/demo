"""MonitorSnapshot API 单测：无会话 / 有会话字段存在性与连续录制语义。"""
from datetime import datetime
from pathlib import Path
import shutil

from app.behavior.models import TrainingSessionRecord
from app.behavior.service import BehaviorService
from app.behavior.store import BehaviorStore
from app.behavior.timeline import BehaviorTimeline
from app.monitor.snapshot import get_monitor_snapshot
from app.services import recording_timeline as rt
from app.session import get_session_manager
from app.session.session_model import Session, SessionStatus

_TMP = Path("tests/_tmp_monitor_snapshot")


def _reset_tmp():
    if _TMP.exists():
        shutil.rmtree(_TMP, ignore_errors=True)
    _TMP.mkdir(parents=True, exist_ok=True)


def _patch_behavior(monkeypatch):
    store = BehaviorStore(_TMP / "behavior")
    service = BehaviorService()
    service.store = store
    service.timeline = BehaviorTimeline(store)
    monkeypatch.setattr("app.monitor.snapshot.get_behavior_service", lambda: service, raising=False)
    # get_monitor_snapshot imports get_behavior_service inside function via app.behavior.service
    monkeypatch.setattr(
        "app.behavior.service.get_behavior_service",
        lambda: service,
    )
    return service, store


def test_snapshot_no_active_session(monkeypatch):
    _reset_tmp()
    _patch_behavior(monkeypatch)
    monkeypatch.setattr(rt, "list_active_recording_sessions", lambda: [])
    # 清空 session manager 活跃
    sm = get_session_manager()
    for s in list(sm.list_all_sessions()):
        sm.remove_session(s.session_id)

    data = get_monitor_snapshot()
    assert data["active"] is False
    assert data["session"] is None
    assert data["refreshHint"]["pollIntervalMs"] == 1000
    assert "health" in data
    assert data["health"]["mediaMode"] in ("agent", "browser")
    assert isinstance(data["preview"], dict)
    assert "enabled" in data["preview"]
    assert isinstance(data["events"], list)
    assert "childAgentOnline" in data["health"]
    assert "limitationLabels" in data["health"]


def test_snapshot_active_session_fields(monkeypatch):
    _reset_tmp()
    service, store = _patch_behavior(monkeypatch)

    training = TrainingSessionRecord(
        training_session_id="ts-monitor-1",
        student_id=42,
        status="active",
        metadata={"human_dir_name": "测试童-6-20260713-1", "recording_mode": "continuous"},
    )
    store.save_training(training)

    window = service.open_window(
        "ts-monitor-1",
        course_id=1,
        course_item_id=10,
        question_index=0,
        course_type="mimic",
        runtime_session_id="media-1",
    )

    service.record_attention(
        "ts-monitor-1",
        window.question_id,
        score=84.0,
        data_quality="VALID",
        face_present=True,
        provider="server",
        runtime_session_id="media-1",
    )

    # 登记连续录制会话
    monkeypatch.setattr(rt, "sessions_root", lambda: _TMP / "sessions")
    rs = rt.begin_recording_session(
        media_session_id="media-1",
        training_session_id="ts-monitor-1",
        student_id=42,
        human_dir_name="测试童-6-20260713-1",
        n=1,
    )
    assert rs is not None

    # SessionManager
    sm = get_session_manager()
    for s in list(sm.list_all_sessions()):
        sm.remove_session(s.session_id)
    sess = sm.create_session(
        student_id=42,
        course_id=1,
        course_item_id=10,
        training_session_id="ts-monitor-1",
        question_id=window.question_id,
        question_index=0,
        metadata={
            "continuous_recording": True,
            "recording_mode": "continuous",
            "human_dir_name": "测试童-6-20260713-1",
            "course_type": "mimic",
            "warmup": False,
        },
    )
    # create_session 可能生成新 id；强制对齐 media-1
    sm.remove_session(sess.session_id)
    sess = Session(
        session_id="media-1",
        student_id=42,
        course_id=1,
        course_item_id=10,
        training_session_id="ts-monitor-1",
        question_id=window.question_id,
        question_index=0,
        status=SessionStatus.RECORDING,
        started_at=datetime.utcnow(),
        metadata={
            "continuous_recording": True,
            "recording_mode": "continuous",
            "human_dir_name": "测试童-6-20260713-1",
            "course_type": "mimic",
            "warmup": False,
        },
    )
    sm._sessions[sess.session_id] = sess

    data = get_monitor_snapshot()
    assert data["active"] is True
    assert data["session"]["trainingSessionId"] == "ts-monitor-1"
    assert data["session"]["mediaSessionId"] == "media-1"
    assert data["session"]["runtimeSessionId"] == "media-1"
    assert data["session"]["humanDirName"] == "测试童-6-20260713-1"
    assert data["session"]["recordingMode"] == "continuous"
    assert data["course"]["courseType"] == "mimic"
    assert data["course"]["questionId"] == window.question_id
    assert data["attention"]["currentScore"] == 84.0
    assert data["attention"]["currentQuality"] == "VALID"
    assert data["attention"]["provider"] == "server"
    assert data["attention"]["sampleCount"] >= 1
    assert isinstance(data["attention"]["recentSamples"], list)
    assert isinstance(data["preview"], dict)
    assert data["preview"]["enabled"] in (True, False)
    assert isinstance(data["events"], list)

    # 显式 ID
    data2 = get_monitor_snapshot("ts-monitor-1")
    assert data2["session"]["mediaSessionId"] == data["session"]["mediaSessionId"]

    # 切题语义：同一 mediaSessionId，仅更新 question
    window2 = service.open_window(
        "ts-monitor-1",
        course_id=1,
        course_item_id=11,
        question_index=1,
        course_type="mimic",
        runtime_session_id="media-1",
    )
    sess.question_id = window2.question_id
    sess.question_index = 1
    sm.update_session(sess)

    data3 = get_monitor_snapshot("ts-monitor-1")
    assert data3["session"]["mediaSessionId"] == "media-1"
    assert data3["course"]["questionId"] == window2.question_id
    assert data3["course"]["questionIndex"] == 1

    # cleanup
    rt.finalize_recording_session("media-1")
    sm.remove_session("media-1")


def test_snapshot_missing_attention_score_is_null(monkeypatch):
    _reset_tmp()
    service, store = _patch_behavior(monkeypatch)

    training = TrainingSessionRecord(
        training_session_id="ts-monitor-missing",
        student_id=7,
        status="active",
        metadata={"human_dir_name": "缺脸童-6-20260716-1", "recording_mode": "continuous"},
    )
    store.save_training(training)
    window = service.open_window(
        "ts-monitor-missing",
        course_id=1,
        course_item_id=1,
        question_index=0,
        course_type="mimic",
        runtime_session_id="media-missing",
    )
    service.record_attention(
        "ts-monitor-missing",
        window.question_id,
        score=0.0,
        data_quality="MISSING",
        face_present=False,
        provider="server",
        runtime_session_id="media-missing",
    )
    monkeypatch.setattr(rt, "list_active_recording_sessions", lambda: [])
    monkeypatch.setattr(rt, "get_recording_session_by_training", lambda _tid: None)
    sm = get_session_manager()
    for s in list(sm.list_all_sessions()):
        sm.remove_session(s.session_id)
    sess = Session(
        session_id="media-missing",
        student_id=7,
        course_id=1,
        course_item_id=1,
        training_session_id="ts-monitor-missing",
        question_id=window.question_id,
        question_index=0,
        status=SessionStatus.RECORDING,
        started_at=datetime.utcnow(),
        metadata={
            "continuous_recording": True,
            "recording_mode": "continuous",
            "human_dir_name": "缺脸童-6-20260716-1",
            "course_type": "mimic",
            "warmup": False,
        },
    )
    sm._sessions[sess.session_id] = sess

    data = get_monitor_snapshot("ts-monitor-missing")
    assert data["attention"]["currentQuality"] == "MISSING"
    assert data["attention"]["currentScore"] is None
    labels = data["health"].get("limitationLabels") or []
    assert any("注意力" in x or "MISSING" in x or "样本" in x for x in labels)


def test_snapshot_preview_disabled(monkeypatch):
    from app.config import Config

    monkeypatch.setattr(Config, "MONITOR_PREVIEW_ENABLED", False)
    _reset_tmp()
    _patch_behavior(monkeypatch)
    monkeypatch.setattr(rt, "list_active_recording_sessions", lambda: [])
    sm = get_session_manager()
    for s in list(sm.list_all_sessions()):
        sm.remove_session(s.session_id)
    data = get_monitor_snapshot()
    assert data["preview"]["enabled"] is False
    assert data["preview"]["jpegBase64"] is None
