# 环境与配置说明

本文档描述如何在本机复现 **Flask + Socket.IO 后端**、连接 **教师端（Vite）**、初始化数据库及可选子系统。项目根目录另见 [项目结构说明.md](../项目结构说明.md)。

## 1. 运行时要求

- **Python**：建议 3.10+（与当前依赖如 `mediapipe` 兼容即可）。
- **Node.js**：教师端 `teacher_frontend` 建议使用 LTS（18+），用于 `npm run dev` / `npm run build`。
- **操作系统**：已在 Windows 上开发与运行；录制依赖 `pyaudio`，在 Linux 上需系统音频开发包。

### 后端（主服务）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python database/init_db.py
python app.py
```

**依赖拆分**：根目录 `requirements.txt` 含运行主服务所需依赖（含 `soundfile`，因真实语音分析器模块在启动时会被加载）。若启用 **FunASR 等真实 ASR**，需额外安装：

```powershell
pip install -r requirements-optional-analyzers.txt
```

详见根目录 `requirements-optional-analyzers.txt` 内注释。

默认在 `app.py` 末尾使用 `socketio.run(app, host="0.0.0.0", port=8080, ...)`（绑定全网卡以便局域网访问）。生产环境若需多进程/反向代理，需自行选用 `gunicorn` + `eventlet`/`gevent` 等方案（当前仓库以开发用法为准）。

#### 局域网儿童端麦克风（推荐：HTTP + 浏览器启动脚本）

Runtime 默认 **HTTP**（`.env` 设 `ENABLE_HTTPS=false`）。本机 `http://127.0.0.1:8080` 已是安全上下文，麦克风可用。局域网 IP 的 `http://IP:8080/child` 不是安全上下文，请用专用配置启动 Edge/Chrome：

```powershell
# Runtime 保持 HTTP 后：
.\.venv\Scripts\python.exe app.py
# 儿童端 LAN 采麦（自动检测 LAN IP，默认也可 -LanHost 192.168.1.113）：
.\scripts\Open-ChildLanMic.ps1
```

脚本会用 `--unsafely-treat-insecure-origin-as-secure=http://<IP>:8080` 打开 `/child`（独立 `--user-data-dir`）。课堂用 **Media Agent** 时不依赖浏览器麦克风。

#### 可选：局域网 HTTPS（自签名）

若仍要整站 HTTPS：`.\scripts\generate_lan_cert.ps1` 后设 `ENABLE_HTTPS=true` 并重启（此时 :8080 仅 HTTPS）。教师端 Vite 仍为 HTTP；代理后端时设 `VITE_BACKEND_URL=https://127.0.0.1:8080`。关闭：`ENABLE_HTTPS=false` 或去掉 `ENABLE_HTTPS` / `SSL_*` 后重启。

### 教师端（React + Vite）

```powershell
cd teacher_frontend
npm ci
npm run dev
```

默认开发服务器通常为 `http://localhost:5173`。Socket.IO 后端地址在 `teacher_frontend/components/ControlPage.tsx` 中配置：开发时优先使用环境变量 **`VITE_SOCKET_URL`**（未设置时默认为 `http://127.0.0.1:8080`），与 Flask 端口一致即可。

### 机械臂玩偶子系统（可选）

见 [docs/README_USAGE.md](README_USAGE.md)（原根目录说明，与 `doll/` Node 服务配合）。

### 儿童端 Media Agent（可选，课堂模式 A）

> 已并入 **Robot Runtime**。请优先阅读 [ROBOT_RUNTIME.md](ROBOT_RUNTIME.md)。

在儿童 / 机器人 Windows 设备上：

```powershell
set ROBOT_RUNTIME_BACKEND_URL=http://<后端IP>:8080
python -m robot_runtime.agent
# 或 robot_runtime\start.bat
```

服务端：`ROBOT_CONTROL_MODE=robot_runtime`，`CHILD_MEDIA_MODE=agent`。  
机器人端安装包下载：`http://<后端IP>:8080/robot/download`（见 [ROBOT_DEPLOY.md](ROBOT_DEPLOY.md)）。

---

## 2. 环境变量（`app/config.py`）

复制根目录 [`.env.example`](../.env.example) 为 `.env`（勿提交）。下列变量可通过环境覆盖，完整列表以代码为准：

| 类别 | 变量示例 | 说明 |
|------|-----------|------|
| Flask | `SECRET_KEY` | 会话与 CSRF 等，生产必须替换 |
| HTTPS（可选） | `ENABLE_HTTPS`, `SSL_CERTFILE`, `SSL_KEYFILE` | 默认 `false`（HTTP）。LAN 采麦优先 `scripts/Open-ChildLanMic.ps1`；自签名见 `generate_lan_cert.ps1` |
| 视频 | `VIDEO_FPS`, `VIDEO_WIDTH`, `VIDEO_HEIGHT`, `VIDEO_CODEC`, `VIDEO_QUALITY` | 须与 `static/js/child.js` 中采集参数一致 |
| 音频 | `AUDIO_SAMPLE_RATE`, `AUDIO_CHANNELS`, `AUDIO_CODEC`, `AUDIO_BITRATE` | 须与儿童端录制一致 |
| 队列 | `VIDEO_QUEUE_SIZE`, `AUDIO_QUEUE_SIZE`, `RESULT_QUEUE_SIZE` | 背压与内存 |
| 分析 | `POSE_ESTIMATION_ENABLED`, `FACE_ANALYSIS_ENABLED`, `AUDIO_ANALYSIS_ENABLED`, `OBJECT_DETECTION_ENABLED`, `VISION_ANALYSIS_INTERVAL`, `AUDIO_ANALYSIS_INTERVAL` | 功能开关与频率 |
| 会话 | `SESSION_TIMEOUT`, `MAX_CONCURRENT_SESSIONS` | 会话生命周期 |
| WebSocket | `WS_HEARTBEAT_INTERVAL`, `WS_TIMEOUT` | 连接保活 |
| 儿童媒体 | `CHILD_MEDIA_MODE` (`browser`/`agent`), `CHILD_MEDIA_AGENT_PORT`, `CHILD_MEDIA_AGENT_KEY`, `CHILD_MEDIA_AGENT_FPS`, `CHILD_MEDIA_AGENT_JPEG_QUALITY` | 课堂部署用 `agent`；见 [ROBOT_RUNTIME.md](ROBOT_RUNTIME.md) |
| 机械臂控制 | `ROBOT_CONTROL_MODE` (`server_osc`/`child_agent`/`robot_runtime`), `ROBOT_RUNTIME_KEY`, `OSC_IP`, `OSC_PORT` | 跨机用 `robot_runtime`；机器人端安装包见 `/robot/download` 与 [ROBOT_DEPLOY.md](ROBOT_DEPLOY.md) |
| 儿童对话 | `DIALOGUE_ENABLED`, `DIALOGUE_TTS_MODE`, `AI_CHAT_PROVIDER`, `VOICE_PYTHON_SERVICE_URL` | 浏览器对话 / TTS；STT 走本进程 FunASR 或 `http://127.0.0.1:8765` |
| Voice service | `START_VOICE_SERVICE`, `VOICE_SERVICE_PYTHON`, `VOICE_SERVICE_FUNASR_*` | `app.py` 在对话开启时自动拉起 `tools/voice-service`（ExpertAnnotator ASD venv）；见 [tools/voice-service/README.md](../tools/voice-service/README.md) |
| 日志 | `LOG_LEVEL` | 如 `DEBUG` / `INFO` |
| 线程池 | `ANALYSIS_THREAD_POOL_SIZE`, `RECORDING_THREAD_POOL_SIZE` | 并发度 |

数据库 URI 默认写在 `Config.SQLALCHEMY_DATABASE_URI` 指向 `database/app.db`；若需改库路径，需改代码或自行扩展为从环境读取。

---

## 3. 分析器配置（`config/analyzers.yaml`）

1. 仓库默认 **`global.mode: real`**（pose/speech matcher 同步 real）；无需每次手改。
2. 无模型/本机冒烟：环境变量 **`USE_REAL_ANALYZERS=false`**，或服务端控制台预设 `mock_only`。
3. Real 创建失败时 Registry **自动回退 Mock** 并打 warning（face 无 Real 实现则始终 Mock）。
4. Real 模式可能涉及 **GPU / FunASR / MediaPipe 模型**，见 `requirements-optional-analyzers.txt` 与归档 [docs/archive/分析模型接入指南_V2.md](archive/分析模型接入指南_V2.md)。
5. 课堂媒体：生产用 `CHILD_MEDIA_MODE=agent`（见 [ROBOT_DEPLOY.md](ROBOT_DEPLOY.md)）；`browser` 仅联调捷径。

---

## 4. 数据库

见 [database/README.md](../database/README.md)：初始化、默认账号、课程迁移脚本说明。

---

## 5. 语音与联调文档

- [语音系统测试指南.md](语音系统测试指南.md)
- [语音系统技术说明书.md](语音系统技术说明书.md)

---

## 6. 已知可选模块

- **真实视觉/语音分析模型**：依赖与性能见归档中的接入指南。
- **机械臂 / OSC**：见 `app/robot/` 与 `docs/README_USAGE.md`。
- **doll 独立服务**：与主 Flask 通过 HTTP 等集成，非启动 Flask 的必需项。
