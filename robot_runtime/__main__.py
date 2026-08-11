"""python -m robot_runtime → agent main."""
from robot_runtime import register_client
from robot_runtime.agent import AGENT_HOST, AGENT_PORT, app, get_data_dir, _runtime_version

if __name__ == "__main__":
    print(f"[RobotRuntime] listen on http://{AGENT_HOST}:{AGENT_PORT}")
    print(f"[RobotRuntime] data dir {get_data_dir()}")
    print(f"[RobotRuntime] version {_runtime_version()}")
    print(f"[RobotRuntime] UI http://127.0.0.1:{AGENT_PORT}/ui")
    cfg = register_client.get_registry_status()
    if cfg.get("backendUrl"):
        print(f"[RobotRuntime] backend {cfg.get('backendUrl')}")
    else:
        print("[RobotRuntime] backend URL 未设置 — 请在 /ui 填写并「应用并注册」")
    print(f"[RobotRuntime] config {cfg.get('configPath')}")
    register_client.start_background(AGENT_PORT)
    app.run(host=AGENT_HOST, port=AGENT_PORT, debug=False, threaded=True)
