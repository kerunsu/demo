# E.I.Art Demo 机独立版

这是可独立拉取和部署的 Demo 机版本，只提供配对和排序课程，以及这两门课程的分析与报告。Demo 机没有机械结构，不提供机械动作、Robot Runtime 或完整版表情；儿童屏幕动画和浏览器语音仍正常使用。

协作前先阅读 [`AGENTS.md`](AGENTS.md) 和 [Demo 同步与部署规范](docs/DEMO_SYNC.md)。两份文件共同规定从完整版本吸收更新时必须保留的 Demo 边界。

## 快速开始

```powershell
.\start_server.ps1
```

`start_server.ps1` 会校验并补齐 Python/npm 依赖，在首次拉取且没有 `database/app.db` 时自动建立只含三门 Demo 课程的数据库，然后构建教师端并启动唯一一个后端实例。只读环境检查使用 `.\start_server.ps1 -CheckOnly`；该命令不会建库，首次部署应直接运行正常启动命令。

默认端点：后端 `http://127.0.0.1:8080`，教师端 `http://127.0.0.1:8080/teacher/`，儿童端 `/child`，监控/配置台 `/server`。Demo 不启动 19091 Robot Runtime。
`START_TEACHER_FRONTEND=0` 与 `START_VOICE_SERVICE=0` 可保留原有启动控制。

## 模块结构与分工

团队成员按以下分工协作，**改动只在自己的主工作区内进行**，避免跨模块冲突：

### 1. 前端修改（教师端 / 儿童端 / 监控台）

| 目录 | 内容 |
|---|---|
| `teacher_frontend/` | 教师端 SPA（React + Vite）：`App.tsx`、`components/`（ControlPage、CourseSelectionPage、LoginPage、ReportPage 等）、`src/`、`styles/`。修改后需 `npm ci && npm run build` 重新构建，`dist/` 由后端同源提供 |
| `templates/` | 儿童端页面 `child.html` 和监控/配置台 `server.html` |
| `static/js/` | 各页面使用的脚本（`config_*.js`、`config_sync.js` 等） |

### 2. 语音模块修改（语音服务与播放）

| 目录 | 内容 |
|---|---|
| `tools/voice-service/` | 旧版本地语音服务诊断工具；生产儿童端已改用浏览器语音识别，不会自动启动该服务 |
| `app/audio/` | 后端语音子系统：`controller.py`（播放控制）、`events.py`（socket 事件）、`service.py`（播放服务）、清单加载（`audio.registry`） |

### 3. 分析模块修改（识别与匹配）

| 目录 | 内容 |
|---|---|
| `app/core/` | 分析核心：`base_analyzer.py`、`audio/`（`speech_analyzer.py`、`real_speech_analyzer.py`）、`matchers/`（`speech_matcher.py`、`pose_matcher.py`）、`pipelines/`（`audio_pipeline.py`、`vision_pipeline.py`） |
| `app/behavior/` | 行为触发与匹配：`models.py`、`matchers` 的集成、触发规则、行为执行与降级 |
| `models/` | 模型文件（`pose_landmarker_lite.task` 等） |

### 4. 整合与后端开发（接口、录制、课程输出）

| 目录 | 内容 |
|---|---|
| `app.py` | 应用入口与启动装配 |
| `app/routes/` | HTTP API（V2 控制台、时间线、素材库、设备检查等） |
| `app/sockets/` | Socket 事件：`events.py`（play_resource 等）和处理器；Demo 不注册 `robot_events.py` 的机械/表情事件 |
| `app/robot/` | 兼容命名的课程输出协调器；只允许浏览器语音与儿童屏幕动画，不允许机械动作或完整版表情 |
| `app/storage/`、`app/services/`、`app/facade/`、`app/contracts/` | 数据层、服务层、门面与契约 |
| `app/config.py`、`config/`、`database/`、`scripts/`、`tests/` | 配置、数据模型与 seed、运维脚本、测试 |

### 其他（所有角色共享）

- `robot_runtime/` 中尚存的上游兼容测试源码不是 Demo 部署入口；Demo 已删除 Runtime/DollSer 打包入口，且不得启动、配置或发布这些源码。
- `static/resources/Animations/` 是儿童屏幕动画库，允许保留；`static/resources/Emotions/`、`doll/Pose/` 和动作/完整版表情清单不得出现在 Demo 发布内容中。
- `docs/`：项目文档（新增/修改功能时同步更新对应指南）

**协作约定**：功能改动后运行 `python -m pytest tests -q` 与本模块相关用例；接口变更通知"整合与后端开发"角色同步契约（`docs/CONTRACT.md`）；素材新增通知前端与语音角色更新清单。

## 日志与诊断

- `logs/app.log` —— 全部模块日志（socket 事件、录制、机器人服务）自 2026-08-10
  起统一追加到此文件；控制台显示 `INFO`，文件保留 `DEBUG`。
- `static/recordings/sessions/<课程目录>/full_interaction_timeline.jsonl` ——
  教师/儿童点击、课程输出事件与每条 `play_resource_ack` 的全量审计流
  （详见 [运维手册](docs/OPERATIONS.md#application-logs)）。
- 排查"点了没反应"：在 `app.log` 中搜索 `play_resource 收到` / `行为繁忙拒绝`
  / `回执`，并按 `requestId` 在时间线中交叉核对。

## 文档索引

- [文档总览](docs/README.md) —— 现行指南与归档设计历史
- [Demo 同步与部署规范](docs/DEMO_SYNC.md) —— 完整版更新同步矩阵、禁止项与全新拉取验收
- [架构](docs/ARCHITECTURE.md) —— 六大模块与依赖约束
- [协作工作区](docs/COLLABORATION.md) —— 前端/后端/语音/模型的职责与接口规则
- [契约](docs/CONTRACT.md) —— HTTP、Socket、运行端与兼容性规则
- [数据模型](docs/DATA_SCHEMA.md) —— SQLite、会话、轨道与时间线
- [配置](docs/CONFIGURATION.md) —— 环境变量、设备配置与素材
- [运维](docs/OPERATIONS.md) —— 健康检查、备份、升级与回滚
- [扩展](docs/EXTENDING.md) —— 设备、模型、对话与交互配置
- [测试](docs/TESTING.md) —— 假设备、契约测试与发布门禁
- [当前架构](docs/ARCHITECTURE.md) —— 当前模块边界与依赖方向

历史过程由 Git 历史保存。切勿重置或清理包含 `database/app.db`、录制、日志或课程素材的部署。
