"""Phase 3 characterization tests for the new capture/storage ports.

These tests use only fake clocks, devices and capture sinks.  They do not
touch the repository's database, recordings or real hardware.
"""

from __future__ import annotations

from pathlib import Path

from app.acquisition.device_registry import InMemoryDeviceRegistry, stable_track_id
from app.acquisition.preflight_probe import CallbackDeviceBroker
from app.acquisition.timebase import TimebaseMapper
from app.computation.preflight import PreflightOrchestrator
from app.contracts.models import DeploymentProfile, DeviceProfile, DeviceRef, SessionRef
from app.storage.repositories.device_profile_store import JsonDeviceProfileStore
from app.storage.repositories.metadata_repository import FileMetadataRepository
from app.storage.repositories.recording_repository import FileRecordingRepository
from app.storage.repositories.timeline_repository import FileTimelineRepository
from app.storage.session_layout import SessionLayout
from app.storage.session_validator import validate_session_directory


class FakeClock:
    def monotonic_seconds(self):
        return 10.0

    def wall_time_iso(self):
        return "2026-01-01T00:00:00+00:00"


class FakeCapture:
    def __init__(self, *, first_samples=True):
        self.first_samples = first_samples
        self.starts = 0
        self.stops = 0

    def prepare(self, session, tracks):
        return {"ok": True}

    def start(self, session, tracks):
        self.starts += 1
        return {
            "ok": True,
            "tracks": [
                {"trackId": track.track_id, "firstSample": self.first_samples}
                for track in tracks
            ],
        }

    def stop(self, session):
        self.stops += 1
        return {"ok": True}

    def health(self, session):
        return {"ok": True}


def test_phase3_device_registry_freezes_zero_to_many_without_array_identity():
    registry = InMemoryDeviceRegistry(clock=FakeClock())
    registry.register(DeviceProfile(device_id="ambient-cam-a", track_id="", kind="video", role="primary_environment", required=True))
    registry.register(DeviceProfile(device_id="ambient-mic-b", track_id="", kind="audio", role="environment_secondary", required=False))

    snapshot = registry.freeze(DeploymentProfile(profile_id="classroom", strict_preflight=True))

    assert len(snapshot.devices) == 2
    assert snapshot.devices[0].track_id == stable_track_id("ambient-cam-a", "video", "primary_environment")
    assert snapshot.devices[0].track_id != snapshot.devices[1].track_id
    assert snapshot.created_at.wall_time_iso.endswith("+00:00")


def test_phase3_device_registry_persists_and_converts_discovery_refs(tmp_path: Path):
    class Discovery:
        def discover(self):
            return [DeviceRef(
                device_id="usb-camera-a",
                kind="video",
                device_type="camera",
                metadata={"role": "environment_secondary", "selector": {"index": 2}},
            )]

    store = JsonDeviceProfileStore(tmp_path / "capture_devices.json")
    registry = InMemoryDeviceRegistry(clock=FakeClock(), discoveries=[Discovery()], profile_store=store)
    discovered = registry.discover()
    assert discovered[0].track_id
    restored = InMemoryDeviceRegistry(clock=FakeClock(), profile_store=store)
    assert restored.get("usb-camera-a") == discovered[0]


def test_phase3_corrupt_device_store_fails_closed_without_overwrite(tmp_path: Path):
    path = tmp_path / "capture_devices.json"
    original = '{"schemaVersion":1,"devices":[{"device_id":"cam","kind":"video","role":"primary_environment","enabled":"false"}]}'
    path.write_text(original, encoding="utf-8")
    registry = InMemoryDeviceRegistry(clock=FakeClock(), profile_store=JsonDeviceProfileStore(path))

    assert registry.get_load_error()
    try:
        registry.register(DeviceProfile("replacement", "", "video", "environment_secondary"))
    except RuntimeError as exc:
        assert "device_registry_load_failed" in str(exc)
    else:
        raise AssertionError("a corrupt registry must not be overwritten")
    assert path.read_text(encoding="utf-8") == original


def test_phase3_discovery_is_atomic_when_tracks_conflict(tmp_path: Path):
    class ConflictingDiscovery:
        def discover(self):
            return [
                DeviceProfile("camera-a", "same-track", "video", "environment_secondary"),
                DeviceProfile("camera-b", "same-track", "video", "environment_secondary"),
            ]

    path = tmp_path / "capture_devices.json"
    registry = InMemoryDeviceRegistry(
        clock=FakeClock(),
        discoveries=[ConflictingDiscovery()],
        profile_store=JsonDeviceProfileStore(path),
    )
    try:
        registry.discover()
    except ValueError as exc:
        assert "duplicate_track_id" in str(exc)
    else:
        raise AssertionError("conflicting discovery must fail")
    assert registry.list_devices() == []
    assert not path.exists()


def test_phase3_device_registry_rejects_duplicate_track_identity():
    registry = InMemoryDeviceRegistry(clock=FakeClock())
    registry.register(DeviceProfile("camera-a", "same-track", "video", "environment_secondary"))
    try:
        registry.register(DeviceProfile("camera-b", "same-track", "video", "environment_secondary"))
    except ValueError as exc:
        assert str(exc) == "duplicate_track_id:same-track"
    else:
        raise AssertionError("duplicate track id must be rejected")


def test_phase3_timebase_normalizes_units_and_clamps_clock_rollback():
    mapper = TimebaseMapper(session_start_ns=1_000_000_000)
    first = mapper.normalize(1000, unit="ms")
    second = mapper.normalize(900, unit="ms")

    assert first.relative_ms == 0
    assert second.relative_ms == first.relative_ms
    assert mapper.correction_count == 1


def test_phase3_layout_preserves_legacy_names_and_stable_extra_tracks(tmp_path: Path):
    from app.contracts.models import TrackRef

    layout = SessionLayout(tmp_path / "sessions")
    assert layout.track_filename(TrackRef("child-v", "video", "primary_child")) == "video.avi"
    assert layout.track_filename(TrackRef("child-a", "audio", "primary_child")) == "audio.wav"
    assert layout.track_filename(TrackRef("env-v", "video", "primary_environment")) == "video.environment.avi"
    assert layout.track_filename(TrackRef("cam-second", "video", "environment_secondary")) == "video.environment.cam-second.avi"
    assert layout.track_filename(TrackRef("mic-second", "audio", "environment_secondary")) == "audio.environment.mic-second.wav"


def test_phase3_metadata_timeline_are_atomic_and_validator_is_read_only(tmp_path: Path):
    layout = SessionLayout(tmp_path / "sessions")
    session = SessionRef(session_id="s1", training_session_id="t1", media_session_id="m1")
    layout.bind(session, "student-NA-20260101-1")
    metadata = FileMetadataRepository(layout)
    timeline = FileTimelineRepository(layout)

    metadata.write(session, {"mediaSessionId": "m1", "tracks": [{"trackId": "env-a"}]})
    timeline.append(session, {"seg_kind": "warmup", "t_start_sec": 0.0})
    timeline.append(session, {"seg_kind": "course", "t_start_sec": 1.25})
    timeline.finalize(session, 2.0)

    assert metadata.read(session)["mediaSessionId"] == "m1"
    report = validate_session_directory(layout.resolve(session))
    assert report["readOnly"] is True
    assert report["status"] == "valid"
    assert report["timelineRows"] == 2
    rows = timeline.read(session)
    assert rows[0]["t_end_sec"] == "1.250"
    assert not list((layout.resolve(session)).glob("*.tmp"))


def test_phase3_recording_repository_writes_track_manifest_without_codec_knowledge(tmp_path: Path):
    from app.contracts.models import TrackRef

    layout = SessionLayout(tmp_path / "sessions")
    session = SessionRef(media_session_id="m-recording")
    layout.bind(session, "student-1")
    repository = FileRecordingRepository(layout)
    metadata = repository.begin(session, [TrackRef("child", "video", "primary_child", required=True)])
    assert metadata["tracks"][0]["filename"] == "video.avi"
    assert not (layout.resolve(session) / "video.avi").exists()


def test_phase3_device_probe_is_not_part_of_class_start(monkeypatch):
    from app.services.readiness_service import ReadinessService

    service = ReadinessService()
    monkeypatch.setattr(service, "_schedule_poll", lambda _gate: None)
    monkeypatch.setattr(service, "_schedule_timeout", lambda _gate: None)
    service.set_capture_start_callback(
        lambda _training: {"ok": True, "sessionId": "phase3-media"}
    )
    result = service.start("teacher", {
        "studentId": 1,
        "trainingSessionId": "phase3-training",
        "items": [{"courseId": 1, "itemId": 1, "courseType": "naming"}],
    })

    assert result["success"] is True
    assert [module["moduleId"] for module in result["modules"]] == ["M2"]


def test_phase3_callback_broker_fails_closed_without_real_probe():
    broker = CallbackDeviceBroker()
    device = DeviceProfile("required-camera", "required-track", "video", "primary_environment", required=True)
    assert broker.check(device)["ok"] is False
    assert broker.reserve(device)["ok"] is False


def test_phase3_preflight_does_not_start_capture_until_barrier_and_rolls_back():
    registry = InMemoryDeviceRegistry(clock=FakeClock())
    registry.register(DeviceProfile(device_id="required-cam", track_id="cam-track", kind="video", role="primary_environment", required=True))
    layout = SessionLayout(Path("." ) / "phase3-test-sessions")
    # Avoid making a repository directory in this test by using a temporary one.
    # The assertion is about lifecycle, not the legacy recordings root.
    import tempfile
    with tempfile.TemporaryDirectory() as root:
        layout = SessionLayout(Path(root))
        capture = FakeCapture()
        orchestrator = PreflightOrchestrator(
            registry=registry,
            broker=CallbackDeviceBroker({"check": lambda device: {"ok": True}}),
            capture=capture,
            layout=layout,
        )
        session = SessionRef(training_session_id="t1", media_session_id="m1")
        orchestrator.prepare(session, human_dir_name="student-1", deployment=DeploymentProfile(strict_preflight=True))
        assert capture.starts == 0
        checked = orchestrator.check(session)
        assert checked.required_ok is True
        started = orchestrator.start_barrier(session)
        assert started["ok"] is True
        assert capture.starts == 1
        assert orchestrator.start_barrier(session)["idempotent"] is True
        orchestrator.stop(session)
        assert capture.stops == 1

        failed_capture = FakeCapture(first_samples=False)
        failed_orchestrator = PreflightOrchestrator(
            registry=registry,
            broker=CallbackDeviceBroker({"check": lambda device: {"ok": True}}),
            capture=failed_capture,
            layout=SessionLayout(Path(root) / "failed"),
        )
        failed_orchestrator.prepare(
            SessionRef(training_session_id="t2", media_session_id="m2"),
            human_dir_name="student-2",
            deployment=DeploymentProfile(strict_preflight=True),
        )
        assert failed_orchestrator.check(SessionRef(training_session_id="t2", media_session_id="m2")).required_ok
        failed = failed_orchestrator.start_barrier(SessionRef(training_session_id="t2", media_session_id="m2"))
        assert failed["ok"] is False
        assert failed["rolledBack"] is True
        assert failed_capture.stops == 1
        # Failed start invalidates the old reservation; a retry performs a
        # fresh check instead of starting against a released device.
        failed_capture.first_samples = True
        assert failed_orchestrator.start_barrier(SessionRef(training_session_id="t2", media_session_id="m2"))["ok"] is True


def test_phase3_strict_prepare_reserves_without_formal_recording(monkeypatch, tmp_path: Path):
    from app.behavior.service import BehaviorService
    from app.behavior.store import BehaviorStore
    from app.behavior.timeline import BehaviorTimeline
    from app.services import recording_timeline as legacy_timeline
    from app.session import get_session_manager
    from app.sockets import handlers as handlers_module
    from app.sockets.handlers import CancelPrepareTrainingHandler, PrepareTrainingHandler

    behavior = BehaviorService()
    behavior.store = BehaviorStore(tmp_path / "behavior")
    behavior.timeline = BehaviorTimeline(behavior.store)
    monkeypatch.setattr(handlers_module, "get_behavior_service", lambda: behavior)
    monkeypatch.setattr(handlers_module, "load_student_label", lambda sid: ("strict-child", 6))
    monkeypatch.setattr(legacy_timeline, "sessions_root", lambda: tmp_path / "sessions")

    class FakeMedia:
        def __init__(self):
            self.starts = 0
            self.stops = 0
            self.start_ok = True

        def start_recording(self, *args, **kwargs):
            self.starts += 1
            return self.start_ok

        def stop_recording(self, *args, **kwargs):
            self.stops += 1
            return True

    media = FakeMedia()
    monkeypatch.setattr(handlers_module, "get_media_service", lambda: media)
    student_id = 9311
    for old in list(get_session_manager().get_sessions_by_student(student_id)):
        get_session_manager().remove_session(old.session_id)

    prepared = PrepareTrainingHandler.handle({
        "studentId": student_id,
        "mode": "training",
        "preflightMode": "strict",
        "requestId": "phase3-strict-prepare",
    })
    assert prepared["success"] is True
    assert prepared["preflight_only"] is True
    assert prepared["capture_started"] is False
    session = get_session_manager().get_session(prepared["session_id"])
    assert session.status.value == "created"
    assert media.starts == 0
    assert not (tmp_path / "sessions" / prepared["human_dir_name"] / "timeline.csv").exists()

    # Full strict lifecycle: the CREATED reservation must be visible to the
    # readiness gate and carry the same session id to the child before formal
    # capture starts.
    from app.services.readiness_service import ReadinessService

    readiness = ReadinessService()
    pending = readiness.check_capture(student_id, prepared["training_session_id"])
    assert pending["pending"] is True
    assert pending["sessionId"] == prepared["session_id"]
    child_events = []
    readiness.set_child_emitter(lambda event, payload: child_events.append((event, payload)))
    readiness.set_capture_start_callback(handlers_module.start_preflight_capture)
    monkeypatch.setattr(readiness, "_schedule_poll", lambda _gate: None)
    monkeypatch.setattr(readiness, "_schedule_timeout", lambda _gate: None)
    readiness.start("teacher-strict", {
        "studentId": student_id,
        "trainingSessionId": prepared["training_session_id"],
        "items": [{"courseId": 1, "itemId": 1, "courseType": "naming"}],
    })
    assert child_events[0][0] == "readiness_complete"
    assert child_events[0][1]["captureStart"] is True
    assert child_events[0][1]["sessionId"] == prepared["session_id"]
    assert media.starts == 1
    assert get_session_manager().get_session(prepared["session_id"]).is_active()
    cancelled = CancelPrepareTrainingHandler.handle({
        "studentId": student_id,
        "trainingSessionId": prepared["training_session_id"],
    })
    assert cancelled["success"] is True
    assert get_session_manager().get_session(prepared["session_id"]) is None

    media.start_ok = False
    failed_prepared = PrepareTrainingHandler.handle({
        "studentId": 9312,
        "mode": "training",
        "preflightMode": "strict",
        "requestId": "phase3-strict-start-failure",
    })
    failed_start = handlers_module.start_preflight_capture(failed_prepared["training_session_id"])
    assert failed_start["ok"] is False
    assert failed_start["rolledBack"] is True
    failed_session = get_session_manager().get_session(failed_prepared["session_id"])
    assert failed_session.metadata["capture_started"] is False
    CancelPrepareTrainingHandler.handle({
        "studentId": 9312,
        "trainingSessionId": failed_prepared["training_session_id"],
    })


def test_phase3_validator_reports_malformed_track_manifest_without_crashing(tmp_path: Path):
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    (session_dir / "session_meta.json").write_text('{"tracks": {"bad": true}}', encoding="utf-8")
    report = validate_session_directory(session_dir)
    assert report["status"] == "invalid"
    assert "tracks must be an array" in report["errors"][0]


def test_phase3_strict_readiness_waits_for_server_verified_formal_sample(monkeypatch):
    from app.services.readiness_service import ReadinessService

    teacher_events = []
    child_events = []
    server_has_sample = {"value": False}
    service = ReadinessService()
    service.set_emitter(lambda event, payload, sid=None: teacher_events.append((event, payload, sid)))
    service.set_child_emitter(lambda event, payload: child_events.append((event, payload)))
    service.set_capture_start_callback(lambda training_id: {"ok": True, "sessionId": "media-1"})
    monkeypatch.setattr(service, "_schedule_poll", lambda _gate: None)
    monkeypatch.setattr(service, "_schedule_timeout", lambda _gate: None)

    def _check_capture(student_id, training_id, report=None):
        if server_has_sample["value"]:
            return {"ok": True, "detail": "server accepted formal sample"}
        return {"ok": False, "pending": True, "detail": "waiting for server sample"}

    monkeypatch.setattr(service, "check_capture", _check_capture)
    service.start("teacher-7", {
        "studentId": 7,
        "trainingSessionId": "strict-formal-barrier",
        "items": [{"courseId": 1, "itemId": 1, "courseType": "naming"}],
    })
    gate = service.get_gate("strict-formal-barrier")
    assert gate.capture_start_attempted is True
    assert gate.capture_started is True
    assert gate.modules["M2"].status == "running"
    assert not [event for event in teacher_events if event[0] == "readiness_complete"]
    assert child_events[0][0] == "readiness_complete"
    assert child_events[0][1]["captureStart"] is True
    assert child_events[0][1]["captureStarted"] is False

    service.handle_child_report({
        "trainingSessionId": gate.training_session_id,
        "captureStartConfirmed": True,
        "recording": True,
        "mediaTracksOk": True,
        "probeFrame": "client-only-probe",
        "frameCount": 999,
        "hasRecentUplink": True,
    })
    assert gate.status == "STARTING"
    assert not [
        event for event in teacher_events
        if event[0] == "readiness_complete"
    ]

    server_has_sample["value"] = True
    service.handle_child_report({
        "trainingSessionId": gate.training_session_id,
        # Resource progress can prompt another poll, but it is never itself
        # recording evidence.
        "coursesReady": True,
        "audioTotal": 0,
        "audioComplete": True,
    })
    completed = [
        event for event in teacher_events
        if event[0] == "readiness_complete" and event[1].get("ok")
    ]
    assert gate.capture_started is True
    assert gate.server_sample_accepted is True
    assert len(completed) == 1
    assert completed[0][1]["captureStarted"] is True
