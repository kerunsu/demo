from pathlib import Path


class _Behavior:
    @staticmethod
    def get_training(_training_id):
        return None

    @staticmethod
    def get_summary(_training_id):
        return {"student_id": 2}


class _Store:
    def __init__(self, *, report=None, published=None):
        self.report = report
        self.published = published

    def get_report(self, _training_id):
        return dict(self.report) if self.report else None

    def save_report(self, _training_id, report):
        self.report = dict(report)

    def get_published_report(self, _training_id):
        return dict(self.published) if self.published else None


def _report(publication_status="pending_review"):
    return {
        "trainingSessionId": "training-review",
        "studentId": 2,
        "overall": 80,
        "status": "PARTIAL",
        "publicationStatus": publication_status,
    }


def test_repeated_generate_broadcasts_one_review_notification(monkeypatch):
    from app.report import service as report_service

    store = _Store()
    events = []
    service = report_service.ReportService()
    monkeypatch.setattr(report_service, "get_behavior_service", lambda: _Behavior())
    monkeypatch.setattr(report_service, "get_behavior_store", lambda: store)
    monkeypatch.setattr(service, "_build_report", lambda *_args, **_kwargs: _report())
    monkeypatch.setattr(report_service, "_emit", lambda event, payload: events.append((event, payload)))

    service.generate("training-review", auto_finalize=False)
    service.generate("training-review", auto_finalize=False)

    assert [event for event, _payload in events] == ["report_ready_for_review"]
    assert store.report["publicationStatus"] == "pending_review"


def test_generate_after_publish_stays_published_and_does_not_notify(monkeypatch):
    from app.report import service as report_service

    store = _Store(report=_report("published"), published=_report("published"))
    events = []
    service = report_service.ReportService()
    monkeypatch.setattr(report_service, "get_behavior_service", lambda: _Behavior())
    monkeypatch.setattr(report_service, "get_behavior_store", lambda: store)
    monkeypatch.setattr(service, "_build_report", lambda *_args, **_kwargs: _report())
    monkeypatch.setattr(report_service, "_emit", lambda event, payload: events.append((event, payload)))

    generated = service.generate("training-review", auto_finalize=False)

    assert generated["publicationStatus"] == "published"
    assert store.report["publicationStatus"] == "published"
    assert events == []


def test_report_review_frontends_do_not_regenerate_or_reopen_same_notice():
    root = Path(__file__).resolve().parents[1]
    teacher = (root / "teacher_frontend/components/ControlPage.tsx").read_text(encoding="utf-8")
    monitor = (root / "static/js/server_monitor.js").read_text(encoding="utf-8")

    interval_start = teacher.index("const t = window.setInterval(() => {")
    interval_end = teacher.index("return () => {", interval_start)
    interval = teacher[interval_start:interval_end]
    assert "probeReportStatus(id);" in interval
    assert "/generate" not in interval
    assert "probeReportStatus(id, true)" in teacher

    assert "if (state.reviewDismissed[id])" in monitor
    assert "state.reviewDismissed[id] = true;" in monitor
    assert "state.currentReviewId === id" in monitor

