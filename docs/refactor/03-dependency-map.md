# 第一阶段：依赖图、线程与外部资源所有权

## 1. 当前依赖图（按运行链路）

```text
app.py
 ├─ Flask/CORS/SocketIO + database.models.db
 ├─ app.config
 ├─ app.session.get_session_manager
 ├─ app.services.media/analysis/feedback
 ├─ app.core.auto_register/config_manager/trigger
 ├─ app.dialogue + dialogue.sockets
 ├─ app.audio + audio_events
 ├─ app.robot.routes/robot_service/runtime_registry
 ├─ app.routes.media_upload/report/monitor/config_content/server_config_files
 └─ app.sockets.events/handlers/robot_events

Socket facade
 ├─ handlers
 │   ├─ session_manager / Session
 │   ├─ media_service / recorder / queue
 │   ├─ analysis_service / feedback_service
 │   ├─ behavior_service / recording_timeline
 │   └─ dialogue page context / audio / robot（局部 import）
 ├─ readiness_service
 ├─ dialogue.sockets → dialogue.service/stt/page_context/phrases
 ├─ audio_events → audio emitter/controller/service
 └─ robot_events → robot_service/motion/emotion/runtime

Media
 ├─ MediaService → SessionManager + Video/AudioRecorder + queues
 ├─ media_upload → SessionManager + MediaService/path registry
 ├─ child_media_agent/robot_runtime → HTTP media upload + Runtime register/heartbeat
 └─ ambient_camera → OpenCV device + preview cache + background thread

Computation
 ├─ AnalysisService → buffer/accumulator/vision pipeline/audio pipeline/trigger
 ├─ pipelines → analyzer/matcher registry + config manager
 ├─ FeedbackService → result queue/storage + SocketIO callback
 ├─ BehaviorService → behavior store/timeline/camera config
 └─ ReportService → behavior store/scoring/narrative/archive sync

Dialogue/Audio
 ├─ DialogueService → phrases/page context/STT/HTTP voice provider
 ├─ dialogue.sockets → page context + dialogue service + SocketIO
 ├─ AudioService → audio emitter + dialogue phrases + robot audio offset
 └─ AudioController/Actions → SocketIO + robot service + session state
```

## 2. 允许的目标依赖

```text
facade → application use cases → domain ports
infrastructure adapters → domain ports
frontend → facade HTTP/Socket contracts
acquisition → storage ports / computation input ports
computation → storage read/write ports / behavior ports
dialogue → speech provider ports / interaction context ports
```

以下依赖应在迁移中逐步消除或包在 adapter 内：

| 当前依赖 | 问题 | 目标替代 |
|---|---|---|
| `app.py → 所有服务/具体蓝图/数据库` | import 即装配，测试和启动耦合 | composition root 只组装 Port 实现；旧 `app.py` 保留 adapter |
| `events.py → handlers + service 细节` | Socket 事件承担业务编排 | `TrainingUseCase`、`RoomDeliveryPort`、`IdempotencyPort` |
| `handlers.py → recorder/timeline/queue` | 门面可直接改变落盘与采集生命周期 | `RecordingLifecyclePort`、`TimelinePort` |
| `routes/media_upload.py → session/handlers` | 上行协议和 session/文件实现耦合 | `MediaIngestPort`、`SessionLookupPort` |
| `readiness_service → media/queues/analysis` | 就绪门无法在正式开录前独立自检 | `PreflightPort`、`DeviceHealthPort`、`ModelHealthPort` |
| `analysis_service → trigger/behavior/report` | 分析、决策、执行和报告互相回调 | `ObservationPipeline`、`DecisionPort`、`ReportPort` |
| `core/actions.py → robot/audio/session` | 行为原子屏障依赖具体设施 | `BehaviorExecutionPort` + `SpeechCommand` |
| `feedback_service → SocketIO` | 领域服务直接知道 transport | `FeedbackEvent` 交给 facade emitter |
| `dialogue.sockets → service/STT/page store` | Socket handler 兼任对话用例 | `DialogueUseCase` + facade adapter |
| `audio/service.py → robot_service` | 语音播放偏移与机器人实现耦合 | `AudioOffsetPort`/统一 `BehaviorPlan` |
| `robot_service → mapping/files/runtime/SocketIO` | 动作库、绑定、设备、传输混成大服务 | `AssetRepository`、`MappingResolverPort`、`RobotTransportPort` |
| `routes/config_content.py → SQLAlchemy + robot` | 内容 API 同时管理 DB、文件、动作资源 | `CourseContentPort`、`AssetLibraryPort` |

## 3. 线程、队列、锁和外部进程

| 资源 | 当前位置 | 所有权/关闭要求 |
|---|---|---|
| MediaService 消费线程 | `app/services/media_service.py` | 服务单例创建；停止时关闭 video/audio recorder 和 queue，不能重复启动 |
| Video/Audio/Result queue | `app/queue/*.py` | 有界队列；保持现有丢弃/阻塞策略、顺序和统计字段 |
| Recording timeline maps | `recording_timeline.py` | RLock 保护；finalize 后保留补传可解析的路径映射，显式 unregister |
| Readiness timers/probe thread | `readiness_service.py` | generation/cancel 防止旧 gate 回写；超时/取消必须停止回调 |
| Analysis threads | `analysis_service.py`、pipelines | 按 session 隔离；end_session 后不再接受帧，释放模型/缓冲 |
| Robot worker/behavior mutex | `robot_service.py`、`motion_player.py` | reserve/prepare/commit/abort；stop 幂等，busy 不泄漏 audio/visual |
| Ambient camera thread | `ambient_camera.py` | 当前单例；控制关闭必须 release OpenCV capture、清空预览并可再次启动 |
| Voice-service 子进程 | `voice_service_launcher.py`、`tools/voice-service` | 由启动器所有；记录 pid/url/健康；退出 app 时 terminate/kill 有超时 |
| Robot Runtime 进程 | `robot_runtime/agent.py` | Runtime 自有采集与 OSC；后端只通过 register/heartbeat/HTTP/OSC 契约访问 |
| Browser media tracks | `static/js/child.js` | 浏览器负责权限/track stop；服务端不能假定浏览器存在或强制打开设备 |

## 4. 关键状态和跨进程边界

- `trainingSessionId` 是课程/训练语义；`sessionId`/`mediaSessionId` 是整场媒体/运行时语义；`behaviorId` 是动作/表情/语音原子行为；`requestId` 是幂等请求。四类 ID 不得在重构中混用。
- 浏览器模式通过 Socket `video_frame`/`audio_chunk` 上行；agent 模式通过 `/api/media/...` 实时上行并可 `/upload` 补传；两者最终进入同一 session/timeline 语义。
- Robot Runtime 注册后由 `runtime_registry` 维护 advertised URL、heartbeat 和版本；不可把 Runtime 内部线程搬入 Flask 进程。
- 数据库连接由 SQLAlchemy `db` 所有；行为 store/recording timeline 的 JSON/CSV 文件不能绕过各自 repository 直接写。

## 5. 审计后的迁移约束

1. 不在本阶段修改上述依赖，不做大文件拆分。
2. 第二阶段只新增 Protocol、DTO、composition root adapter 和契约测试；旧 import 保留。
3. 任何切片迁移前先为调用者加 characterization test，迁移后用旧/新双算或 shadow 比较。
4. 若依赖图中某条边无法移除，必须在 ADR 中写明原因、所有权和未来边界，不以“放进 shared”掩盖。
5. 依赖图的下一版必须由静态 import 扫描和运行时线程/单例快照共同更新，而不是只凭目录名称。
