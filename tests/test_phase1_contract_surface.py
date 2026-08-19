"""第一阶段契约表面与旧映射逻辑特征测试。

这些测试只读取现有装饰器/配置并验证旧行为，不实现新架构，也不修改业务代码。
"""

import ast
import json
from pathlib import Path

from app.robot.mapping_resolver import MappingResolver
from app.services.recording_timeline import TIMELINE_COLUMNS


ROOT = Path(__file__).resolve().parents[1]


def _decorated_contracts():
    routes = set()
    events = set()
    prefixes = {
        "robot_bp": "/api/robot",
        "media_bp": "/api/media",
        "report_bp": "/api/report",
        "monitor_bp": "/api/monitor",
        "config_content_bp": "/api/config",
        "server_config_files_bp": "/api/server/config",
    }
    paths = [ROOT / "app.py", *sorted((ROOT / "app").rglob("*.py"))]
    for path in paths:
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                name = ast.unparse(decorator.func)
                if decorator.args and isinstance(decorator.args[0], ast.Constant):
                    value = str(ast.literal_eval(decorator.args[0]))
                else:
                    continue
                if name.endswith(".route"):
                    prefix = prefixes.get(name.split(".", 1)[0], "")
                    methods = ["GET"]
                    for keyword in decorator.keywords:
                        if keyword.arg == "methods":
                            methods = list(ast.literal_eval(keyword.value))
                    for method in methods:
                        routes.add((method, prefix + value))
                elif ".on" in name or name.endswith(".on_event"):
                    events.add(value)
    return routes, events


def test_phase1_legacy_http_surface_has_no_removed_critical_routes():
    routes, _ = _decorated_contracts()
    expected = {
        ("GET", "/"),
        ("GET", "/child"),
        ("GET", "/server"),
        ("GET", "/therapist"),
        ("GET", "/api/server/status"),
        ("GET", "/api/students"),
        ("POST", "/api/teacher/login"),
        ("POST", "/api/media/<session_id>/frames"),
        ("POST", "/api/media/<session_id>/audio-chunks"),
        ("POST", "/api/media/<session_id>/upload"),
        ("GET", "/api/monitor/snapshot"),
        ("GET", "/api/monitor/ambient/devices"),
        ("POST", "/api/robot/motions/import"),
        ("POST", "/api/robot/emotions/upload"),
        ("GET", "/api/report/<training_session_id>"),
    }
    assert expected <= routes


def test_phase1_legacy_socket_surface_has_no_removed_critical_events():
    _, events = _decorated_contracts()
    expected = {
        "connect",
        "disconnect",
        "client_presence",
        "join_session",
        "leave_session",
        "prepare_training",
        "cancel_prepare_training",
        "readiness_start",
        "readiness_cancel",
        "readiness_force_enter",
        "readiness_child_report",
        "readiness_complete",
        "play_resource",
        "resource_ready",
        "resource_transition_failed",
        "video_frame",
        "audio_chunk",
        "stop_recording",
        "finalize_training",
        "teacher_rating_submit",
        "child_dialogue_text",
        "child_dialogue_audio",
        "robot_speak_ended",
        "robot_play_motion",
        "robot_stop_playback",
        "robot_emotion_auto_random",
    }
    # readiness_complete is a server-emitted event rather than a decorator.
    assert expected - {"readiness_complete"} <= events


def test_phase1_existing_recording_timeline_columns_are_frozen():
    assert TIMELINE_COLUMNS == [
        "seg_index",
        "seg_kind",
        "course_type_id",
        "course_item_id",
        "course_id",
        "question_id",
        "t_start_sec",
        "t_end_sec",
        "t_start_hms",
        "t_end_hms",
        "wall_start_iso",
        "wall_end_iso",
    ]


def test_phase1_mapping_resolver_uses_global_course_item_precedence(tmp_path):
    mapping_path = tmp_path / "course_map.json"
    mapping_path.write_text(
        json.dumps(
            {
                "defaults": {
                    "question": ["default-question"],
                    "praise": ["default-praise"],
                },
                "courses": {"7": {
                    "question": ["course-question"],
                    "items": {"11": {"question": ["item-question"]}},
                }},
                "students": {
                    "3": {
                        "7": {
                            "question": ["student-course-question"],
                            "items": {"11": {"question": ["item-question"]}},
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    resolver = MappingResolver(str(mapping_path))

    assert resolver.parse_aux_type({"question": True}) == "question"
    assert resolver.parse_aux_type({"praise": True, "question": True}) == "praise"
    assert resolver.parse_aux_type({"socialGreetingIntro": True}) == "social_greeting_intro"
    assert resolver.parse_aux_type({}) == "silent"
    assert resolver.find_mapping(3, 7, 11, "question")["motions"] == ["item-question"]
    # 旧 students 数据保留但已退出机器人执行链。
    assert resolver.find_mapping(3, 7, 12, "question")["motions"] == ["course-question"]
    assert resolver.find_mapping(4, 7, 12, "question")["motions"] == ["course-question"]
    assert resolver.find_mapping(4, 8, 12, "question")["motions"] == ["default-question"]


def test_behavior_event_ownership_separates_social_from_ordering():
    from app.robot.behavior_events import allowed_aux_types, is_aux_allowed

    assert allowed_aux_types("ordering") == ("praise", "question", "hint", "silent")
    assert not is_aux_allowed("ordering", "social_greeting_intro")
    assert allowed_aux_types("social", social_role="greeting") == (
        "silent", "social_greeting_intro", "social_greeting_play",
    )
    # 社交课点 content load 走 silent，必须允许；标准表扬不得泄漏进打招呼。
    assert is_aux_allowed("social", "silent", social_role="greeting")
    assert not is_aux_allowed("social", "praise", social_role="greeting")
    assert not is_aux_allowed("social", "social_farewell_bye", social_role="greeting")


def test_mapping_resolver_accepts_windows_utf8_bom(tmp_path):
    mapping_path = tmp_path / "course_map.json"
    payload = {"defaults": {"question": ["ask"]}, "courses": {}, "students": {}}
    mapping_path.write_bytes(b"\xef\xbb\xbf" + json.dumps(payload).encode("utf-8"))

    resolver = MappingResolver(str(mapping_path))

    assert resolver.find_mapping(None, 1, None, "question")["motions"] == ["ask"]
