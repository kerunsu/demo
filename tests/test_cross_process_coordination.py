from app.services.teacher_control import TeacherControlRegistry
from app.storage.process_lock import InterProcessMutex
import builtins
from unittest.mock import Mock


def test_teacher_lease_is_shared_between_worker_registries(tmp_path):
    state = tmp_path / "teacher-leases.json"
    worker_one = TeacherControlRegistry(state_path=state)
    worker_two = TeacherControlRegistry(state_path=state)

    claimed = worker_one.claim(
        "training-1", teacher_id=1, teacher_username="owner", sid="sid-1"
    )
    observed = worker_two.claim(
        "training-1", teacher_id=2, teacher_username="observer", sid="sid-2"
    )

    assert claimed["writable"] is True
    assert observed["writable"] is False
    assert observed["lease"]["ownerTeacherId"] == 1
    assert worker_two.authorize(
        "training-1", teacher_id=1, sid="sid-1"
    )["writable"] is True
    worker_one.clear()


def test_same_host_process_mutex_rejects_second_holder(tmp_path):
    first = InterProcessMutex(tmp_path / "behavior.lock")
    second = InterProcessMutex(tmp_path / "behavior.lock")
    assert first.acquire(blocking=False) is True
    try:
        assert second.acquire(blocking=False) is False
    finally:
        first.release()
    assert second.acquire(blocking=False) is True
    second.release()


def test_blocking_mutex_retries_transient_windows_style_open_error(
    tmp_path, monkeypatch
):
    real_open = builtins.open
    attempts = 0

    def flaky_open(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError(22, "Invalid argument", str(args[0]))
        return real_open(*args, **kwargs)

    monkeypatch.setattr(builtins, "open", flaky_open)
    mutex = InterProcessMutex(tmp_path / "transient.lock")

    assert mutex.acquire(blocking=True) is True
    assert attempts >= 2
    mutex.release()


def test_mutex_release_error_is_contained(tmp_path, monkeypatch):
    mutex = InterProcessMutex(tmp_path / "release.lock")
    assert mutex.acquire(blocking=True) is True
    handle = mutex._handle
    assert handle is not None
    monkeypatch.setattr(handle, "seek", Mock(side_effect=OSError(22, "Invalid argument")))

    mutex.release()

    assert mutex.held is False
