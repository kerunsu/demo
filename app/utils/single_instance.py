"""Cross-platform process lock for the backend entry point."""

from __future__ import annotations

import atexit
import os
from pathlib import Path
from typing import BinaryIO, Optional


class InstanceAlreadyRunning(RuntimeError):
    pass


class ProcessFileLock:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._file: Optional[BinaryIO] = None
        self._pid_path: Optional[Path] = None

    def acquire(self) -> "ProcessFileLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError) as exc:
            handle.close()
            raise InstanceAlreadyRunning(
                f"后端已经启动，请复用现有 8080 服务（锁文件: {self.path}）"
            ) from exc
        self._file = handle
        # 记录当前实例 PID 到独立文件（供 server.ps1 stop/status 定位进程）。
        # 注意不能写进锁文件本身：Windows 的 msvcrt 字节锁会拒绝其他进程
        # 读取被锁区域，锁文件在运行期间永远读不到内容。
        self._pid_path = self.path.with_name(self.path.name + ".pid")
        try:
            self._pid_path.write_text(str(os.getpid()), encoding="ascii")
        except OSError:
            pass  # 权限/只读介质等异常不应阻断服务启动
        atexit.register(self.release)
        return self

    def release(self) -> None:
        handle, self._file = self._file, None
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
        # 清理 PID 文件；进程被强杀时它会残留，stop 脚本会校验进程是否存在
        if self._pid_path is not None:
            try:
                self._pid_path.unlink(missing_ok=True)
            except OSError:
                pass

    def __enter__(self) -> "ProcessFileLock":
        return self.acquire()

    def __exit__(self, *_args) -> None:
        self.release()


def acquire_server_instance_lock(project_root: Path) -> ProcessFileLock:
    return ProcessFileLock(
        Path(project_root) / ".runtime" / "coordination" / "server_instance.lock"
    ).acquire()


__all__ = [
    "InstanceAlreadyRunning",
    "ProcessFileLock",
    "acquire_server_instance_lock",
]
