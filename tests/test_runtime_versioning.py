from __future__ import annotations

from pathlib import Path

from app.acquisition.device_preflight_runtime import perform_device_preflight
from app.robot import runtime_registry
from app.versioning import runtime_protocol_compatibility


def test_runtime_protocol_compatibility_is_explicit():
    assert runtime_protocol_compatibility("1")["compatible"] is True
    assert runtime_protocol_compatibility(None) == {
        "protocolVersion": None,
        "compatible": False,
        "compatibilityReason": "runtime_protocol_missing",
        "minRuntimeProtocolVersion": "1",
        "maxRuntimeProtocolVersion": "1",
    }
    assert runtime_protocol_compatibility("0")["compatibilityReason"] == "runtime_protocol_too_old"
    assert runtime_protocol_compatibility("2")["compatibilityReason"] == "runtime_protocol_too_new"


def test_runtime_registry_exposes_build_protocol_and_version_matrix(monkeypatch):
    monkeypatch.setattr(runtime_registry, "_runtimes", {})
    record = runtime_registry.register_runtime(
        "http://runtime.invalid:19091",
        capabilities=["device-preflight-v1"],
        meta={"buildVersion": "runtime-build-1", "protocolVersion": "1"},
    )
    assert record["buildVersion"] == "runtime-build-1"
    assert record["compatible"] is True

    status = runtime_registry.get_runtime_status()
    assert status["primary"]["protocolVersion"] == "1"
    assert status["versionMatrix"]["runtime"]["buildVersion"] == "runtime-build-1"
    assert status["versionMatrix"]["server"]["minRuntimeProtocolVersion"] == "1"
    assert status["versionMatrix"]["frontend"]["buildVersion"]


def test_legacy_runtime_is_online_but_preflight_requires_upgrade(monkeypatch):
    monkeypatch.setattr(runtime_registry, "_runtimes", {})
    legacy = runtime_registry.register_runtime(
        "http://legacy.invalid:19091",
        capabilities=["device-preflight-v1", "multi-track-media-v1"],
        meta={"buildVersion": "legacy-build"},
    )
    assert legacy["online"] is True
    assert legacy["compatible"] is False

    class Registry:
        @staticmethod
        def list_devices():
            return []

    result = perform_device_preflight(Registry(), runtime_registry.get_runtime_status())
    assert result["ok"] is False
    assert result["error"] == "robot_runtime_upgrade_required"
    assert {item["error"] for item in result["checks"]} == {
        "robot_runtime_upgrade_required"
    }


def test_registry_prefers_compatible_sync_runtime_over_newer_legacy_heartbeat(monkeypatch):
    monkeypatch.setattr(runtime_registry, "_runtimes", {})
    monkeypatch.setattr(runtime_registry, "_preferred_runtime_id", None)
    monkeypatch.setattr(runtime_registry, "_preferred_runtime_source", None)
    compatible = runtime_registry.register_runtime(
        "http://compatible.invalid:19091",
        capabilities=[
            "behavior-sync-v1",
            "device-preflight-v1",
            "multi-track-media-v1",
        ],
        meta={"buildVersion": "new-build", "protocolVersion": "1"},
    )
    legacy = runtime_registry.register_runtime(
        "http://legacy.invalid:19091",
        capabilities=["device-preflight-v1", "multi-track-media-v1"],
        meta={"buildVersion": "old-build"},
    )
    assert legacy["lastSeenMs"] >= compatible["lastSeenMs"]

    primary = runtime_registry.get_primary_runtime()
    assert primary["advertisedUrl"] == "http://compatible.invalid:19091"
    assert primary["compatible"] is True


def test_child_runtime_preference_survives_other_runtime_heartbeats(monkeypatch):
    monkeypatch.setattr(runtime_registry, "_runtimes", {})
    monkeypatch.setattr(runtime_registry, "_preferred_runtime_id", None)
    monkeypatch.setattr(runtime_registry, "_preferred_runtime_source", None)
    child_url = "http://192.168.1.105:19091"
    other_url = "http://192.168.1.106:19091"
    runtime_registry.register_runtime(
        child_url,
        capabilities=["behavior-sync-v1"],
        meta={"protocolVersion": "1"},
    )
    runtime_registry.register_runtime(
        other_url,
        capabilities=["behavior-sync-v1"],
        meta={"protocolVersion": "1"},
    )

    assert runtime_registry.prefer_runtime(child_url, source="child_socket:test")
    assert runtime_registry.heartbeat_runtime(other_url)
    assert runtime_registry.get_primary_runtime()["advertisedUrl"] == child_url
    status = runtime_registry.get_runtime_status()
    assert status["preferredRuntimeId"] == child_url
    assert status["preferredRuntimeSource"] == "child_socket:test"


def test_legacy_heartbeat_never_refreshes_multiple_runtime_records(monkeypatch):
    monkeypatch.setattr(runtime_registry, "_runtimes", {})
    first = runtime_registry.register_runtime(
        "http://192.168.1.105:19091",
        meta={"protocolVersion": "1"},
    )
    second = runtime_registry.register_runtime(
        "http://192.168.1.106:19091",
        meta={"protocolVersion": "1"},
    )
    before = {
        first["id"]: runtime_registry._runtimes[first["id"]]["lastSeenMs"],
        second["id"]: runtime_registry._runtimes[second["id"]]["lastSeenMs"],
    }

    assert runtime_registry.heartbeat_runtime(None) is False
    assert {
        runtime_id: record["lastSeenMs"]
        for runtime_id, record in runtime_registry._runtimes.items()
    } == before


def test_same_runtime_instance_replaces_old_endpoint(monkeypatch):
    monkeypatch.setattr(runtime_registry, "_runtimes", {})
    runtime_registry.register_runtime(
        "http://192.168.1.105:19091",
        meta={"protocolVersion": "1", "instanceId": "physical-1"},
    )
    runtime_registry.register_runtime(
        "http://192.168.1.106:19092",
        meta={"protocolVersion": "1", "instanceId": "physical-1"},
    )
    status = runtime_registry.get_runtime_status()
    assert status["onlineCount"] == 1
    assert [item["advertisedUrl"] for item in status["runtimes"]] == [
        "http://192.168.1.106:19092"
    ]


def test_packaged_launcher_waits_for_ready_and_has_a_mutex():
    root = Path(__file__).resolve().parents[1]
    launcher = (root / "robot_runtime" / "packaging" / "start_robot_runtime.ps1").read_text(
        encoding="utf-8"
    )
    batch = (root / "robot_runtime" / "packaging" / "start.bat").read_text(
        encoding="utf-8"
    )
    assert "EIArtRobotRuntimeLauncher" in launcher
    assert 'Get-RuntimeState "/ready"' in launcher
    assert "protocolCompatible -eq $true" in launcher
    assert "Get-NetUDPEndpoint" in launcher
    assert "start_robot_runtime.ps1" in batch


def test_three_terminal_acceptance_script_checks_real_endpoints_and_can_probe_devices():
    root = Path(__file__).resolve().parents[1]
    script = (root / "scripts" / "verify_three_terminal_readiness.ps1").read_text(
        encoding="utf-8"
    )
    assert "/api/server/status" in script
    assert "/health" in script
    assert "/ready" in script
    assert "/api/v2/control/devices/check" in script
    assert "behavior-sync-v1" in script
    assert "RunDeviceCheck" in script
    assert "logs\\acceptance" in script
