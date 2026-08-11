# Child Media Agent（儿童端媒体采集）

> **已并入 [Robot Runtime](ROBOT_RUNTIME.md)**（`robot_runtime/`，端口 19091）。  
> `child_media_agent/agent.py` 仅为兼容入口，会转发到 Runtime。

儿童 / 机器人 Windows 设备上的本机服务：独占摄像头/麦克风，本地落盘，并向后端可靠上行；同时提供 DollSer OSC 桥。

## 与 Robot Agent 的关系

| 服务 | 默认端口 | 职责 |
|------|----------|------|
| ~~Robot Agent (`doll/robot_agent.py`)~~ | `19090` | **弃用**，仅 OSC |
| **Robot Runtime** (`robot_runtime/`) | `19091` | 媒体 + OSC + 运维 UI |

详见 [ROBOT_RUNTIME.md](ROBOT_RUNTIME.md)。

## 启动

```bash
set ROBOT_RUNTIME_BACKEND_URL=http://<后端IP>:8080
python -m robot_runtime.agent
```

或 `robot_runtime/start.bat`。

## 后端模式

```bash
CHILD_MEDIA_MODE=agent
ROBOT_CONTROL_MODE=robot_runtime
```

其余媒体 HTTP 接口、验收要点与原先 Media Agent 相同，见 Runtime 文档。
