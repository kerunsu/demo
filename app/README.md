本目录为 Flask 应用的核心 Python 包，与根目录 `app.py` 组合运行。
# 目录结构（与实现对齐）

app/
├── config.py           # 全局配置（环境变量见 docs/ENVIRONMENT.md）
├── session/            # 会话模型、SessionManager、过期清理
├── sockets/            # Socket.IO 注册与事件处理（视频帧、音频块、资源播放等）
├── services/           # media_service、analysis_service、feedback_service
├── queue/              # 视频/音频/结果队列
├── recorder/           # 音视频录制与 media_recorder 编排
├── core/               # 分析器/比对器、registry、auto_register、pipelines、trigger、vision、audio、
matchers
├── storage/            # 分析结果落盘
├── audio/              # 语音清单、emitter/controller、与 Socket 协同
├── robot/              # 机械臂 Blueprint、OSC、动作录制/播放（可选）
└── utils/              # logger、exceptions、resource_utils 等

## 关键扩展点

- **分析器注册**：`app/core/auto_register.py` 在启动时注册各分析器/比对器；模式由 `config/analyzers.yaml` 
与 `USE_REAL_ANALYZERS` 控制。
- **分析流水线**：`app/core/pipelines/` 中 vision/audio 流水线消费队列并回调 `analysis_service`。
- **Socket 入口**：`app/sockets/events.py` 的 `register_socket_events(socketio)` 在 `app.py` 中调用；语
音、机械臂另有独立注册模块。

## 配置与日志

- 配置类：`app.config.Config`。
- 日志：`app/utils/logger.py`，默认写入项目 `logs/`（见 `.gitignore`）。

# `app/` 参考手册（按目录/文件/方法）

本目录为服务端核心 Python 包，负责**多端通信衔接（Socket/HTTP）**、**会话与录制**、**分析流水线与触发**、**结果反馈**、以及可选的**语音/机械臂**子系统。

> 说明：
> - 本文以“代码签名 + 文件头 docstring + 调用点”来写用途说明。
> - 对于超长模块中未逐行核验的实现细节，会标注 **（从命名/调用点推断）**，避免误导。
> - 项目对外 Socket 事件契约见 `docs/CONTRACT.md`。

---

## 0. 顶层模块

### `app/__init__.py`

- **全局变量**
  - `app`: 全局 Flask 实例（由 `create_app` 初始化）
  - `socketio`: 全局 SocketIO 实例（由 `create_app` 初始化）
- **create_app(config=None)**
  - **用途**：创建并配置 Flask + SocketIO；初始化数据库 `db.init_app(app)`。
  - **备注**：这是“可复用 app factory”；实际主入口仍是根目录 `app.py`。
- **get_app()**
  - **用途**：返回全局 Flask app（供脚本/模块使用）。
- **get_socketio()**
  - **用途**：返回全局 socketio 实例。

### `app/config.py`

- **Config（类）**
  - **用途**：集中管理服务端配置与路径；会创建 `static/recordings`、`static/results`、`static/temp`、`logs` 等目录。
  - **常用字段**：`SECRET_KEY`、`SQLALCHEMY_DATABASE_URI`、视频/音频采样参数、分析开关、队列大小、日志级别等。
  - **常用方法**
    - `get_recording_path(session_id)`: 只解析该 session 的录制目录；第一笔真实写入才创建目录
    - `get_result_path(session_id)`: 返回结果目录（并确保存在）
    - `get_video_file_path(session_id) / get_audio_file_path(session_id) / get_result_file_path(session_id)`: 拼接输出文件完整路径

---

## 1. 会话（session）

### `app/session/__init__.py`

- 主要暴露 `get_session_manager()`（见 `session_manager.py`）。

### `app/session/session_model.py`

- **SessionStatus（Enum）**
  - `CREATED / RECORDING / ANALYZING / COMPLETED / FAILED / CANCELLED`
  - **用途**：规范会话生命周期状态机。
- **Session（dataclass）**
  - **用途**：承载一次训练会话的关键字段（student/course/item、文件路径、统计计数、metadata、status、时间戳等）。
  - **方法**
    - `start()`: 从 CREATED → RECORDING，并写入 `started_at`
    - `stop()`: 从 RECORDING/ANALYZING → COMPLETED，并写入 `ended_at`
    - `fail(error_message=None)`: 标记 FAILED，并可写入 `metadata['error']`
    - `cancel()`: 标记 CANCELLED
    - `set_analyzing()`: 从 RECORDING → ANALYZING
    - `is_active()`: 是否处于 RECORDING/ANALYZING
    - `get_duration()`: 会话持续时间（秒）
    - `to_dict() / from_dict(data)`: 序列化/反序列化（供 JSON/存储使用）

### `app/session/session_manager.py`

- **SessionManager（类，线程安全）**
  - **用途**：管理内存中的 session 集合（创建、查询、结束、清理过期、并发限制）。
  - **方法**
    - `create_session(student_id=None, course_id=None, course_item_id=None, metadata=None) -> Session`
      - 创建新 session，并基于 `Config` 写入 video/audio/result 文件路径。
    - `get_session(session_id) -> Optional[Session]`
    - `update_session(session)`
    - `end_session(session_id, status=COMPLETED)`
    - `remove_session(session_id)`
    - `list_active_sessions() / list_all_sessions()`
    - `get_sessions_by_student(student_id) / get_sessions_by_course(course_id)`
    - `cleanup_expired_sessions()`: 超时策略，活动会话超时会被标记 fail
    - `get_statistics()`: 返回会话统计（total/active/completed/failed 等）
- **get_session_manager()**
  - **用途**：SessionManager 单例入口（线程安全初始化）。

---

## 2. 队列（queue）

### `app/queue/video_queue.py`

- **VideoQueue（类）**
  - **用途**：按 session 缓冲视频帧（用于录制与分析消费）（从命名与调用点推断）。

### `app/queue/audio_queue.py`

- **AudioQueue（类）**
  - **用途**：按 session 缓冲音频 chunk（用于录制与分析消费）（从命名与调用点推断）。

### `app/queue/result_queue.py`

- **ResultType（Enum）**
  - **用途**：结果队列项的类型分类（分析/匹配/注意力/触发等）。
- **QueuedResult（dataclass）**
  - **用途**：封装入队结果（类型、时间戳、payload）。
- **ResultQueue（类）**
  - **用途**：汇总并缓存结果，供反馈服务批处理/拉取（从命名与调用点推断）。
- **get_result_queue()**
  - **用途**：ResultQueue 单例入口。

### `app/queue/__init__.py`

- **get_video_queue() / get_audio_queue()**
  - **用途**：返回全局队列实例（供 sockets/media_service/pipelines 使用）。

---

## 3. 录制（recorder）

> 录制由 `MediaService` 驱动：Socket handler 把数据写入 queue，MediaService 消费 queue 并调用 MediaRecorder 写盘。

### `app/recorder/base_recorder.py`

- **BaseRecorder（ABC）**
  - **用途**：视频/音频 recorder 的统一抽象（start/stop/write/cleanup 等）（从命名推断，具体以实现为准）。

### `app/recorder/video_recorder.py`

- **VideoRecorder（BaseRecorder）**
  - **用途**：把视频帧编码并写入视频文件（依赖 `opencv-python`）（从文件名与依赖推断）。

### `app/recorder/audio_recorder.py`

- **AudioRecorder（BaseRecorder）**
  - **用途**：把音频 chunk 写入 wav 文件或中间格式（从文件名与调用点推断）。

### `app/recorder/media_recorder.py`

- **MediaRecorder（类）**
  - **用途**：组合 VideoRecorder + AudioRecorder，统一 session 级录制入口。
  - **常见方法（从调用点确认）**
    - `start(record_video=True, record_audio=True, auto_capture_audio=False)`
    - `write_video_frame(frame_b64)`
    - `write_audio_chunk(chunk_b64)`
    - `stop()`
    - `cleanup()`

### `app/recorder/__init__.py`

- 导出 `MediaRecorder` 等类，供 `services/media_service.py` 使用。

---

## 4. Socket 层（sockets）

### `app/sockets/__init__.py`

- 导出 `register_socket_events` 与 handlers（供 `app.py` 调用）。

### `app/sockets/events.py`

- **register_socket_events(socketio)**
  - **用途**：注册所有核心 Socket.IO 事件；并调用 `register_robot_events` 追加机械臂事件。
  - **事件处理器（内部 def）**
    - `connect/disconnect`: 连接管理；回 `connected`
    - `join_session/leave_session`: 加入/离开房间（sessionId 通用房间 + 角色房间）
    - `teacher_enter_control/teacher_leave_control`: 广播通知儿童端隐藏/显示待机图
    - `play_resource`: 交由 `PlayResourceHandler.handle` 处理，补充 `sessionId/resolvedFile/behaviorAnimation` 后再定向转发
    - `video_frame/audio_chunk/stop_recording`: 交由对应 handler 处理，并转发给 Child
    - 互动课事件：`matching_*`、`sequencing_*`、`behavior_animation_ended`（多为 room 转发）
  - **备注**：分析反馈事件（`match_result`、`attention_update`、`session_summary`、`analysis_result`、`trigger_action`）由服务端服务直接 emit，不在此注册处理器。

### `app/sockets/handlers.py`

- **PlayResourceHandler**
  - `_resolve_course_type(course_id, fallback='default')`: 从 DB 推导课程 type（与 `/courses` 输出一致）
  - `handle(data)`: 处理 `play_resource` 请求，包含：
    - 识别 aux 操作并复用会话
    - 创建 session、启动录制、（可能）随机选文件、启动分析会话、触发语音服务等
- **VideoFrameHandler.handle(data)**
  - **用途**：处理儿童端上行视频帧（通常是：入队 + 触发分析）（具体看实现）。
- **AudioChunkHandler.handle(data)**
  - **用途**：处理儿童端上行音频 chunk（通常是：入队 + 触发分析）。
- **StopRecordingHandler.handle(data)**
  - **用途**：停止录制（停止 MediaService 录制器、更新会话状态等）。

### `app/sockets/audio_events.py`

- **register_audio_events(socketio)**
  - `play_audio`: （测试通道）转发 `play_audio` 到 room 或广播
  - `audio_status`: Child → Server 的播放状态回传；更新 controller，并 emit `audio_status_update` 给 teacher_room
  - `stop_audio`: Teacher → Server 停止请求；调用 `AudioController.stop_audio`

### `app/sockets/robot_events.py`

- **register_robot_events(socketio)**
  - 注册机械臂姿态数据、录制、播放、表情事件（详见 `docs/CONTRACT.md` robot 部分）。

---

## 5. 服务编排（services）

### `app/services/__init__.py`

- 暴露 `get_media_service/get_analysis_service/get_feedback_service` 等单例工厂。

### `app/services/media_service.py`

- **MediaService**
  - **用途**：录制“中枢服务”，管理 `MediaRecorder` 生命周期，并消费 video/audio 队列写盘。
  - **方法（部分已在代码头部确认）**
    - `start_recording(session_id, student_id=None, course_id=None, course_item_id=None) -> bool`
    - `stop_recording(session_id) -> bool`
    - `process_video_frame(session_id, frame, timestamp=None) -> bool`
    - `process_audio_chunk(session_id, chunk, timestamp=None) -> bool`
    - `_ensure_consumers_running()` / `_video_consumer_loop()` / `_audio_consumer_loop()`（从文件头部推断存在）

### `app/services/analysis_service.py`

- **WindowAnalysisScheduler**
  - `start(session_id) / stop(session_id) / cleanup()`：管理窗口分析的定时调度线程
- **SessionAnalysisState**
  - **用途**：维护某 session 的分析状态（累计帧/音频计数、统计、是否已设置 target 等）（从类名推断）。
- **AnalysisService**
  - **用途**：分析总入口：解码媒体、喂给 pipelines、检查 triggers、发出分析/匹配结果回调。
  - **主要方法（由签名确认）**
    - `_init_pipelines()`
    - `set_callbacks(on_analysis, on_match, on_trigger)`
    - `start_session(session_id, ...)`
    - `set_pose_target* / set_speech_target(...)`
    - `process_video_frame(session_id, frame_data, ...)`
    - `process_audio_chunk(session_id, chunk_data, ...)`
    - `_run_realtime_video_analysis/_run_realtime_audio_analysis/_run_window_analysis(...)`
    - `end_session(session_id)`
    - `get_session_state(session_id) / get_statistics() / cleanup()`
- **get_analysis_service()**
  - 单例入口。

### `app/services/feedback_service.py`

- **FeedbackConfig（dataclass）**
  - enable_realtime/enable_storage/batch_interval/attention_throttle
- **FeedbackService**
  - **用途**：把分析/匹配/触发/总结结果入队 + 落盘 + 通过 socket 推送到 Teacher/Child。
  - **主要方法（从代码确认）**
    - `set_socketio(socketio)`
    - `send_match_result(session_id, match_result)`
    - `send_attention_score(session_id, score, state='unknown', trend='stable', details=None)`（含节流）
    - `send_analysis_result(session_id, analysis_result)`（注意力结果会走 send_attention_score）
    - `send_session_summary(session_id, summary)`（含 export_path）
    - `send_trigger_action(...) / send_match_success(...)` 等（未在本次片段完全展开，见文件后半部分）
- **get_feedback_service()**
  - 单例入口。

---

## 6. 存储（storage）

### `app/storage/result_storage.py`

- **StoredResult（dataclass）**
  - **用途**：存储层内部记录结构（从命名推断）。
- **ResultStorage**
  - **用途**：会话级结果落盘与导出（analysis/match/summary 等）。
  - **常用方法（从调用点推断）**
    - `store_match_result(session_id, match_result)`
    - `store_analysis_result(session_id, analysis_result)`
    - `export_session(session_id) -> Optional[path]`
- **get_result_storage()**
  - 单例入口。

### `app/storage/__init__.py`

- 导出 `get_result_storage` 等。

---

## 7. 分析框架（core）

> 核心思想：registry 注册 analyzer/matcher → pipelines 消费数据 → analysis_service 调度 → trigger/actions 触发副作用 → feedback_service 推送。

### `app/core/auto_register.py`

- `register_all_analyzers() / register_all_matchers()`: 注册 mock/real analyzer 与 matcher
- `auto_register()`: 统一入口，在 `app.py` 启动时调用

### `app/core/registry.py`

- **AnalyzerMode（Enum）**：mock/real
- **AnalyzerRegistry（类）**
  - `register_analyzer/register_matcher`: 注册（name → mock_cls/real_cls）
  - `get_analyzer_class/get_matcher_class/create_analyzer/create_matcher`
  - `list_analyzers/list_matchers/has_real_implementation/clear`
- `register_analyzer()/register_matcher()`：装饰器版本
- `get_registry()`：获取 registry 单例

### `app/core/config_manager.py`

- **AnalyzerConfigManager**
  - **用途**：加载 `config/analyzers.yaml` 并解析全局模式/每个 analyzer/matcher 的 enabled/sample_rate/threshold 等。
  - 关键方法：`load()`、`get_global_mode()`、`get_analyzer_config(name)`、`get_matcher_config(name)`、`is_sampling_enabled()` 等（以实际文件为准）
- `get_config_manager(config_path=None)`：单例入口
- `reset_config_manager()`：重置单例（用于测试/重载）

### `app/core/models.py`

承载分析系统的数据结构：
- **AnalysisMode / AnalyzerStatus / AnalyzerType（Enum）**
- **AnalysisContext**
  - `update_frame_index/update_audio_chunk_index/get_elapsed_time`
- **AnalysisResult**
  - `to_dict/from_dict`
- **MatchResult**
  - `to_dict`
- **WindowData**
  - `frame_count/audio_chunk_count/duration`
- **SessionSummary**
  - `to_dict`
- **AnalyzerConfig / Action / Trigger** 等结构体

### `app/core/base_analyzer.py`

- **BaseAnalyzer（ABC）**：通用 analyzer 抽象（initialize/analyze/cleanup 等）
- **BaseVisionAnalyzer / BaseAudioAnalyzer / BaseWindowAnalyzer**
  - **用途**：按数据类型细分 analyzer 基类，约束输入输出与初始化流程。

### `app/core/base_matcher.py`

- **BaseMatcher（ABC）**
- **BasePoseMatcher / BaseSpeechMatcher**
  - **用途**：匹配器基类，提供 set_target/compute_similarity 等抽象。

### `app/core/pipelines/base_pipeline.py`

- **BasePipeline（ABC）**：实时/窗口/会话级处理接口
- **PipelineManager**：管理 pipelines 实例与生命周期
- `get_pipeline_manager()`：单例入口

### `app/core/pipelines/vision_pipeline.py`

- **VisionPipeline(BasePipeline)**
  - `use_real_pose()`: 是否使用 real 姿态分析器
  - `pose_analyzer/face_analyzer/attention_analyzer/pose_matcher`: 组件访问器
  - `set_pose_target* / reset_pose_target`: 设置姿态目标（用于模仿/比对）
  - `process_realtime/process_window/process_session`: 三种粒度处理入口
  - `reset_session/get_analysis_results`: 会话重置与结果读取

### `app/core/pipelines/audio_pipeline.py`

- **AudioPipeline(BasePipeline)**：音频实时/窗口/会话处理入口
  - `speech_analyzer/session_speech_analyzer/speech_matcher`
  - `set_speech_target(...)`
  - `process_realtime/process_window/process_session`
  - `reset_session/get_analysis_results`
- **ImitationAudioPipeline(AudioPipeline)**：模仿类音频管线的特化实现（从命名推断）

### `app/core/vision/*`

- `pose_analyzer.py`
  - **MockPoseAnalyzer**：Mock 姿态分析器
  - **MockPoseNormalizer**：姿态归一化工具
- `real_pose_analyzer.py`
  - **RealPoseAnalyzer**：基于 MediaPipe 的真实姿态分析
  - **RealPoseNormalizer**：真实关键点归一化
- `face_analyzer.py`
  - **MockFaceAnalyzer**：Mock 表情/头部分析
- `attention_analyzer.py`
  - **MockAttentionAnalyzer**：Mock 注意力（窗口）分析
- `real_attention_analyzer.py`
  - **RealAttentionAnalyzer**：基于 MediaPipe Face Mesh 的真实注意力分析
- `__init__.py`
  - 汇总导出 vision analyzers

### `app/core/audio/*`

- `speech_analyzer.py`
  - **MockSpeechAnalyzer**：Mock 语音分析器
  - **MockSessionSpeechAnalyzer**：会话级 mock 语音分析器（汇总/窗口）
- `real_speech_analyzer.py`
  - **RealSpeechAnalyzer**：旧版可选本地 ASR 分析器；生产配置默认关闭，儿童端以浏览器识别文本为准
  - `_preprocess_audio/analyze_audio/analyze_chunk`：预处理、全量分析、chunk 分析
- `__init__.py`
  - 汇总导出 audio analyzers

### `app/core/matchers/*`

- `pose_matcher.py`
  - **MockPoseMatcher**：Mock 姿态比对器
- `real_pose_matcher.py`
  - **RealPoseMatcher**：真实姿态比对器（阈值、统计等）
- `speech_matcher.py`
  - **MockSpeechMatcher**：Mock 语音比对器
- `real_speech_matcher.py`
  - **RealSpeechMatcher**：真实语音文本比对器（features/similarity/target/statistics）
- `__init__.py`
  - 汇总导出 matchers

### `app/core/actions.py`

- **ActionType / ActionTarget（Enum）**：动作类型与投递目标
- **ActionDefinition / ActionResult**：动作定义与执行结果
- **ActionFactory**：构造动作（播放音频/视频、emit 事件、log、notify 等）
- **ActionExecutor**
  - `set_socketio(socketio)`
  - `execute(action, session_id)`
  - `_emit_to_target/_execute_play_audio/_execute_emit_event/...`：动作执行实现

### `app/core/trigger.py`

- **TriggerType / TriggerCondition / TriggerDefinition**
- **TriggerEvaluator**：判定触发条件
- **TriggerSystem**：统一触发系统（维护 triggers、触发动作）
- **TriggerFactory**：内置触发器生成（如 match success → praise）
- `get_trigger_system()`：单例入口

### `app/core/buffer.py`、`app/core/accumulator.py`

- **MultiSessionBuffer / MultiSessionAccumulator**
  - **用途**：多会话窗口缓冲与累积统计（供窗口分析与总结使用）
- `get_buffer_manager()` / `get_accumulator_manager()`：单例入口

### `app/core/__init__.py`

- 汇总导出 core 侧的常用类/函数，方便外部导入。

---

## 8. 语音子系统（audio）

> 语音播放的“服务端控制 + 儿童端播放 + 状态回传”链路详见 `docs/CONTRACT.md` 与 `static/js/audio_player.js`。

### `app/audio/models.py`

- 定义 SelectionStrategy、AudioStatus、AudioFile、AudioEntry、AudioContext、PlaybackStatus、AudioManifest 等数据结构与 `to_dict`/查询方法。

### `app/audio/registry.py`

- **AudioRegistry**
  - `get_instance()`: 单例 + 加载清单
  - `load_manifest(config_path='config/audio_manifest.yaml')`
  - `_parse_manifest/_parse_files/_create_default_manifest`
  - 查询接口：`get_entry/get_by_category/get_by_intent/get_by_tags/...`
- `get_audio_registry()`: 获取单例

### `app/audio/selector.py`

- **AudioSelector**
  - `select(entry_id, context=None, file_type='files') -> Optional[str]`
  - `_apply_strategy/_select_random/_select_sequential/_select_weighted/_select_context_aware`
  - `select_for_course/select_vocalization/get_play_history/reset_history`（见文件后半部分）
- `get_audio_selector()`: 单例入口

### `app/audio/events.py`

- **AudioEventEmitter**
  - **用途**：服务端向 Child room emit `play_audio`（并携带 entry_id/file_path/priority/interrupt）
- `init_audio_emitter/get_audio_emitter`: emitter 的初始化与单例获取

### `app/audio/controller.py`

- **AudioController**
  - `stop_audio(session_id, immediate=True)`：向 child_room emit `stop_audio`
  - `on_audio_status(session_id, data)`：处理 Child 回传的 `audio_status` 并转发给 Teacher
  - `get_status/get_all_status/clear_status/clear_all_status/get_stats`
- `init_audio_controller/get_audio_controller`

### `app/audio/service.py`

- **AudioService**
  - `process_play_resource(session_id, data)`：把 `play_resource` 的 aux(question/praise/hint) 映射为实际语音播放（调用 emitter.emit_for_course）
- `get_audio_service/init_audio_service`

### `app/audio/__init__.py`

- 汇总导出 registry/selector/emitter/controller/service 等入口函数。

---

## 9. 机械臂子系统（robot，可选）

### `app/robot/config.py`

- `ensure_data_files()`: 确保 motions/mapping 等数据文件存在（从命名推断）。

### `app/robot/motion_recorder.py`

- **MotionRecorder**：录制机械臂动作帧序列并落盘（从命名推断）。

### `app/robot/motion_player.py`

- **MotionPlayer**：通过 OSC 等协议播放动作（依赖 `python-osc`）（从命名与依赖推断）。

### `app/robot/mapping_resolver.py`

- **MappingResolver**：根据学生/课程/项目等四级映射解析应该播放的 motion（从文件名与项目文档推断）。

### `app/robot/robot_service.py`

- `set_socketio(socketio)`: 设置 socketio（用于表情等事件）
- **RobotService**：机械臂服务总入口（录制/播放/映射/触发课程事件）
- `get_robot_service()`: 单例入口

### `app/robot/routes.py`

- 一组 HTTP API（Blueprint）：
  - `get_motions/get_motion/save_motion/delete_motion`
  - `play_motion/stop_playback`
  - mapping CRUD：`get_full_mapping/set_idle_pose/update_default_motions/...`
  - `trigger_course_event`：外部触发课程事件
  - `get_students/get_courses`：（供面板使用）
  - emotion：`get_emotions/get_default_emotion/trigger_emotion`

### `app/robot/__init__.py`

- 汇总导出 robot_service、motion_player/recorder、mapping_resolver、routes 等。

---

## 10. 工具（utils）

### `app/utils/logger.py`

- `setup_logger(name='app', log_file=None, level=None) -> logging.Logger`
  - **用途**：统一日志配置（控制台 + 文件），供各模块按 name 获取 logger。

### `app/utils/exceptions.py`

- 定义项目异常层级：
  - `AppException → SessionException/RecordingException/AnalysisException/StorageException` 及其子类

### `app/utils/resource_utils.py`

- `get_random_file_from_folder/get_first_file_from_folder`
- `is_folder_path/folder_exists/count_files_in_folder`

### `app/utils/__init__.py`

- 聚合导出 utils 子模块（如有）。

