# 项目协作规范

本文是本仓库当前状态的协作入口。它描述“现在如何工作”，不是重构计划，也不替代接口和数据格式的事实文档。如果文档与代码或测试冲突，以代码和测试为准，并在本文中补充确认后的结论。改动需要找到根源问题并解决而不是单纯补丁。历史阶段资料由 Git 历史保存，不在工作树重复保留。

## 0. Demo 机硬边界

本仓库是与完整版本目录、Git 工作树和部署包相互独立的 Demo 产品。同步完整版本更新前必须阅读 `docs/DEMO_SYNC.md`，不得整目录覆盖。

- 唯一启用课型为 `mimic`、`pairing`、`ordering`；课程选择、配置、预设、采集分析和新报告都只能投影这三类。
- `config/demo_course_scope.json` 是课程范围事实源，`config/demo_deployment.json` 是部署能力事实源；二者非法或缺失时必须安全收紧，不能扩大权限。
- Demo 没有机械结构，不注册机械 Socket 事件，不启动 Robot Runtime，不提供动作接口/页面/资产，也不消费完整版本的表情协议或表情素材。
- `static/resources/Animations/` 是儿童屏幕鼓励动画，不属于机器人表情，必须保留。浏览器语音、儿童页面、采集、分析、教师评分和报告流程保持正常。
- `app/robot/` 名称只为旧课程输出契约兼容；生产实例必须固定 `disabled`，输出计划只能含语音和儿童屏幕动画。
- 更新完整版本时，先同步通用修复，再逐项重施上述边界，最后执行 `docs/DEMO_SYNC.md` 的全套验收。

## 1. 开始工作前

1. 先运行 `git status --short`，确认工作区已有修改。已有修改属于当前操作者，不得覆盖、回滚或格式化。
2. 阅读本文件，以及与任务直接相关的 `docs/CONTRACT.md`、`docs/DATA_SCHEMA.md`、`docs/TESTING.md`。
3. 给任务声明边界：准备修改的目录、不会修改的目录、需要同步的接口或资源。
4. 同一工作区只能有一个操作者同时写同一个文件。若发现别人正在修改目标文件，停止对该文件的编辑，先协调或改为只读检查。

## 2. 工作区所有权

| 工作区 | 当前职责 | 典型改动 |
|---|---|---|
| `teacher_frontend/` | 教师端 React/Vite 页面 | 页面、交互、前端 API/Socket 调用和类型 |
| `templates/`、`static/` | 儿童端、Server 控制台、Robot 页面及静态资源 | Flask 模板、页面脚本、样式、浏览器采集 |
| `app/routes/`、`app/sockets/`、`app.py` | HTTP/Socket 接入和应用组装 | 校验、鉴权、DTO、事件转发；不要在这里堆业务规则 |
| `app/acquisition/`、`app/recorder/` | 采集、设备、录制生命周期 | 设备检查、轨道启动/停止、上行处理 |
| `app/storage/`、`database/` | SQLite、会话文件、时间线、报告和资源目录 | repository、文件布局、元数据、迁移 |
| `app/computation/`、`app/behavior/`、`app/report/` | readiness、分析、评分、行为和课程交互解析 | 业务决策、评分公式、InteractionProfile/legacy 兼容 |
| `app/dialogue/`、`app/audio/`、`tools/voice-service/` | ASR/LLM/TTS、语音播放和语音服务 | provider、超时、降级、语音资产 |
| `app/robot/`、`robot_runtime/`、`doll/` | Demo 兼容层与被禁用的完整产品源码 | 不得启用 Runtime、机械动作、完整版表情；仅保留课程输出兼容与儿童动画引用 |
| `config/`、`doll/data/` | 可审阅的课程、交互、语音和 Demo 能力配置 | YAML/JSON/CSV；配置变更必须说明兼容性 |
| `tests/` | 当前行为和接口的自动化证据 | 与改动同提交测试，不删除或放宽既有断言 |

不要把数据库、录音、日志、`.env`、`.runtime/`、`node_modules/`、构建产物或发布 ZIP 当作源码工作区。它们不应提交，也不应为“清理工作区”而删除。

## 3. 当前架构边界

生产入口仍是 `app.py`，负责 Flask/SocketIO 启动和兼容注册；`app/facade/bootstrap.py` 是组合骨架，不是唯一生产入口。教师端生产页面由 Flask 在 `/teacher/` 提供，Vite 的 5173 端口只用于开发。

依赖方向保持为：

```text
前端 -> 接入层 -> {采集, 存储, 计算, 对话}
采集 -> contracts + storage ports
计算 -> contracts + acquisition/storage ports
对话 -> contracts + speech/robot ports
存储 -> contracts
```

`app/contracts/` 只能放无框架依赖的 DTO、Protocol、事件信封、时间点和错误语义。领域层不得直接依赖 Flask、SocketIO、数据库会话、具体硬件或文件传输实现；跨边界通过 port/adapter。

## 4. 现在的业务事实

### 课程与交互

- 主流程是 `登录 -> 选学生/课程 -> prepare_training -> readiness -> play_resource/提问 -> 对话/分析 -> 教师评分 -> finalize -> 报告`。
- legacy 课程行为来自 `doll/data/course_map.json` 及相关课程/语音资源；已发布的 `InteractionProfileV2` 才能由 `app/computation/interaction/` 解析。draft、非法或未命中的 profile 必须回退 legacy。
- 行为必须携带并校验 `sessionId`、`trainingSessionId`、`behaviorId`、`requestId`；Socket 只发到明确的 session/role room，不能用全局广播兜底。
- 一个训练会话内切换课点只追加时间线，不重启连续录制。重复请求、取消、忙碌、断线重连和浏览器晚到补传必须保持幂等或明确失败。
- 修改课程交互、事件名、儿童动画/语音绑定或发布规则时，必须同步 `docs/CONTRACT.md`、对应 fixture 和相关教师端/儿童端消费方。

### 存储

- SQLite 位于 `database/app.db`，部署时原地升级；不得通过重置数据库解决问题。
- 会话文件位于 `static/recordings/sessions/<课程目录>/`。兼容文件名 `video.avi`、`audio.wav`、环境轨、`timeline.csv`、`session_meta.json`、`archive_meta.json` 不得随意改名或替换为 MP4。
- 行为审计写入 `interaction_timeline.jsonl`；完整交互审计写入 `full_interaction_timeline.jsonl`。时间戳以会话单调时钟为准，墙上时钟只作元数据。
- 存储校验器是只读的；不要自动修复、移动或删除历史会话。文件和配置写入使用临时文件、`fsync`、原子替换。

## 5. 修改规则

- 先改事实源和契约，再改 adapter/handler，最后改前端或 Runtime consumer；新增字段优先向后兼容，删除/改名必须给出迁移期。
- 不顺手重命名目录、升级框架、格式化整仓库或清理历史文档。
- 资源变更要检查引用保护、文件格式、大小和来源；MP4 资源需同步索引/课程引用。
- 任何跨边界改动都要补最小测试。常规门禁：`python -m pytest tests -q`；教师端改动再运行 `cd teacher_frontend; npm.cmd run build`。

## 6. 完成改动时必须说明

提交或交接前，在 PR/提交说明/任务回复中写明：

```text
改动范围：<目录和文件>
验证：<运行的测试、构建或人工检查>
影响：<对课程交互、采集/存储、教师端、儿童端、语音、机器人 Runtime、报告的影响；无影响也要明确写出>
契约变化：<无 / 新增字段 / 行为变化 / 迁移方案>
协作者提示：<其他人需要同步修改或避开的文件>
```

如果改的是共享规范（课程流程、接口、存储文件名、事件、配置 schema、评分规则），必须在影响中明确提醒所有相关工作区，并先更新事实文档和测试证据。规范可以被修改，但不能悄悄修改。

## 7. 文档规则

当前规范只写在根目录 `AGENTS.md` 和 `docs/` 的事实文档中：`CONTRACT.md`、`DATA_SCHEMA.md`、`TESTING.md`、`CONFIGURATION.md`、`OPERATIONS.md` 及对应专题。机器可读的契约快照位于 `tests/fixtures/contracts/`，只供自动化测试使用，不是开发计划；新增规则不要写入 fixture。
