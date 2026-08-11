# E.I.Art 教育训练系统（server_demo）

Flask + Socket.IO 后端，配合 **儿童端**（模板 + 静态 JS）与 **教师端**（`teacher_frontend` Vite + React），支持课程训练、媒体录制与可插拔分析流水线。

**交接与由浅入深导读**：请先阅读根目录 **[工程说明.md](工程说明.md)**（统一导航与依赖说明），再按需展开下方链接。

## 快速开始

**推荐（交接/新机器）**：`git pull` 后执行一次幂等引导：

```powershell
python scripts/bootstrap.py
```

会检查/补齐：venv、`pip` 依赖、`.env`、教师端 `npm`、课程资源体检；若无 `database/app.db` 则自动 `init_db` + 标准库播种（`database/seed_standard.py`）。已配好环境时再跑只会体检并跳过已有项。  
仅检查：`python scripts/bootstrap.py --check-only`  
重建库：`python scripts/bootstrap.py --reset-db --yes`

也可逐步手动：

1. 环境与变量：请阅读 [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md)，并复制 `.env.example` 为 `.env`。
2. 初始化并播种标准库：`python database/seed_standard.py`（或仅 `python database/init_db.py`，详见 [database/README.md](database/README.md)）。
3. 教师端首次需安装依赖：`cd teacher_frontend && npm ci`。
4. 一键启动（Windows）：`.\.venv\Scripts\python.exe app.py`（后端 `http://127.0.0.1:8080` + 教师端 Vite `http://127.0.0.1:5173` + 对话 FunASR voice-service `http://127.0.0.1:8765`）。
   - 请直接使用项目虚拟环境的 Python，避免系统 Python 缺少 Flask 等依赖。
   - 仅启动后端：`START_TEACHER_FRONTEND=0 python app.py`（Windows PowerShell：`$env:START_TEACHER_FRONTEND=0; python app.py`）。
   - 对话开启（`DIALOGUE_ENABLED=true`）时默认自动拉起 FunASR（ExpertAnnotator ASD venv）；关闭：`START_VOICE_SERVICE=0`。详见 [tools/voice-service/README.md](tools/voice-service/README.md)。
5. **课堂机器人端（跨机推荐）**：在机器人 Windows 上打开 `http://<后端IP>:8080/robot/download` 下载 exe 安装包，解压后双击 `start.bat`；后端设 `ROBOT_CONTROL_MODE=robot_runtime` 与 `CHILD_MEDIA_MODE=agent`。详见 [docs/ROBOT_DEPLOY.md](docs/ROBOT_DEPLOY.md)、[docs/ROBOT_RUNTIME.md](docs/ROBOT_RUNTIME.md)。

## 文档索引

| 文档 | 内容 |
|------|------|
| [工程说明.md](工程说明.md) | **交接导读**、阅读顺序、`requirements` 说明、结构评价 |
| [docs/PRD.md](docs/PRD.md) | **需求文档**：验收口径、完成度盘点、后续阶段规划 |
| [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) | 依赖、环境变量、分析器 YAML、数据库 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 模块职责与三条主链路 |
| [docs/CONTRACT.md](docs/CONTRACT.md) | **接口契约**：Socket.IO 事件字典（方向 + payload 示例 + room 规则） |
| [docs/ROBOT_INTERACTION_DESIGN.md](docs/ROBOT_INTERACTION_DESIGN.md) | **双屏交互核心规范**：事件时机、上下屏、表情、动作、语音偏移、降级与验收表 |
| [docs/ROBOT_RUNTIME.md](docs/ROBOT_RUNTIME.md) | **机器人端统一 Runtime**：媒体 + DollSer OSC + 运维 UI |
| [docs/ROBOT_DEPLOY.md](docs/ROBOT_DEPLOY.md) | **部署对照**：后端 git pull vs 机器人端 exe 下载包 |
| [docs/CHILD_MEDIA_AGENT.md](docs/CHILD_MEDIA_AGENT.md) | 媒体采集说明（已并入 Runtime） |
| [docs/ROBOT_AGENT.md](docs/ROBOT_AGENT.md) | 旧 OSC-only Agent（弃用） |
| [项目结构说明.md](项目结构说明.md) | 目录树与接口概览 |
| [app/README.md](app/README.md) | `app/` 包内说明 |
| [docs/语音系统测试指南.md](docs/语音系统测试指南.md) | 语音联调步骤 |
| [docs/README_USAGE.md](docs/README_USAGE.md) | 机械臂 / Doll 子系统（可选） |
| [docs/CHANGELOG_handover.md](docs/CHANGELOG_handover.md) | 交接收尾变更摘要 |
| [docs/archive/](docs/archive/) | 历史规划与阶段总结 |

## 可选子系统

- **机械臂 / 表情**：见 `app/robot/` 与 `docs/README_USAGE.md`。
- **doll 独立 Node 服务**：见 `doll/` 与同目录说明。
