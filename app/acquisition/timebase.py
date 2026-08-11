"""跨浏览器、Server、Runtime 的单调时间归一化。"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class TimebaseSample:
    monotonic_ns: int
    relative_ms: float
    wall_time_iso: Optional[str] = None
    source_unit: str = "ns"


class TimebaseMapper:
    """把不同来源时间映射到同一场 media session 的相对毫秒。

    输入单位必须显式给出，输出单调不倒退；当设备时钟回拨时保留样本但将
    relative_ms 夹到上一个值，并记录 correction_count，便于后续质量分析。
    """

    def __init__(self, *, session_start_ns: int = 0) -> None:
        self.session_start_ns = int(session_start_ns)
        self._last_ns = self.session_start_ns
        self._last_relative_ms = 0.0
        self._correction_count = 0
        self._lock = threading.RLock()

    @property
    def correction_count(self) -> int:
        with self._lock:
            return self._correction_count

    def normalize(
        self,
        value: int | float,
        *,
        unit: str,
        wall_time_iso: Optional[str] = None,
    ) -> TimebaseSample:
        unit = unit.lower().strip()
        if unit in {"ns", "nanosecond", "nanoseconds"}:
            ns = int(value)
        elif unit in {"ms", "millisecond", "milliseconds"}:
            ns = int(float(value) * 1_000_000)
        elif unit in {"s", "sec", "second", "seconds"}:
            ns = int(float(value) * 1_000_000_000)
        else:
            raise ValueError(f"unsupported_time_unit:{unit}")

        with self._lock:
            if ns < self._last_ns:
                self._correction_count += 1
                ns = self._last_ns
            self._last_ns = ns
            relative_ms = max(0.0, (ns - self.session_start_ns) / 1_000_000.0)
            if relative_ms < self._last_relative_ms:
                self._correction_count += 1
                relative_ms = self._last_relative_ms
            self._last_relative_ms = relative_ms
            return TimebaseSample(
                monotonic_ns=ns,
                relative_ms=relative_ms,
                wall_time_iso=wall_time_iso,
                source_unit=unit,
            )
