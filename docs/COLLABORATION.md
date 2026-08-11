# 项目协作与工作区

本文是新协作者的最短入口。项目当前采用**单仓多工作区**：教师端 React 已具备独立
构建边界；儿童端、机器人表情页和管理页仍由 Flask 同源托管。不要把当前状态描述为
“前后端已经完全分仓”，也不要在没有契约测试的情况下移动目录。

## 1. 前端工作区

| 客户端 | 工作区 | 入口 | 说明 |
|---|---|---|---|
| 教师端 | `teacher_frontend/` | `teacher_frontend/App.tsx` | React + TypeScript + Vite，唯一独立前端构建工作区 |
| 儿童端 | `templates/child.html`、`static/js/child*.js`、`static/css/child.css` | `/child` | Flask 托管的浏览器客户端，不属于 React 工作区 |
| 机器人表情端 | `templates/robot/`、`static/robot/` | `/robot/emotion` | 浏览器播放器，与 Robot Runtime 通过本机 HTTP 配合 |
| Server 管理页 | `templates/server/`、`static/js/config_*.js`、`static/css/server*.css` | `/server` | Flask 托管的运维和配置客户端 |

教师端开发：

```powershell
cd teacher_frontend
npm ci
npm run dev
```

提交前执行 `npm.cmd run build`。不要修改或提交 `teacher_frontend/dist/` 和
`teacher_frontend/node_modules/`。前端只能通过 HTTP、Socket.IO 和静态资源 URL 使用
后端能力，不能读取数据库、服务器文件路径或导入 Python 实现。

## 2. 后端工作区

后端工作区是仓库根目录和 `app/`：

- `app.py`：当前组合根、Flask/SocketIO 启动和少量兼容路由。
- `app/routes/`、`app/robot/routes.py`：HTTP API facade。
- `app/sockets/`、`app/dialogue/sockets.py`：Socket.IO transport 和房间路由。
- `app/services/`、`app/session/`、`app/behavior/`：应用服务与会话编排。
- `app/acquisition/`、`app/storage/`、`app/computation/`、`app/dialogue/`：新边界实现。
- `database/`：数据库模型、初始化和迁移工具。
- `robot_runtime/`：机器人 Windows Runtime，独立进程、独立打包，不是 Flask 内部模块。

启动和只读环境检查：

```powershell
.\start_server.ps1 -CheckOnly
.\start_server.ps1
```

新业务不要继续堆进 `app.py` 或大型 Socket handler。HTTP/Socket 只做认证、校验、DTO
转换和调用应用服务；业务规则应进入相应领域工作区。

## 3. 语音与模型工作区

### 语音

| 职责 | 工作区 |
|---|---|
| 独立 FunASR HTTP 服务 | `tools/voice-service/` |
| 后端 ASR/对话/LLM 编排 | `app/dialogue/` |
| 课程语音资产和播放编排 | `app/audio/` |
| 儿童端采集与浏览器 TTS | `static/js/child_dialogue.js`、`static/js/browser_tts.js` |
| 自动启动 voice-service | `app/utils/voice_service_launcher.py` |

FunASR 模型运行缓存位于 `.runtime/models/voice/`，不提交 Git。语音服务对外只暴露
`GET /health`、`POST /stt`、`POST /tts`；Server 通过
`VOICE_PYTHON_SERVICE_URL` 调用，不应导入 voice-service 的内部对象。

### 分析模型

- 模型插件和推理实现：`app/core/`、`app/computation/model_plugins.py`。
- 模型接口：`app/contracts/ports.py` 中的 `AnalysisModel`、`ModelProvider`。
- 小型、允许入库的模型资产：`models/`。
- 模型配置：`config/analyzers.yaml` 和环境变量。
- 下载缓存、权重和本机运行文件：`.runtime/`，不得提交。

新增模型必须实现 `prepare / health / analyze / close`，通过 registry 或组合根注入；模型
代码不能导入 Flask、Socket.IO、具体数据库、录制器或机器人实现。

## 4. 对接层、接口和规范

### 接口定义位置

| 接口类型 | 权威位置 |
|---|---|
| 跨模块 DTO、事件信封、时间点 | `app/contracts/models.py` |
| 可替换端口/Protocol | `app/contracts/ports.py` |
| 可分类错误 | `app/contracts/errors.py` |
| HTTP API | `app/routes/`、`app/robot/routes.py`，兼容路由暂留 `app.py` |
| Socket.IO 服务端事件 | `app/sockets/`、`app/dialogue/sockets.py` |
| 交互计划 schema | `docs/refactor/33-interaction-plan-schema.md` |
| 机器可读接口清单 | `docs/refactor/contracts.snapshot.json` |
| 所有权和追踪矩阵 | `docs/refactor/traceability.matrix.json` |

`app/contracts/` 必须保持无框架：不得出现 Flask、Socket.IO、SQLAlchemy、文件路径、
设备 SDK 或业务决策。浏览器端目前没有自动生成的 TypeScript SDK，因此 HTTP/Socket
字段变更必须同时修改服务端 fixture 和对应客户端类型/解析代码；这是当前最主要的协作
风险之一。

### 传输规范

1. 新接口优先使用 `/api/v2/...`，统一 JSON；旧接口只做兼容，不在旧格式上继续扩张。
2. 同一次行为必须传递 `sessionId`、`trainingSessionId`、`requestId`、`behaviorId`；不得用
   “当前最新行为”猜测回执归属。
3. Socket 行为只发到明确的 session/role room；找不到目标时失败，不允许全局广播兜底。
4. 时间字段必须注明时钟域和单位，例如 `actualAtClientMs`、`startAtServerMs`；持续时间统一
   使用 `...Ms`。
5. 命令必须有 accepted/ready/started/terminal 生命周期，terminal 处理必须幂等。
6. 新字段可增量添加；删除、改名或改变状态码/事件顺序前必须提供兼容期和迁移说明。
7. 外部服务通过端口或 HTTP adapter 接入，领域层不能直接依赖 transport 实现。

### 接口变更顺序

1. 先改 DTO/Protocol、接口清单和契约 fixture。
2. 再改后端 adapter/handler，并保留旧调用兼容。
3. 再改前端或 Runtime consumer。
4. 增加成功、失败、重试、重复回执和断线恢复测试。
5. 最后更新 `docs/CONTRACT.md` 和追踪矩阵。

## 5. 协作与合并门禁

建议按 `frontend/*`、`backend/*`、`voice/*`、`model/*`、`contract/*` 创建功能分支。一个
PR 尽量只跨一个所有权边界；必须跨边界时，先提交契约，再分别提交 producer 和
consumer，避免其他协作者面对半套接口。

合并前至少执行：

```powershell
python -m pytest tests -q
cd teacher_frontend
npm.cmd run build
```

涉及启动、语音、模型或 Runtime 时，还要执行对应健康检查和真实设备 smoke test。不得
提交 `.env`、数据库、日志、录制、`.runtime/`、`node_modules/`、`dist/` 或机器人发布
ZIP。课程资源和小型模型确需入库时，单文件必须低于 GitHub 限制，并在 PR 中说明来源、
许可和 SHA-256。

## 当前分离结论

- **可并行协作**：教师端、后端、语音服务、模型和 Robot Runtime 已有清晰目录边界。
- **尚未完全物理分离**：儿童端、机器人表情端和管理页仍与 Flask 模板/静态目录共仓；
  `app.py` 和部分 legacy Socket handler 仍是迁移期兼容入口。
- **推荐做法**：现阶段保持单仓，通过契约和 CODE REVIEW 隔离变更。等客户端契约可自动
  生成、`app.py` 只剩组合根、legacy handler 被 adapter 替代后，再讨论拆仓。
