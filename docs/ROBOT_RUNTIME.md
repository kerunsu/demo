"""
# Robot Runtime — 机器人端统一进程

合并原 `child_media_agent`（媒体采集）与 `doll/robot_agent`（DollSer OSC 桥）。

## 跨机部署（推荐）

| 机器 | 运行内容 |
|------|----------|
| 后端主机 | `python app.py`，`ROBOT_CONTROL_MODE=robot_runtime`，`CHILD_MEDIA_MODE=agent` |
| 机器人端 | **发布 zip**（`RobotRuntime.exe` + DollSer）或开发机源码；浏览器打开服务器 `/child`、`/robot/emotion` |

动作路径：**后端 HTTP → Runtime `/osc/*` → 本机 DollSer**（不依赖儿童页转发）。  
关浏览器 `/child` 后动作仍可达。

完整部署对照见 [ROBOT_DEPLOY.md](ROBOT_DEPLOY.md)。

## 发布与安装（exe 包）

在 **Windows** 仓库根目录打包（建议用仅含 `robot_runtime/requirements.txt` 的干净 venv，避免 conda 环境把无关库打进 exe）：

```powershell
.\scripts\pack_robot_release.ps1
```

产物在 `releases/robot/`。后端提供：

- 下载页：`GET /robot/download`
- 元信息：`GET /api/robot/runtime/version`
- 文件：`GET /api/robot/runtime/download`

机器人机打开下载页 → 解压 → 双击包内 `start.bat` → `/ui` 填后端地址。

仅构建 exe（不打 zip）：

```powershell
.\robot_runtime\build_exe.ps1
```

## 启动（开发机源码）

```bash
# 机器人端（推荐：先双击 start.bat，再在 /ui 填写后端地址）
robot_runtime\start.bat

# 或命令行
python -m robot_runtime.agent
```

默认监听：`0.0.0.0:19091`  
运维 UI：`http://127.0.0.1:19091/ui`

**后端地址怎么配（三选一，推荐 1）：**

1. 打开 `/ui`，填写 `http://<后端局域网IP>:8080`，点「应用并注册」（会写入 `%LOCALAPPDATA%\EIArt\robot_runtime\config.json`，下次启动自动读取）
2. 启动前设置环境变量：`set ROBOT_RUNTIME_BACKEND_URL=http://192.168.x.x:8080`
3. 编辑 `robot_runtime.yaml`（若后续接入；当前以 UI / 环境变量为准）

环境变量优先于 UI 已保存配置。

**本地音视频目录：**

- 默认：`%LOCALAPPDATA%\EIArt\child_media\<sessionId>\`（`video.avi` + `audio.wav`）
- 在 `/ui`「本地音视频目录」修改并应用（写入 `config.json` 的 `mediaDataDir`）；录制中不可改
- 环境变量 `CHILD_MEDIA_DATA_DIR` 若已设置，则优先于 UI

**打开 /child（LAN 麦克风）：**

运维页「打开 /child」会调用 Runtime `POST /ui/open-child`，优先启动 `scripts/Open-ChildLanMic.ps1`（exe 包内与 `RobotRuntime.exe` 同目录），并从当前后端地址解析 `-LanHost` / `-Port`（例如 `http://192.168.1.113:8080` → `-LanHost 192.168.1.113 -Port 8080`）。脚本用 Edge/Chrome 的 insecure-origin 标志打开 LAN HTTP 上的 `/child`，以便 `getUserMedia` 可用。脚本缺失时回退为普通浏览器打开 `http://host:port/child`。

**热更新（exe 包）：**

1. 开发机重新 `.\scripts\pack_robot_release.ps1`，把 `releases/robot/*.zip` + `manifest.json` 拷到服务器
2. 机器人机打开 `/ui` →「检查更新」→「立即更新」
3. Runtime 下载 zip，替换同目录 `RobotRuntime.exe`（及 `start.bat` / `README.txt` / `VERSION` / `Open-ChildLanMic.ps1`），自动重启；**不覆盖 DollSer**
4. 源码模式不支持自动换进程，需重新打包后用 exe 测试机更新

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `ROBOT_RUNTIME_HOST` | `0.0.0.0` | 监听地址（须非 loopback 以便后端直连） |
| `ROBOT_RUNTIME_PORT` | `19091` | 端口 |
| `ROBOT_RUNTIME_BACKEND_URL` | 空 | 后端基址，用于 register |
| `ROBOT_RUNTIME_ADVERTISE_HOST` | 自动探测 | 上报给后端的局域网 IP |
| `ROBOT_RUNTIME_KEY` | 空 | 与后端 `ROBOT_RUNTIME_KEY` 一致 |
| `CHILD_MEDIA_DATA_DIR` | `%LOCALAPPDATA%\EIArt\child_media` | 本地音视频根目录（优先于 UI） |
| `DOLLSER_OSC_IP` / `PORT` | `127.0.0.1` / `12000` | 本机 DollSer |
| 媒体相关 | 同 CHILD_MEDIA_* | 见 CHILD_MEDIA_AGENT.md |

## 控制模式对照

| 模式 | 适用 | 说明 |
|------|------|------|
| `robot_runtime` | **跨机课堂** | 后端直连 Runtime HTTP |
| `child_agent` | 兼容旧方案 | 经 `/child` 网页转发到本机 Agent |
| `server_osc` | 同机调试 | 后端本机 OSC，DollSer 须与后端同机 |

## HTTP 接口摘要

- 媒体：`/health`、`/record/start|stop`、`/preview.mjpeg`（同原 Media Agent）
- OSC：`/osc/play`、`/osc/frame`、`/osc/stop`
- 注册：Runtime → `POST /api/robot/runtime/register`；手动 `POST /register/now`
- 配置：`POST /config/media-dir`；更新：`GET /update/check`、`POST /update/apply`
- UI：`GET /ui`；打开儿童页：`POST /ui/open-child`（LAN mic 脚本，失败则浏览器回退）
- 发布包：后端 `GET /robot/download`、`GET /api/robot/runtime/version`、`GET /api/robot/runtime/download`

## 与旧入口关系

- `child_media_agent/agent.py`：薄包装，转发到 `robot_runtime.agent`
- `doll/robot_agent.py`：弃用，打印提示后可仍跑 OSC-only（建议改用 Runtime）
