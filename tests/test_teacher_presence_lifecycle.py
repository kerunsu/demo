from pathlib import Path


def test_teacher_presence_starts_after_login_not_after_prepare():
    source = (
        Path(__file__).resolve().parents[1] / "teacher_frontend/App.tsx"
    ).read_text(encoding="utf-8")
    assert "prepareSocketRef.current = ensureTeacherSocket(prepareSocketRef.current)" in source
    assert "if (currentPage === 'control')" in source
    assert "disposeTeacherSocket(prepareSocketRef.current)" in source
    assert "Keep exactly one teacher connection" in source


def test_control_page_has_reliable_page_exit_finalization():
    root = Path(__file__).resolve().parents[1]
    source = (root / "teacher_frontend/components/ControlPage.tsx").read_text(
        encoding="utf-8"
    )
    server = (root / "app.py").read_text(encoding="utf-8")

    assert "window.addEventListener('pagehide', finalizeOnPageExit)" in source
    assert "navigator.sendBeacon" in source
    assert "/api/training/finalize-beacon" in source
    assert '@app.route("/api/training/finalize-beacon", methods=["POST"])' in server
