import json

from app.robot import neutral_pose
from robot_runtime.osc_bridge import normalize_pose


def test_neutral_pose_comes_from_configured_empty_action(tmp_path, monkeypatch):
    motions = tmp_path / "motions.json"
    mapping = tmp_path / "course_map.json"
    mapping.write_text(json.dumps({"defaults": {"idle": "空动作"}}, ensure_ascii=False), encoding="utf-8")
    motions.write_text(json.dumps({
        "version": 2,
        "motions": {"空动作": [{"time": 0, "pose": {
            "pitch": 201, "yaw": 159, "armL": 319, "armR": 51,
        }}]},
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(neutral_pose, "COURSE_MAP_FILE", str(mapping))
    monkeypatch.setattr(neutral_pose, "MOTIONS_FILE", str(motions))
    monkeypatch.setattr(neutral_pose, "_cache_key", None)

    assert neutral_pose.get_neutral_pose() == {
        "pitch": 201, "yaw": 159, "armL": 319, "armR": 51,
    }
    assert neutral_pose.complete_pose({"yaw": 170}) == {
        "pitch": 201, "yaw": 170, "armL": 319, "armR": 51,
    }


def test_runtime_uses_server_neutral_pose_for_incomplete_frames():
    assert normalize_pose(
        {"pitch": 210},
        {"pitch": 200, "yaw": 160, "armL": 320, "armR": 50},
    ) == {"pitch": 210, "yaw": 160, "armL": 320, "armR": 50}
