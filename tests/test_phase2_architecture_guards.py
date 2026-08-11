"""第二阶段：目标骨架、依赖方向和首个 facade vertical slice 守卫。"""

from __future__ import annotations

import ast
import sys
import threading
from pathlib import Path

from app.contracts.models import ServerStatusSnapshot
from app.facade.presenters.server_status import present_server_status
from app.facade.use_cases.server_status import ServerStatusInputs, ServerStatusUseCase


ROOT = Path(__file__).resolve().parents[1]


def _py_files(relative: str) -> list[Path]:
    root = ROOT / relative
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_phase2_target_layout_exists_without_moving_legacy_modules():
    expected = (
        "contracts",
        "facade",
        "acquisition",
        "computation",
        "storage/repositories",
        "storage/content_catalog",
    )
    assert all((ROOT / "app" / item).is_dir() for item in expected)
    assert (ROOT / "app.py").is_file()
    assert (ROOT / "app" / "sockets" / "events.py").is_file()


def test_phase2_contracts_are_framework_and_infrastructure_free():
    forbidden = {
        "flask",
        "flask_socketio",
        "sqlalchemy",
        "database",
        "cv2",
        "pyaudio",
        "sounddevice",
    }
    for path in _py_files("app/contracts"):
        assert not any(
            name == item or name.startswith(item + ".")
            for name in _imports(path)
            for item in forbidden
        ), path


def test_phase2_new_block_skeletons_obey_dependency_direction():
    forbidden_by_root = {
        "app/facade": {"flask", "flask_socketio", "sqlalchemy", "database", "app.sockets", "app.services", "app.robot"},
        "app/acquisition": {"app.dialogue", "app.report", "app.robot", "llm", "openai"},
        "app/computation": {"flask", "flask_socketio", "app.dialogue", "cv2", "pyaudio", "sounddevice"},
        "app/storage/repositories": {"flask", "flask_socketio", "app.facade", "cv2", "pyaudio"},
        "app/storage/content_catalog": {"flask", "flask_socketio", "app.facade", "cv2", "pyaudio"},
    }
    for relative, forbidden in forbidden_by_root.items():
        for path in _py_files(relative):
            imports = _imports(path)
            assert not any(
                name == item or name.startswith(item + ".")
                for name in imports
                for item in forbidden
            ), f"{path}: {sorted(imports)}"


def test_phase2_frontends_do_not_import_server_implementation_modules():
    forbidden = ("database", "sqlalchemy", "sqlite3", "cv2", "pyaudio", "VideoCapture")
    roots = [ROOT / "teacher_frontend" / "src", ROOT / "static" / "js", ROOT / "templates"]
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix.lower() not in {".js", ".jsx", ".ts", ".tsx", ".html"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert not any(token.lower() in text.lower() for token in forbidden), path


def test_phase2_composition_root_is_lazy_and_does_not_start_runtime_resources():
    before = {thread.ident for thread in threading.enumerate()}
    from app.facade.bootstrap import create_application_container

    container = create_application_container()
    use_case = container.get("server_status_use_case")
    after = {thread.ident for thread in threading.enumerate()}
    assert use_case.__class__.__name__ == "ServerStatusUseCase"
    assert before == after
    assert "app.py" not in sys.modules
    container.close()


def test_phase2_server_status_vertical_slice_preserves_legacy_presenter_shape():
    class Config:
        def get_all_config(self):
            return {"global": {"mode": "mock"}}

        def get_snapshot_count(self):
            return 2

        def get_audit_logs(self, limit=1000):
            assert limit == 1000
            return [{"id": 1}]

    class Analysis:
        def get_statistics(self):
            return {"processed": 3}

        def get_all_session_states(self):
            return {"s1": {"status": "idle"}}

    snapshot = ServerStatusUseCase().execute(
        ServerStatusInputs(
            config_manager=Config(),
            analysis_service=Analysis(),
            model_status=lambda _config: {"pose": "mock"},
            online_presence=lambda: {"teachers": 1},
            robot_control_mode=lambda: "robot_runtime",
            child_media_mode=lambda: "browser",
            media_session_meta=lambda: {"m1": {"status": "active"}},
            runtime_status=lambda: {"online": False},
        )
    )
    assert isinstance(snapshot, ServerStatusSnapshot)
    assert present_server_status(snapshot) == {
        "success": True,
        "statistics": {"processed": 3},
        "sessions": {"s1": {"status": "idle"}},
        "modelStatus": {"pose": "mock"},
        "globalMode": "mock",
        "snapshotCount": 2,
        "historyCount": 1,
        "onlinePresence": {"teachers": 1},
        "robotControlMode": "robot_runtime",
        "childMediaMode": "browser",
        "mediaSessionMeta": {"m1": {"status": "active"}},
        "robotRuntime": {"online": False},
    }


def test_phase2_socket_registry_adapter_delegates_once_without_re_registration():
    from app.facade.sockets import register_legacy_socket_events

    calls = []

    def legacy_register(socketio):
        calls.append(socketio)
        return "registered"

    socketio = object()
    assert register_legacy_socket_events(socketio, legacy_register) == "registered"
    assert calls == [socketio]
