# Robot Agent 启动说明（已弃用独立进程）

> **请改用统一 [Robot Runtime](ROBOT_RUNTIME.md)**（`python -m robot_runtime.agent`，端口 `19091`）。  
> 本文件保留旧 `doll/robot_agent.py`（19090，仅 OSC）的说明，仅供紧急回退。

## 旧流程（不推荐）

1. 启动 `doll/DollSer/bin/DollSer.exe`（OSC `127.0.0.1:12000`）
2. `python doll/robot_agent.py`（HTTP `127.0.0.1:19090`）
3. 后端 `ROBOT_CONTROL_MODE=child_agent`，机器人端浏览器打开 `/child` 转发动作

跨机课堂请使用 **`ROBOT_CONTROL_MODE=robot_runtime`**，见 [ROBOT_RUNTIME.md](ROBOT_RUNTIME.md)。
