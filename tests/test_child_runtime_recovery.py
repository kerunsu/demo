from __future__ import annotations

from pathlib import Path


def test_child_template_registers_presence_before_course_module():
    template = Path("templates/child.html").read_text(encoding="utf-8")

    bootstrap = 'window.startClientPresenceHeartbeat?.("child", 10000);'
    module = 'src="/static/js/child.js?v=20260826-child-surface-v2"'
    assert bootstrap in template
    assert module in template
    assert template.index(bootstrap) < template.index(module)
    assert 'window.socket?.on("connect_error"' in template


def test_child_uses_server_presence_without_robot_runtime_heartbeat():
    child = Path("static/js/child.js").read_text(encoding="utf-8")
    template = Path("templates/child.html").read_text(encoding="utf-8")

    assert 'socket.emit("client_presence", binding)' in child
    assert "startRuntimeChildPresence" not in child
    assert "/ui/child-presence" not in child
    assert "ROBOT_AGENT_BASE" not in child
    assert "ROBOT_AGENT_BASE" not in template

def test_demo_child_launcher_uses_kiosk_without_robot_runtime():
    browser_script = Path("scripts/Open-ChildLanMic.ps1").read_text(encoding="utf-8")
    child_script = Path("static/js/child.js").read_text(encoding="utf-8")

    assert "--new-window" in browser_script
    assert "--kiosk" in browser_script
    assert "--start-fullscreen" not in browser_script
    assert "/ui/child-presence" not in child_script
    assert "robot_motion_command" not in child_script


def test_packaged_child_watchdog_can_be_explicitly_disabled(monkeypatch):
    from robot_runtime import agent

    monkeypatch.setattr(agent.sys, "frozen", True, raising=False)
    monkeypatch.setenv("ROBOT_RUNTIME_AUTO_OPEN_CHILD", "0")
    with agent._child_page_watchdog_lock:
        agent._child_page_watchdog_started = False

    assert agent.start_child_page_watchdog() is False


def test_online_update_restart_restores_child_without_expression_page(tmp_path, monkeypatch):
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
    assert "'/ui/open-emotion'" not in script
    assert script.index("'/health'") < script.index("'/ui/open-child'")
