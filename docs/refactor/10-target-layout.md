# 第二阶段：目标目录与六块骨架

## 1. 本阶段边界

本阶段建立目录、无框架契约、轻量 composition root、首个 facade vertical slice 和架构守卫，不搬迁训练、录制、Socket 业务实现，不修改页面或产品默认值。旧入口仍是生产入口，新增骨架必须可以关闭或绕过。

当前工作区基线：分支 `add_voice`，HEAD `6836cbffa882e768912cb96e9d2f7bcd01f13d4c`，`python -m pytest tests -q` 为 `243 passed`（warnings only）。工作区原有用户/运行时改动保留，未执行 reset、clean、checkout 或数据删除。

## 2. 目标目录

```text
teacher_frontend/                  前端 Web：教师端 React/Vite
templates/                         前端 Web：儿童、监控、配置、报告页面
static/js/                         前端 Web：旧页面、儿童端和浏览器采集

app/
├─ contracts/                      六块共享的纯 DTO/Protocol/错误/事件信封
├─ facade/                         后端门面
│  ├─ bootstrap.py                 轻量 composition root 注册骨架
│  ├─ application.py               可替换、可关闭的应用容器
│  ├─ use_cases/                   应用编排用例
│  ├─ presenters/                  旧 HTTP/Socket 回包呈现
│  ├─ routes/                      逐条迁移的 HTTP route adapter
│  └─ sockets/                     逐组迁移的 Socket 注册/事件 adapter
├─ acquisition/                    采集块目标边界
├─ storage/
│  ├─ repositories/                session、recording、结果、报告 repository
│  └─ content_catalog/             CSV/YAML/静态媒体只读内容库
├─ computation/                    计算块目标边界
├─ dialogue/                       语音对话块（现有实现保留）
├─ recorder/、queue/、monitor/     现有采集基础设施，暂由旧 adapter 提供
├─ core/、services/、behavior/     现有计算/行为基础设施，暂由旧 adapter 提供
└─ sockets/、routes/               旧门面入口，逐步变为兼容 shim

app.py                             兼容启动入口和暂未迁移的旧 route/装配
```

`contracts` 不是第七个业务块，只能容纳跨块稳定数据和接口。任何课程 if/elif、文件路径拼接、SQLAlchemy model、Flask request、Socket room、硬件调用或模型推理都不得放入其中。

## 3. 允许依赖方向

```text
前端 Web ──HTTP/Socket──> facade
facade ──use case/port──> acquisition / storage / computation / dialogue
acquisition ──采集 DTO/端口──> storage、computation 输入端口
computation ──结果/决策端口──> storage、facade、RobotCommandPort
dialogue ──SpeechCommand/InteractionContext──> facade/行为编排
基础设施 adapter ──实现──> contracts Protocol
```

允许 facade 依赖各块公开端口；各业务块不得反向 import `app.facade`、Flask、SocketIO 或具体 transport。旧代码中尚存的违规边应留在明确的 legacy adapter 中，并在迁移日志和依赖图中记录，不得用 `shared` 隐藏。

## 4. 首个真实使用切片

`GET /api/server/status` 保留在 `app.py` 的旧 route 装饰器和 endpoint 名称，但函数内部通过：

```text
app.py route
  → ApplicationContainer
  → ServerStatusUseCase
  → ServerStatusSnapshot
  → present_server_status
  → 原 success + camelCase JSON
```

该切片不改旧依赖的取得方式、异常捕获、日志和状态码。`register_socket_events` 也只增加一层显式 legacy adapter，注册函数调用一次，事件集合和顺序不变。训练、播放、评分、录制和机器人事件仍由旧入口直接拥有。

## 5. 旧实现兼容策略

- `python app.py`、现有 URL、Blueprint 前缀、Socket 注册函数和历史 import 路径继续保留。
- 旧 service/singleton 暂不改身份；新容器只保存用例和可替换端口，不复制设备、线程、队列或数据库连接。
- 新路由逐条迁移；每次迁移前后比较 HTTP/Socket 字段、状态码、room、ack 和异常形态。
- 新交互、设备、素材和模型能力均先 shadow/preview，再按开关灰度；未命中、未发布或异常继续回退 legacy。
- 任何核心链路出现差异，立即撤回当前 adapter，并保留 characterization test 作为阻断证据。
