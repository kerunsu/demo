import pytest

from tools.benchmark_class_start import (
    EventInbox,
    LiveClassStartBenchmark,
    RunResult,
    metric_summary,
    percentile,
    summarize_results,
)


class _FakeClient:
    connected = True

    def __init__(self, inbox, *, readiness_failed=False):
        self.inbox = inbox
        self.readiness_failed = readiness_failed

    def emit(self, event, payload):
        if event == "prepare_training":
            self.inbox.put("prepare_training_ack", {
                "success": True,
                "requestId": payload["requestId"],
                "trainingSessionId": "training-benchmark",
                "sessionId": "media-benchmark",
                "preflightMode": "legacy",
                "captureStarted": True,
                "childBound": True,
            })
        elif event == "readiness_start":
            self.inbox.put("readiness_start_ack", {
                "success": True,
                "snapshot": {"trainingSessionId": "training-benchmark"},
            })
            if self.readiness_failed:
                self.inbox.put("readiness_update", {
                    "trainingSessionId": "training-benchmark",
                    "status": "failed",
                    "anyFailed": True,
                    "detail": "camera unavailable",
                })
            else:
                self.inbox.put("readiness_complete", {
                    "trainingSessionId": "training-benchmark",
                    "status": "success",
                    "ok": True,
                    "elapsedMs": 500,
                })
        elif event == "finalize_training":
            self.inbox.put("finalize_training_ack", {
                "success": True,
                "requestId": payload["requestId"],
                "operationId": payload["operationId"],
                "trainingSessionId": payload["trainingSessionId"],
            })


def _benchmark(inbox, client):
    return LiveClassStartBenchmark(
        client=client,
        inbox=inbox,
        student_id=1,
        course_id=9,
        item_id=79,
        course_type="pairing",
        mode="assessment",
        timeout_seconds=5,
        cleanup_timeout_seconds=1,
        selection_delay_seconds=0,
        settle_seconds=0,
    )


def test_percentile_uses_linear_interpolation_for_ten_runs():
    values = list(range(100, 1100, 100))

    assert percentile(values, 0.50) == pytest.approx(550.0)
    assert percentile(values, 0.95) == pytest.approx(955.0)


def test_summary_excludes_failed_runs_from_latency_metrics():
    results = [
        RunResult(
            run=1,
            request_id="one",
            started_at="2026-01-01T00:00:00+08:00",
            success=True,
            prepare_ms=10,
            readiness_server_ms=500,
            readiness_e2e_ms=520,
            technical_total_ms=530,
            cleanup_success=True,
        ),
        RunResult(
            run=2,
            request_id="two",
            started_at="2026-01-01T00:00:01+08:00",
            success=False,
            training_session_id="training-two",
            prepare_ms=12,
            error="child_offline",
            cleanup_success=False,
        ),
    ]

    summary = summarize_results(results)

    assert summary["runs"] == 2
    assert summary["successes"] == 1
    assert summary["failures"] == 1
    assert summary["cleanupFailures"] == 1
    assert summary["prepareMs"] == metric_summary([10])
    assert summary["readinessServerMs"]["mean"] == 500


def test_event_inbox_keeps_unmatched_correlated_events():
    inbox = EventInbox()
    inbox.put("prepare_training_ack", {"requestId": "old"})
    inbox.put("prepare_training_ack", {"requestId": "current"})

    current = inbox.wait_any(
        ("prepare_training_ack",),
        lambda event: event.payload["requestId"] == "current",
        0.01,
    )
    old = inbox.wait_any(
        ("prepare_training_ack",),
        lambda event: event.payload["requestId"] == "old",
        0.01,
    )

    assert current.payload["requestId"] == "current"
    assert old.payload["requestId"] == "old"


def test_live_benchmark_correlates_success_and_finalizes_training():
    inbox = EventInbox()
    benchmark = _benchmark(inbox, _FakeClient(inbox))

    result = benchmark.run_once(1)

    assert result.success is True
    assert result.readiness_server_ms == 500
    assert result.technical_total_ms == pytest.approx(
        result.prepare_ms + result.readiness_e2e_ms
    )
    assert result.cleanup_success is True


def test_live_benchmark_reports_lowercase_readiness_failure_and_cleans_up():
    inbox = EventInbox()
    benchmark = _benchmark(inbox, _FakeClient(inbox, readiness_failed=True))

    result = benchmark.run_once(1)

    assert result.success is False
    assert result.error == "camera unavailable"
    assert result.cleanup_success is True
