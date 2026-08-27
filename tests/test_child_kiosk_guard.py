"""Child touch surface stays inside the course while preserving task clicks."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_child_page_loads_input_guard_before_runtime_and_sandboxes_courses():
    template = (ROOT / "templates/child.html").read_text(encoding="utf-8")
    assert "maximum-scale=1.0, user-scalable=no" in template
    assert template.index("child_kiosk_guard.js") < template.index("child.js?")
    assert template.count('sandbox="allow-scripts allow-same-origin"') == 2
    assert template.count('allow="autoplay"') == 2
    assert "disablepictureinpicture" in template


def test_child_input_guard_blocks_native_navigation_but_keeps_course_scroller():
    guard = (ROOT / "static/js/child_kiosk_guard.js").read_text(encoding="utf-8")
    styles = (ROOT / "static/css/child.css").read_text(encoding="utf-8")
    for event_name in (
        "contextmenu", "auxclick", "dragstart", "selectstart",
        "touchstart", "touchmove", "gesturestart", "keydown",
    ):
        assert f'"{event_name}"' in guard
    assert 'a[href],area[href]' in guard
    assert 'window.open = () => null' in guard
    assert '.options-zone' in guard
    assert "touch-action: pan-x" in guard
    assert "overscroll-behavior: none" in styles


def test_demo_child_launcher_uses_kiosk_profile_without_runtime_package():
    source = (ROOT / "scripts/Open-ChildLanMic.ps1").read_text(encoding="utf-8")
    assert '"--kiosk"' in source
    assert '"--disable-pinch"' in source
    assert '"--overscroll-history-navigation=0"' in source
    assert "robot_runtime" not in source.lower()
    assert not (ROOT / "scripts/pack_robot_release.ps1").exists()
    assert not (ROOT / "doll/DollSer").exists()
