# 第二阶段：公共接口与数据契约

## 1. 版本和命名

内部 Python DTO 使用 snake_case；旧 HTTP/Socket 仍使用现有 camelCase/snake_case 兼容字段，由 facade presenter/adapter 转换。新增 DTO 默认 `schema_version=1`，新增字段只允许可选，不能删除或改名旧字段。所有时间字段明确单位和基准：媒体排序使用 session 内单调秒，跨进程对齐额外记录 UTC ISO 墙上时钟和 `clock_domain`。

四类 ID 不得混用：

| ID | 含义 |
|---|---|
| `trainingSessionId` | 课程/训练语义，全场唯一 |
| `sessionId` / `mediaSessionId` | 媒体与 Runtime 采集语义，兼容旧字段 |
| `behaviorId` | 动作、表情、语音原子行为 |
| `requestId` | 请求幂等和重试关联 |

## 2. DTO

当前实现位于 `app/contracts/models.py`，字段如下：

| DTO | 必要字段与语义 |
|---|---|
| `TimePoint` | `monotonic_seconds`（秒，排序基准）、`wall_time_iso`（可选 UTC）、`clock_domain`、`sequence` |
| `SessionRef` | `session_id`、`training_session_id`、`media_session_id`，均允许暂缺以支持 prepare/补传阶段 |
| `DeviceRef` | `device_id`、`kind`、`device_type`、`runtime_id`、`enabled`、`required`、元数据；支持 Server/Runtime 的 0..N 设备 |
| `TrackRef` | `track_id`、`kind`、`role`、`device_id`、`runtime_id`、`required`、兼容 `filename`、`format` 和时钟域 |
| `AssetRef` | 逻辑 `asset_id + version`、`kind`、物理 `filename`、MIME、checksum、时长；逻辑引用不等于物理文件名 |
| `InteractionContext` | `course_id`、`course_type`、`item_id`、`question_id`、`event_key`、`scene_key`、`line_id`、`student_id`、`profile_version` |
| `SpeechCommand` | `command_id`、文本/音频素材、`line_id`、`behavior_id`、`SessionRef`、上下文、`pause_asr` 和元数据 |
| `EventEnvelope` | 事件名、payload、`request_id`、`behavior_id`、`SessionRef`、`TimePoint`、schema 版本；不包含 room 实现 |
| `ReadinessSnapshot` | `status`、`required_ok`、模块/设备结果、失败列表、session 和 schema 版本 |
| `ServerStatusSnapshot` | status 用例的内部字段；由 presenter 生成原有 `success/statistics/modelStatus/...` |

设备状态必须区分 `disabled/not_configured`、`optional`、`required`、`enabled`，不能因为缺少 optional 设备而伪造 required 成功。训练开始时冻结设备 profile，训练中的增删只影响下一场。

## 3. 稳定 Protocol

`app/contracts/ports.py` 当前定义以下最小端口：

| 领域 | Protocol | 责任 |
|---|---|---|
| 存储 | `SessionRepository`、`RecordingRepository`、`ContentCatalog` | session、连续录制/timeline、课程和内容读取 |
| 采集 | `DeviceRegistry`、`DeviceDiscoveryPort`、`DeviceBroker`、`CapturePort`、`CaptureSink` | 0..N 设备发现、自检、开关、采集生命周期和帧/音频上行 |
| 素材/交互 | `AssetLibrary`、`BatchImportService`、`InteractionProfileRepository`、`BehaviorResolver` | 逻辑素材版本、批量 staging/校验/提交、课程事件情境解析 |
| 计算 | `AnalysisEngine`、`ModelProvider`、`CourseProgression`、`DecisionEngine` | 分析模型、mock/real provider、课程推进和决策 |
| 语音/输出 | `DialoguePort`、`SpeechOutput`、`RobotCommandPort`、`EventPublisher` | 文本/音频入，SpeechCommand、机器人命令和跨块事件出 |
| 基础 | `Clock` | 单调时间与墙上时钟，不由业务自行调用系统时间 |

端口方法返回 Mapping 是第一阶段兼容过渡；新实现应逐步用版本化 DTO 替代无约束字典，但旧 payload 只能在 presenter 层转换。`start/stop/close` 相关实现必须幂等，线程、设备、队列和外部进程必须由唯一 owner 创建和关闭。

## 4. 错误语义

跨块使用 `ContractError`、`InvalidRequestError`、`ResourceUnavailableError`、`BusyError`、`NotReadyError`。它们只表达稳定分类和安全状态，不规定 HTTP 状态码。旧 route 继续保留各自的 400/404/409/500 和 `error` 字符串；统一错误 DTO 不在本阶段强行引入。

## 5. 旧契约映射

`present_server_status` 已证明把 `ServerStatusSnapshot` 映射为第一阶段 fixture 的完整字段集合。Socket adapter 只委托旧注册函数，不重新声明事件。后续迁移必须以 `contracts.snapshot.json` 和 `tests/test_phase1_*` 为回归基准。
