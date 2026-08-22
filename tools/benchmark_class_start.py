"""Benchmark the live ``prepare_training -> readiness`` class-start path.

This command acts only as the teacher client.  Keep exactly one real child
page open with camera permission so the normal browser capture path supplies
the first video frame.  The command does not fake a camera, bypass readiness,
or require a robot.

Example, from the repository root::

    .venv/bin/python tools/benchmark_class_start.py \
        --student-id 1 --course-id 9 --item-id 79 \
        --course-type pairing --runs 10

The teacher password is read with ``getpass`` unless
``MAIMAI_BENCH_PASSWORD`` is set.  Each iteration creates a real local
recording/training artifact and finalizes it; artifacts are deliberately not
deleted by this diagnostic tool.
"""
from __future__ import annotations

import argparse
import getpass
import json
import math
import os
import statistics
import sys
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence
from urllib.parse import urljoin, urlparse

import requests
import socketio


EVENT_NAMES = (
    "prepare_training_ack",
    "readiness_start_ack",
    "readiness_update",
    "readiness_complete",
    "finalize_training_ack",
)


@dataclass
class ReceivedEvent:
    name: str
    payload: Dict[str, Any]
    received_ns: int


class EventInbox:
    """Thread-safe correlated event inbox for python-socketio callbacks."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._events: Dict[str, List[ReceivedEvent]] = defaultdict(list)

    def put(self, name: str, payload: Any) -> None:
        normalized = payload if isinstance(payload, dict) else {"value": payload}
        event = ReceivedEvent(name, dict(normalized), time.monotonic_ns())
        with self._condition:
            self._events[name].append(event)
            self._condition.notify_all()

    def clear(self, *names: str) -> None:
        with self._condition:
            for name in names:
                self._events.pop(name, None)

    def wait_any(
        self,
        names: Iterable[str],
        predicate: Callable[[ReceivedEvent], bool],
        timeout_seconds: float,
    ) -> ReceivedEvent:
        selected_names = tuple(names)
        deadline = time.monotonic() + timeout_seconds
        with self._condition:
            while True:
                for name in selected_names:
                    queue = self._events.get(name, [])
                    for index, event in enumerate(queue):
                        if predicate(event):
                            return queue.pop(index)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"等待事件超时: {', '.join(selected_names)}"
                    )
                self._condition.wait(remaining)


@dataclass
class RunResult:
    run: int
    request_id: str
    started_at: str
    success: bool = False
    training_session_id: Optional[str] = None
    media_session_id: Optional[str] = None
    prepare_ms: Optional[float] = None
    readiness_e2e_ms: Optional[float] = None
    readiness_server_ms: Optional[float] = None
    technical_total_ms: Optional[float] = None
    preflight_mode: Optional[str] = None
    capture_started_during_prepare: Optional[bool] = None
    child_bound: Optional[bool] = None
    cleanup_success: bool = False
    cleanup_ms: Optional[float] = None
    error: Optional[str] = None
    cleanup_error: Optional[str] = None


def percentile(values: Sequence[float], quantile: float) -> Optional[float]:
    """Return a linearly interpolated percentile, including small samples."""

    if not values:
        return None
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile 必须位于 0 到 1")
    ordered = sorted(float(value) for value in values)
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def metric_summary(values: Sequence[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {
            "count": 0,
            "min": None,
            "mean": None,
            "p50": None,
            "p95": None,
            "max": None,
        }
    normalized = [float(value) for value in values]
    return {
        "count": len(normalized),
        "min": min(normalized),
        "mean": statistics.fmean(normalized),
        "p50": percentile(normalized, 0.50),
        "p95": percentile(normalized, 0.95),
        "max": max(normalized),
    }


def summarize_results(results: Sequence[RunResult]) -> Dict[str, Any]:
    successful = [result for result in results if result.success]

    def values(field: str) -> List[float]:
        return [
            float(value)
            for result in successful
            if (value := getattr(result, field)) is not None
        ]

    return {
        "runs": len(results),
        "successes": len(successful),
        "failures": len(results) - len(successful),
        "cleanupFailures": sum(
            bool(result.training_session_id) and not result.cleanup_success
            for result in results
        ),
        "prepareMs": metric_summary(values("prepare_ms")),
        "readinessServerMs": metric_summary(values("readiness_server_ms")),
        "readinessE2eMs": metric_summary(values("readiness_e2e_ms")),
        "technicalTotalMs": metric_summary(values("technical_total_ms")),
    }


def _milliseconds(start_ns: int, end_ns: int) -> float:
    return (end_ns - start_ns) / 1_000_000.0


def _event_matches_request(event: ReceivedEvent, request_id: str) -> bool:
    return str(event.payload.get("requestId") or "") == request_id


def _event_matches_training(event: ReceivedEvent, training_id: str) -> bool:
    payload = event.payload
    snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
    candidate = (
        payload.get("trainingSessionId")
        or payload.get("training_session_id")
        or snapshot.get("trainingSessionId")
    )
    return str(candidate or "") == str(training_id)


class LiveClassStartBenchmark:
    def __init__(
        self,
        *,
        client: socketio.Client,
        inbox: EventInbox,
        student_id: int,
        course_id: int,
        item_id: int,
        course_type: str,
        mode: str,
        timeout_seconds: float,
        cleanup_timeout_seconds: float,
        selection_delay_seconds: float,
        settle_seconds: float,
    ) -> None:
        self.client = client
        self.inbox = inbox
        self.student_id = student_id
        self.course_id = course_id
        self.item_id = item_id
        self.course_type = course_type
        self.mode = mode
        self.timeout_seconds = timeout_seconds
        self.cleanup_timeout_seconds = cleanup_timeout_seconds
        self.selection_delay_seconds = selection_delay_seconds
        self.settle_seconds = settle_seconds

    def _finalize(self, result: RunResult) -> None:
        training_id = result.training_session_id
        if not training_id or not self.client.connected:
            result.cleanup_error = "缺少训练会话或 Socket 已断开"
            return
        operation_id = f"benchmark-finalize-{uuid.uuid4()}"
        self.inbox.clear("finalize_training_ack")
        started_ns = time.monotonic_ns()
        self.client.emit(
            "finalize_training",
            {
                "studentId": self.student_id,
                "trainingSessionId": training_id,
                "requestId": operation_id,
                "operationId": operation_id,
            },
        )
        try:
            event = self.inbox.wait_any(
                ("finalize_training_ack",),
                lambda item: _event_matches_request(item, operation_id),
                self.cleanup_timeout_seconds,
            )
            result.cleanup_ms = _milliseconds(started_ns, event.received_ns)
            result.cleanup_success = event.payload.get("success") is True
            if not result.cleanup_success:
                result.cleanup_error = str(
                    event.payload.get("error") or "finalize_training 失败"
                )
        except TimeoutError as exc:
            result.cleanup_error = str(exc)

    def run_once(self, run_number: int) -> RunResult:
        request_id = f"benchmark-prepare-{run_number}-{uuid.uuid4()}"
        result = RunResult(
            run=run_number,
            request_id=request_id,
            started_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        prepare_started_ns = time.monotonic_ns()
        try:
            self.inbox.clear(*EVENT_NAMES)
            self.client.emit(
                "prepare_training",
                {
                    "studentId": self.student_id,
                    "mode": self.mode,
                    "requestId": request_id,
                    "operationId": request_id,
                    "preflightMode": "auto",
                },
            )
            prepare = self.inbox.wait_any(
                ("prepare_training_ack",),
                lambda event: _event_matches_request(event, request_id),
                self.timeout_seconds,
            )
            result.prepare_ms = _milliseconds(prepare_started_ns, prepare.received_ns)
            if prepare.payload.get("success") is not True:
                raise RuntimeError(
                    str(prepare.payload.get("error") or "prepare_training 失败")
                )

            result.training_session_id = str(
                prepare.payload.get("trainingSessionId") or ""
            ) or None
            result.media_session_id = str(
                prepare.payload.get("sessionId") or ""
            ) or None
            result.preflight_mode = prepare.payload.get("preflightMode")
            result.capture_started_during_prepare = prepare.payload.get("captureStarted")
            result.child_bound = prepare.payload.get("childBound")
            if not result.training_session_id or not result.media_session_id:
                raise RuntimeError("prepare_training_ack 缺少训练或媒体会话标识")
            if result.child_bound is False:
                reason = prepare.payload.get("childBindingError") or "child_offline"
                raise RuntimeError(f"儿童端未绑定: {reason}")

            if self.selection_delay_seconds > 0:
                time.sleep(self.selection_delay_seconds)

            training_id = result.training_session_id
            self.inbox.clear(
                "readiness_start_ack",
                "readiness_update",
                "readiness_complete",
            )
            readiness_started_ns = time.monotonic_ns()
            self.client.emit(
                "readiness_start",
                {
                    "studentId": self.student_id,
                    "trainingSessionId": training_id,
                    "items": [
                        {
                            "courseId": self.course_id,
                            "itemId": self.item_id,
                            "courseType": self.course_type,
                        }
                    ],
                    "timeoutMs": int(self.timeout_seconds * 1000),
                },
            )
            readiness_ack = self.inbox.wait_any(
                ("readiness_start_ack",),
                lambda _event: True,
                self.timeout_seconds,
            )
            if readiness_ack.payload.get("success") is not True:
                raise RuntimeError(
                    str(
                        readiness_ack.payload.get("error")
                        or "readiness_start 失败"
                    )
                )

            while True:
                elapsed_seconds = (time.monotonic_ns() - readiness_started_ns) / 1_000_000_000
                remaining = self.timeout_seconds - elapsed_seconds
                if remaining <= 0:
                    raise TimeoutError("等待 readiness_complete 超时")
                readiness = self.inbox.wait_any(
                    ("readiness_complete", "readiness_update"),
                    lambda event: _event_matches_training(event, training_id),
                    remaining,
                )
                status = str(readiness.payload.get("status") or "").upper()
                if status == "FAILED" or readiness.payload.get("anyFailed") is True:
                    raise RuntimeError(
                        str(
                            readiness.payload.get("detail")
                            or readiness.payload.get("error")
                            or "readiness 失败"
                        )
                    )
                if readiness.name != "readiness_complete":
                    continue
                if readiness.payload.get("ok") is not True:
                    raise RuntimeError(
                        str(readiness.payload.get("error") or "readiness 未确认")
                    )
                result.readiness_e2e_ms = _milliseconds(
                    readiness_started_ns, readiness.received_ns
                )
                server_elapsed = readiness.payload.get("elapsedMs")
                if isinstance(server_elapsed, (int, float)):
                    result.readiness_server_ms = float(server_elapsed)
                # Adding the two measured system segments excludes all time
                # between prepare ack and readiness emit, including both the
                # configured selection delay and any scheduler/user overhead.
                result.technical_total_ms = (
                    float(result.prepare_ms) + float(result.readiness_e2e_ms)
                )
                result.success = True
                break
        except (RuntimeError, TimeoutError) as exc:
            result.error = str(exc)
        except Exception as exc:  # pragma: no cover - protects live cleanup
            result.error = f"{type(exc).__name__}: {exc}"
        finally:
            if result.training_session_id:
                self._finalize(result)
            if self.settle_seconds > 0:
                time.sleep(self.settle_seconds)
        return result


def _local_url(value: str, allow_remote: bool) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise argparse.ArgumentTypeError("base-url 必须是完整的 http(s) URL")
    local_hosts = {"127.0.0.1", "localhost", "::1"}
    if not allow_remote and parsed.hostname.lower() not in local_hosts:
        raise argparse.ArgumentTypeError(
            "默认只允许本机 URL；确需远端服务时增加 --allow-remote"
        )
    return value.rstrip("/")


def _runtime_modes(session: requests.Session, base_url: str) -> Dict[str, Any]:
    try:
        response = session.get(
            urljoin(f"{base_url}/", "api/server/runtime-modes"), timeout=5
        )
        if response.ok:
            payload = response.json()
            if isinstance(payload, dict):
                return payload
    except (requests.RequestException, ValueError):
        pass
    return {}


def _login(
    session: requests.Session,
    base_url: str,
    username: str,
    password: str,
) -> Dict[str, Any]:
    response = session.post(
        urljoin(f"{base_url}/", "api/teacher/login"),
        json={"username": username, "password": password},
        timeout=10,
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if not response.ok or payload.get("success") is not True:
        raise RuntimeError(
            str(payload.get("error") or f"教师登录失败: HTTP {response.status_code}")
        )
    return payload


def _format_number(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.1f}"


def _print_run(result: RunResult) -> None:
    status = "成功" if result.success else "失败"
    print(
        f"[{result.run:02d}] {status} "
        f"prepare={_format_number(result.prepare_ms)}ms "
        f"readiness(server/e2e)="
        f"{_format_number(result.readiness_server_ms)}/"
        f"{_format_number(result.readiness_e2e_ms)}ms "
        f"total={_format_number(result.technical_total_ms)}ms "
        f"cleanup={'ok' if result.cleanup_success else 'failed'}"
    )
    if result.error:
        print(f"     error: {result.error}")
    if result.cleanup_error:
        print(f"     cleanup: {result.cleanup_error}")


def _print_metric(label: str, data: Dict[str, Optional[float]]) -> None:
    print(
        f"{label}: n={data['count']} "
        f"min={_format_number(data['min'])}ms "
        f"mean={_format_number(data['mean'])}ms "
        f"P50={_format_number(data['p50'])}ms "
        f"P95={_format_number(data['p95'])}ms "
        f"max={_format_number(data['max'])}ms"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "使用真实儿童端摄像头连续评估 prepare_training/readiness 开课耗时"
        )
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--username", default=os.getenv("MAIMAI_BENCH_USERNAME"))
    parser.add_argument("--student-id", type=int, required=True)
    parser.add_argument("--course-id", type=int, required=True)
    parser.add_argument("--item-id", type=int, required=True)
    parser.add_argument("--course-type", required=True)
    parser.add_argument("--mode", choices=("assessment", "training"), default="assessment")
    parser.add_argument("--runs", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=float, default=35.0)
    parser.add_argument("--cleanup-timeout-seconds", type=float, default=15.0)
    parser.add_argument(
        "--selection-delay-ms",
        type=float,
        default=0.0,
        help="模拟人工选课停留；该时间不计入 technical total",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=1.0,
        help="每轮 finalize 后等待儿童端释放摄像头的时间",
    )
    parser.add_argument(
        "--transport",
        choices=("auto", "polling", "websocket"),
        default="auto",
        help="Socket.IO 传输；auto 会使用环境可用的最佳传输",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="在文字汇总后额外输出机器可读 JSON",
    )
    return parser


def _validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.runs <= 0:
        parser.error("--runs 必须大于 0")
    if args.timeout_seconds < 5:
        parser.error("--timeout-seconds 不能小于 5")
    if args.cleanup_timeout_seconds <= 0:
        parser.error("--cleanup-timeout-seconds 必须大于 0")
    if args.selection_delay_ms < 0:
        parser.error("--selection-delay-ms 不能为负数")
    if args.settle_seconds < 0:
        parser.error("--settle-seconds 不能为负数")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _validate_args(parser, args)
    try:
        base_url = _local_url(args.base_url, args.allow_remote)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))

    username = args.username or input("教师用户名: ").strip()
    password = os.getenv("MAIMAI_BENCH_PASSWORD") or getpass.getpass("教师密码: ")
    if not username or not password:
        print("教师用户名和密码不能为空", file=sys.stderr)
        return 2

    http = requests.Session()
    try:
        login = _login(http, base_url, username, password)
    except (requests.RequestException, RuntimeError) as exc:
        print(f"无法开始评估: {exc}", file=sys.stderr)
        return 2

    inbox = EventInbox()
    client = socketio.Client(
        http_session=http,
        reconnection=False,
        logger=False,
        engineio_logger=False,
    )
    for event_name in EVENT_NAMES:
        def handler(payload: Any = None, name: str = event_name) -> None:
            inbox.put(name, payload)

        client.on(event_name, handler=handler)

    modes = _runtime_modes(http, base_url)
    connect_options: Dict[str, Any] = {"wait_timeout": 10}
    if args.transport != "auto":
        connect_options["transports"] = [args.transport]
    try:
        client.connect(base_url, **connect_options)
    except Exception as exc:
        print(f"Socket.IO 连接失败: {exc}", file=sys.stderr)
        return 2

    teacher = login.get("teacher") if isinstance(login.get("teacher"), dict) else {}
    actual_transport = client.transport() if client.connected else "unknown"
    print("开课性能评估")
    print(
        "条件: "
        f"base={base_url} transport={actual_transport} "
        f"child={modes.get('childMediaMode', 'unknown')} "
        f"robot={modes.get('robotControlMode', 'unknown')} "
        f"teacher={teacher.get('username', username)} "
        f"student={args.student_id} mode={args.mode} "
        f"item={args.course_id}/{args.item_id}/{args.course_type}"
    )
    print(
        "口径: technical total = prepare RTT + readiness E2E，"
        "不含 selection delay；每轮会创建并 finalize 真实本地录制。"
    )

    benchmark = LiveClassStartBenchmark(
        client=client,
        inbox=inbox,
        student_id=args.student_id,
        course_id=args.course_id,
        item_id=args.item_id,
        course_type=args.course_type,
        mode=args.mode,
        timeout_seconds=args.timeout_seconds,
        cleanup_timeout_seconds=args.cleanup_timeout_seconds,
        selection_delay_seconds=args.selection_delay_ms / 1000.0,
        settle_seconds=args.settle_seconds,
    )
    results: List[RunResult] = []
    try:
        for run_number in range(1, args.runs + 1):
            if not client.connected:
                result = RunResult(
                    run=run_number,
                    request_id="",
                    started_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                    error="Socket.IO 已断开",
                )
            else:
                result = benchmark.run_once(run_number)
            results.append(result)
            _print_run(result)
            if not client.connected:
                break
    except KeyboardInterrupt:
        print("\n收到中断，当前轮已尽力正常收尾。", file=sys.stderr)
    finally:
        if client.connected:
            client.disconnect()

    summary = summarize_results(results)
    print("\n汇总")
    print(
        f"次数={summary['runs']} 成功={summary['successes']} "
        f"失败={summary['failures']} 清理失败={summary['cleanupFailures']}"
    )
    _print_metric("prepare RTT", summary["prepareMs"])
    _print_metric("readiness server", summary["readinessServerMs"])
    _print_metric("readiness E2E", summary["readinessE2eMs"])
    _print_metric("technical total", summary["technicalTotalMs"])

    if args.json:
        print(
            json.dumps(
                {
                    "conditions": {
                        "baseUrl": base_url,
                        "transport": actual_transport,
                        "runtimeModes": modes,
                        "studentId": args.student_id,
                        "courseId": args.course_id,
                        "itemId": args.item_id,
                        "courseType": args.course_type,
                        "mode": args.mode,
                        "selectionDelayMs": args.selection_delay_ms,
                    },
                    "runs": [asdict(result) for result in results],
                    "summary": summary,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0 if summary["failures"] == 0 and summary["cleanupFailures"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
