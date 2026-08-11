# E.I.Art server_demo

协作前请先阅读 [`AGENTS.md`](AGENTS.md)，其中记录当前工作区边界、共享契约和跨模块影响说明要求。

Flask + Flask-SocketIO + SQLAlchemy/SQLite 训练系统，包含教师端、儿童端、
监控/配置台与机器人运行端（Robot Runtime）四类客户端。系统保留旧版
HTTP/Socket 契约与会话文件命名；V2 控制接口为增量扩展，可回退到旧路径。

## 快速开始

```powershell
.\start_server.ps1
```

`start_server.ps1` 会校验依赖版本与导入、自动安装缺失的 Python/npm 依赖，
并启动唯一一个后端实例。如需只读环境检查，使用 `.\start_server.ps1 -CheckOnly`；
直接运行 `python app.py` 也受同一单实例锁保护。

默认端点：后端 `http://127.0.0.1:8080`，教师端 `http://127.0.0.1:8080/teacher/`，
儿童端 `/child`，监控/配置台 `/server`，机器人运行端 `http://127.0.0.1:19091/ui`。
`START_TEACHER_FRONTEND=0` 与 `START_VOICE_SERVICE=0` 可保留原有启动控制。

## 模块结构与分工

团队成员按以下分工协作，**改动只在自己的主工作区内进行**，避免跨模块冲突：

### 1. 前端修改（教师端 / 儿童端 / 监控台）

| 目录 | 内容 |
|---|---|
| `teacher_frontend/` | 教师端 SPA（React + Vite）：`App.tsx`、`components/`（ControlPage、CourseSelectionPage、LoginPage、ReportPage 等）、`src/`、`styles/`。修改后需 `npm ci && npm run build` 重新构建，`dist/` 由后端同源提供 |
| `templates/` | 儿童端页面 `child.html`、监控台 `server.html`、机器人下载页 `robot_download.html` |
| `static/js/` | 各页面使用的脚本（`config_*.js`、`config_sync.js` 等） |

### 2. 语音模块修改（语音服务与播放）

| 目录 | 内容 |
|---|---|
| `tools/voice-service/` | 独立语音服务进程（`voice_service.py`、`prepare_models.py`）：ASR 识别、TTS 合成、模型下载与路径缓存 |
| `app/audio/` | 后端语音子系统：`controller.py`（播放控制）、`events.py`（socket 事件）、`service.py`（播放服务）、清单加载（`audio.registry`） |

### 3. 分析模块修改（识别与匹配）

| 目录 | 内容 |
|---|---|
| `app/core/` | 分析核心：`base_analyzer.py`、`audio/`（`speech_analyzer.py`、`real_speech_analyzer.py`）、`matchers/`（`speech_matcher.py`、`pose_matcher.py`）、`pipelines/`（`audio_pipeline.py`、`vision_pipeline.py`） |
| `app/behavior/` | 行为触发与匹配：`models.py`、`matchers` 的集成、触发规则、行为执行与降级 |
| `models/` | 模型文件（`pose_landmarker_lite.task` 等） |

### 4. 整合与后端开发（接口、录制、机器人控制）

| 目录 | 内容 |
|---|---|
| `app.py` | 应用入口与启动装配 |
| `app/routes/` | HTTP API（V2 控制台、时间线、素材库、设备检查等） |
| `app/sockets/` | Socket 事件：`events.py`（play_resource 等）、`handlers.py`、`robot_events.py` |
| `app/robot/` | 机器人服务与表情/动画/动作资产管理 |
| `app/storage/`、`app/services/`、`app/facade/`、`app/contracts/` | 数据层、服务层、门面与契约 |
| `app/config.py`、`config/`、`database/`、`scripts/`、`tests/` | 配置、数据模型与 seed、运维脚本、测试 |

### 其他（所有角色共享）

- `robot_runtime/`：机器人端运行程序（独立机器部署，改动经 `scripts/pack_robot_release.ps1` 打包分发）
- `doll/`：表情/动作资产与 DollSer 工作台（新素材统一 MP4，勿再添加 GIF）
- `docs/`：项目文档（新增/修改功能时同步更新对应指南）

**协作约定**：功能改动后运行 `python -m pytest tests -q` 与本模块相关用例；接口变更通知"整合与后端开发"角色同步契约（`docs/CONTRACT.md`）；素材新增通知前端与语音角色更新清单。

## 日志与诊断

- `logs/app.log` —— 全部模块日志（socket 事件、录制、机器人服务）自 2026-08-10
  起统一追加到此文件；控制台显示 `INFO`，文件保留 `DEBUG`。
- `static/recordings/sessions/<课程目录>/full_interaction_timeline.jsonl` ——
  教师/儿童点击、机器人模态事件与每条 `play_resource_ack` 的全量审计流
  （详见 [运维手册](docs/OPERATIONS.md#application-logs)）。
- 排查"点了没反应"：在 `app.log` 中搜索 `play_resource 收到` / `行为繁忙拒绝`
  / `回执`，并按 `requestId` 在时间线中交叉核对。

## 文档索引

- [文档总览](docs/README.md) —— 现行指南与归档设计历史
- [架构](docs/ARCHITECTURE.md) —— 六大模块与依赖约束
- [协作工作区](docs/COLLABORATION.md) —— 前端/后端/语音/模型的职责与接口规则
- [契约](docs/CONTRACT.md) —— HTTP、Socket、运行端与兼容性规则
- [数据模型](docs/DATA_SCHEMA.md) —— SQLite、会话、轨道与时间线
- [配置](docs/CONFIGURATION.md) —— 环境变量、设备配置与素材
- [运维](docs/OPERATIONS.md) —— 健康检查、备份、升级与回滚
- [扩展](docs/EXTENDING.md) —— 设备、模型、对话与交互配置
- [测试](docs/TESTING.md) —— 假设备、契约测试与发布门禁
- [当前架构](docs/ARCHITECTURE.md) —— 当前模块边界与依赖方向
- [教师端 Windows 控制锁修复 2026-08-10](docs/教师端Windows控制锁修复与验收记录-20260810.md)
  —— Windows `Errno 22` 根因、恢复行为与浏览器证据
- [三端协同稳定性整改方案](docs/current/三端协同稳定性根因与分阶段整改方案.md)
  —— 根因、已实施改动、现场证据与剩余浸泡测试

历史文档归档于 `docs/archive/`，不具规范效力。机器人动作格式说明位于工作台
`doll/DollSer/docs/`。切勿重置或清理包含 `database/app.db`、录制、日志、
发布包或课程素材的部署。
