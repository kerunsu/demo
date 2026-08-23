"""第一阶段：源码契约快照与运行时装配交叉验证。"""

import ast
import json
import os
import runpy
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "tests" / "fixtures" / "contracts" / "contracts.snapshot.json"


def _python_sources():
    return [ROOT / "app.py", *sorted((ROOT / "app").rglob("*.py"))]


def _source_contracts():
    prefixes = {
        "robot_bp": "/api/robot",
        "media_bp": "/api/media",
        "report_bp": "/api/report",
        "monitor_bp": "/api/monitor",
        "config_content_bp": "/api/config",
        "server_config_files_bp": "/api/server/config",
        "capture_devices_bp": "/api/v2/capture",
        "asset_library_bp": "/api/v2/assets",
        "interaction_profiles_bp": "/api/v2/interaction",
        "control_overview_bp": "/api/v2/control",
        "config_sync_bp": "/api/v2/config/sync",
        "voice_status_bp": "/api/v2/voice",
        "interaction_timeline_bp": "/api/v2/timeline",
    }
    routes = set()
    events = set()
    emits = set()
    for path in _python_sources():
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if not isinstance(decorator, ast.Call):
                        continue
                    if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                        continue
                    value = str(ast.literal_eval(decorator.args[0]))
                    name = ast.unparse(decorator.func)
                    if name.endswith(".route"):
                        prefix = prefixes.get(name.split(".", 1)[0], "")
                        methods = ["GET"]
                        for keyword in decorator.keywords:
                            if keyword.arg == "methods":
                                methods = list(ast.literal_eval(keyword.value))
                        routes.update((method, prefix + value) for method in methods)
                    elif ".on" in name or name.endswith(".on_event"):
                        events.add(value)
            if isinstance(node, ast.Call) and node.args:
                if isinstance(node.func, ast.Attribute) and node.func.attr == "emit":
                    if isinstance(node.args[0], ast.Constant):
                        emits.add(str(node.args[0].value))
                elif isinstance(node.func, ast.Name) and node.func.id == "emit":
                    if isinstance(node.args[0], ast.Constant):
                        emits.add(str(node.args[0].value))
    return routes, events, emits


@pytest.fixture(scope="module")
def phase1_runtime():
    old = {
        key: os.environ.get(key)
        for key in ("START_TEACHER_FRONTEND", "START_VOICE_SERVICE", "DIALOGUE_ENABLED")
    }
    os.environ["START_TEACHER_FRONTEND"] = "0"
    os.environ["START_VOICE_SERVICE"] = "0"
    os.environ["DIALOGUE_ENABLED"] = "0"
    try:
        yield runpy.run_path("app.py", run_name="phase1_runtime_contracts")
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_phase1_runtime_url_map_matches_source_snapshot(phase1_runtime):
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    source_routes, _, _ = _source_contracts()
    runtime_routes = set()
    for rule in phase1_runtime["app"].url_map.iter_rules():
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            runtime_routes.add((method, rule.rule))

    expected = source_routes | {
        ("GET", "/static/<path:filename>"),
    }
    assert len(source_routes) == snapshot["routeCount"] == 194
    assert runtime_routes == expected
    assert len(runtime_routes) == snapshot["runtimeUrlRuleCountObserved"] == 195
    assert snapshot["runtimeImplicitRoutes"] == ["GET /static/<path:filename>"]


def test_phase1_socket_registration_and_emit_scan_match_snapshot(phase1_runtime):
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    _, source_events, source_emits = _source_contracts()
    actual_events = set(phase1_runtime["socketio"].server.handlers.get("/", {}))

    assert source_events == set(snapshot["socketDecoratedEvents"])
    assert actual_events == source_events
    assert len(actual_events) == snapshot["socketDecoratorCount"] == 69
    assert source_emits == set(snapshot["observedServerEmits"])
    assert len(source_emits) == 71
