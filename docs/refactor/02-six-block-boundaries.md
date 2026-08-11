# 第一阶段：六块边界与职责表

## 1. 目标依赖方向

```text
前端 Web ──HTTP/Socket──> 后端门面 ──用例/Protocol──> 采集
                                      ├──────────────> 存储
                                      ├──────────────> 计算
                                      └──────────────> 语音对话

采集 ──采集 DTO/时间戳──> 存储
采集 ──FrameBatch/AudioBatch──> 计算
语音对话 ──SpeechCommand/InteractionContext──> 后端门面/计算的交互编排
计算 ──Observation/Decision/Report──> 存储/门面
```

运行代码只能依赖接口；具体 Flask、SocketIO、数据库、文件、硬件 SDK、模型 provider 和外部进程只能在各块 adapter/infrastructure 中出现。跨块共享只允许稳定 DTO、Protocol、事件信封、时间戳、错误类型和配置快照。

## 2. 六块职责与禁止事项

| 块 | 现有入口 | 第一阶段认定的职责 | 禁止事项 |
|---|---|---|---|
| 前端 Web | `teacher_frontend/src`、`templates`、`static/js` | 页面呈现、用户输入、权限可见性、HTTP/Socket client、重连和状态展示 | 直接读 DB/服务器路径、调用设备 SDK、决定课程评分或落盘 |
| 后端门面 | `app.py`、`app/routes`、`app/sockets` | 路由/事件注册、鉴权、输入校验、DTO 转换、用例编排、旧契约回包、room 投递 | 写媒体、执行评分公式、解析模型、直接驱动设备、承载长状态机 |
| 采集 | `app/recorder`、`app/queue`、`media_service`、agent、Runtime、ambient | 设备发现、自检、采样、缓冲、上行、补传、背压、设备生命周期和采集质量 | 决定课程、动作、评分、LLM、最终目录命名或业务报告 |
| 存储 | `app/session`、`recording_timeline`、`app/storage`、`behavior/store`、DB、内容库 | session、媒体轨道、meta/timeline、结果/报告、DB、原子写入、历史读取和内容索引 | 依赖 Flask request/Socket room、选择动作或执行模型 |
| 计算 | `app/core`、`analysis_service`、`readiness_service`、`behavior`、`report` | 就绪、特征、分析器/匹配器、注意力/情绪/姿态、课程推进、评分、决策和报告 | 主对话 LLM、直接 emit 前端事件、直接操作 DB 文件和硬件 |
| 语音对话 | `app/dialogue`、`app/audio`、voice-service、儿童端 TTS | 唤醒、ASR、页面上下文、对话 LLM、TTS、固定话术和 SpeechCommand | 直接修改课程状态、直接选 robot 设备、直接写 session 文件或绕过行为屏障 |

## 3. 当前代码归属与违规依赖

### 后端门面超载

- 根 `app.py` 同时是启动入口、依赖装配、DB 初始化、Blueprint 注册、Socket 注册、分析回调和约 70 个路由。
- `app/sockets/events.py` 约 3413 行，混合房间、在线状态、请求幂等、课点、ready、录制、互动课、评分、行为 ACK 和广播。
- `app/sockets/handlers.py` 约 1280 行，同时引用 session、queue、media、analysis、behavior、timeline。

### 采集/存储交叉

- `app/services/media_service.py` 同时拥有 recorder、queue 和 session 生命周期；`recording_timeline.py` 同时注册目录、创建目录、写 CSV/JSON 和管理 active registry。
- `app/routes/media_upload.py` 直接查 session manager 并调用 handler，Runtime HTTP 上行与存储协议耦合。
- `app/monitor/ambient_camera.py` 是设备发现、线程、帧缓存、控制和预览的一体化单例。

### 计算/交互交叉

- `analysis_service.py` 直接接收回调、触发行为、读取 behavior context，并管理 vision/audio pipeline。
- `app/core/actions.py` 直接导入 robot、session、audio，执行动作、音频和行为互斥。
- `feedback_service.py` 直接持有 SocketIO，用于发送分析、注意力、结果和 trigger 事件。
- `report/service.py` 直接依赖 behavior store；报告、行为和分析结果的持久化边界不统一。

### 语音/门面/机器人交叉

- `dialogue/sockets.py` 直接注册 Socket 事件并 emit；`audio/service.py` 同时判断 TTS 模式、课程类型、语音资源和 robot offset。
- `app.py` 直接初始化 dialogue/audio；`core/actions.py` 和 `audio/controller.py` 通过局部 import 访问 robot 和 session。
- `robot_service.py` 约 1391 行，同时管理动作存储、播放、情绪、映射、行为互斥、Runtime 和 Socket 回调。

## 4. 共享状态所有权清单

| 状态 | 当前所有者 | 风险 | 迁移要求 |
|---|---|---|---|
| `_play_request_cache` | `app/sockets/events.py` | 进程内、TTL/容量/锁隐式 | 保持 requestId 语义，后续抽为 IdempotencyPort |
| `_teacher_rating_cache` | `events.py` | ACK 与重复提交耦合 | 保留 TTL/返回字段，抽为幂等用例 |
| session manager registry | `app/session/session_manager.py` | 训练/媒体 session 混用 | 明确 sessionId/trainingSessionId/mediaSessionId，不改变旧字段 |
| recording path/active maps | `recording_timeline.py` | 目录与文件写入分散 | 由 RecordingRepository/TimelineRepository 统一所有权 |
| video/audio/result queues | `app/queue` | 丢帧策略和线程生命周期隐式 | 保留容量、顺序、丢弃策略和 close 幂等 |
| analyzer/matcher registry | `app/core/registry.py` | auto-register 与配置模式相互影响 | 通过 ModelRegistryPort 暴露，保留 mock/real 开关 |
| behavior mutex/sequence | `robot_service.py`、`core/actions.py` | 音频/动作/表情原子性依赖隐式回调 | 由 BehaviorExecutionPort 所有，输出 resolution/commit trace |
| dialogue/page context | `dialogue/page_context_store.py` | 课程/题目切换需清理历史 | 由 DialogueContextPort 所有，保持 fingerprint 规则 |
| ambient singleton/thread | `monitor/ambient_camera.py` | 只能单设备、stop 释放风险 | 迁移到 DeviceRegistry/DeviceBroker，保持旧 API adapter |

## 5. shared contracts 最小范围

允许新增：

- `SessionRef(sessionId, trainingSessionId, mediaSessionId)`；
- `TrackRef(trackId, deviceId, kind, role, required, filename, clock)`；
- `InteractionContext(courseId, courseType, itemId, questionId, eventKey, sceneKey, lineId, studentId)`；
- `BehaviorPlan`、`SpeechCommand`、`Observation`、`Decision`、`ReadinessSnapshot`；
- `EventEnvelope(event, requestId, behaviorId, sessionId, timestamp, payload)`；
- 可分类的错误类型、超时/取消结果和质量状态。

禁止在 contracts 中放置 SQLAlchemy model、Flask request、SocketIO emit、路径拼接、动作选择、课程 if/elif、模型推理或硬件调用。

## 6. 边界验收

- 可用 fake adapter 单独测试采集、存储、计算和对话。
- 关闭新增 adapter 后旧 facade 仍可运行。
- 领域模块不 import Flask/SocketIO；门面不 import recorder 内部实现、LLM provider 或数据库查询细节。
- 所有后台线程/外部进程有明确 start owner、stop owner、超时、异常通知和幂等 close。
- 控制端只能通过 API 看到 device/track/storage/resolution 状态，不能访问任意文件路径。
