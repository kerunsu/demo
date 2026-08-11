from __future__ import annotations

import pytest

from app.utils.single_instance import InstanceAlreadyRunning, ProcessFileLock


def test_process_file_lock_rejects_second_backend(tmp_path):
    path = tmp_path / "server.lock"
    first = ProcessFileLock(path).acquire()
    try:
        with pytest.raises(InstanceAlreadyRunning):
            ProcessFileLock(path).acquire()
    finally:
        first.release()

    second = ProcessFileLock(path).acquire()
    second.release()
