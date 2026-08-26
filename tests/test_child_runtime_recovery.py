from __future__ import annotations

from pathlib import Path


def test_child_template_registers_presence_before_course_module():
    template = Path("templates/child.html").read_text(encoding="utf-8")

    bootstrap = 'window.startClientPresenceHeartbeat?.("child", 10000);'
    module = 'src="/static/js/child.js?v=20260824-screen-click-v1"'
    assert bootstrap in template
    assert module in template
    assert template.index(bootstrap) < template.index(module)
    assert 'window.socket?.on("connect_error"' in template


def test_runtime_child_presence_is_real_heartbeat_not_process_launch():
    from robot_runtime import agent

    with agent._child_page_lock:
        agent._child_page_state.update({
            "pageId": None,
            "url": None,
            "visible": None,
            "active": False,
            "lastSeenAt": 0,
            "lastLaunchAt": 123,
            "lastLaunchOk": True,
            "lastLaunchMode": "lan_mic_script",
            "lastLaunchError": None,
            "launchAttempts": 1,
        })

    before = agent.child_page_presence_status(now_ms=1000)
    assert before["lastLaunchOk"] is True
    assert before["online"] is False

    response = agent.app.test_client().post(
        "/ui/child-presence",
        json={
            "pageId": "child-browser-1",
            "url": "http://server:8080/child",
            "visible": True,
            "active": True,
        },
    )
    body = response.get_json()
    assert response.status_code == 200
    assert body["online"] is True
    assert agent.state.status()["childPageOnline"] is True

    stale = agent.child_page_presence_status(
        now_ms=int(body["lastSeenAt"]) + int(body["ttlMs"]) + 1
    )
    assert stale["online"] is False


def test_packaged_launcher_requires_child_heartbeat_and_visible_retry():
    launcher = Path("robot_runtime/packaging/start_robot_runtime.ps1").read_text(
        encoding="utf-8"
    )
    browser_script = Path("scripts/Open-ChildLanMic.ps1").read_text(encoding="utf-8")
    child_script = Path("static/js/child.js").read_text(encoding="utf-8")

    assert "function Wait-ChildPage" in launcher
    assert "$State.childPage.online" in launcher
    assert "forcing one visible retry" in launcher
    assert "--new-window" in browser_script
    assert "--start-fullscreen" in browser_script
    assert "/ui/child-presence" in child_script
    assert "startRuntimeChildPresence();" in child_script


def test_packaged_child_watchdog_can_be_explicitly_disabled(monkeypatch):
    from robot_runtime import agent

    monkeypatch.setattr(agent.sys, "frozen", True, raising=False)
    monkeypatch.setenv("ROBOT_RUNTIME_AUTO_OPEN_CHILD", "0")
    with agent._child_page_watchdog_lock:
        agent._child_page_watchdog_started = False

    assert agent.start_child_page_watchdog() is False


def test_online_update_restart_restores_child_and_emotion_pages(tmp_path, monkeypatch):
    from robot_runtime import updater

    prepared_exe = tmp_path / "new" / "RobotRuntime.exe"
    prepared_exe.parent.mkdir(parents=True)
    prepared_exe.write_bytes(b"MZ" + b"\0" * 2048)
    config_dir = tmp_path / "config"

    monkeypatch.setattr(updater, "is_frozen", lambda: True)
    monkeypatch.setattr(updater.register_client, "config_dir", lambda: config_dir)
    monkeypatch.setattr(updater.subprocess, "Popen", lambda **_kwargs: object())

    result = updater.launch_swap_and_exit({
        "exePath": str(prepared_exe),
        "sidecars": {},
    })

    assert result["ok"] is True
    script = Path(result["scriptPath"]).read_text(encoding="utf-8-sig")
    assert "'/health'" in script
    assert "'/ui/open-child'" in script
    assert "'/ui/open-emotion'" in script
    assert script.index("'/health'") < script.index("'/ui/open-child'")
