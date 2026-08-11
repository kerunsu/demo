"""Small same-host inter-process mutex used by multi-worker coordinators."""
from __future__ import annotations

import os
from pathlib import Path
import time
from typing import BinaryIO, Optional


class InterProcessMutex:
    def __init__(self, path: Path):
        # Resolve once.  A relative coordination path must not silently move if
        # a launcher or third-party library changes the process working
        # directory after application import.
        self.path = Path(path).resolve()
        self._handle: Optional[BinaryIO] = None

    @property
    def held(self) -> bool:
        return self._handle is not None

    def acquire(self, blocking: bool = False) -> bool:
        if self._handle is not None:
            return True
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Windows may transiently report EINVAL while a previous handle is
        # being closed.  A short bounded retry prevents that OS detail from
        # aborting an otherwise valid teacher action.
        attempts = 3 if blocking else 1
        for attempt in range(attempts):
            handle: Optional[BinaryIO] = None
            try:
                handle = open(self.path, "a+b")
                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                    os.fsync(handle.fileno())
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
                    msvcrt.locking(handle.fileno(), mode, 1)
                else:
                    import fcntl

                    flags = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
                    fcntl.flock(handle.fileno(), flags)
            except (OSError, BlockingIOError):
                if handle is not None:
                    try:
                        handle.close()
                    except OSError:
                        pass
                if attempt + 1 < attempts:
                    time.sleep(0.05 * (attempt + 1))
                continue
            self._handle = handle
            return True
        return False

    def release(self) -> None:
        handle, self._handle = self._handle, None
        if handle is None:
            return
        try:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                # Closing the descriptor releases any remaining OS lock.  An
                # unlock race must never turn a successful business operation
                # into an error returned to the browser.
                pass
        finally:
            try:
                handle.close()
            except OSError:
                pass

    def __enter__(self):
        if not self.acquire(blocking=True):
            raise RuntimeError("inter_process_lock_unavailable")
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.release()
