# 第一阶段：对外契约清单

## 1. 生成口径

本清单依据当前 Python AST 装饰器、实际蓝图前缀、前端调用和 `docs/CONTRACT.md` 交叉核对。机器快照见 [`contracts.snapshot.json`](contracts.snapshot.json)。当前快照记录 152 个源码 route 和 58 个装饰器注册的 Socket 事件；根 Flask 实例另外自动提供 1 个框架默认 `/static/<path:filename>` 规则，因此启动导入检查观察到 153 条 URL。服务端动态 emit 另单列，不把“装饰器注册”和“服务端输出”混为一类。

契约冻结内容包括：路径、方法、参数命名、响应 envelope、状态码、错误字符串、Socket 事件名、方向、room、ack、关联 ID、重试/幂等、页面 URL、静态 URL、端口、环境变量、启动方式和文件名。任何迁移必须先更新 fixture/快照，再证明旧客户端仍能工作。

## 2. 页面与静态入口

| URL | 当前行为 |
|---|---|
| `/` | `templates/index.html` |
| `/therapist` | 重定向到 `TEACHER_FRONTEND_URL`，默认同源 `/teacher/` |
| `/child` | `templates/child.html` |
| `/server` | 监控页；`?view=config` 重定向 `/server/config/overview` |
| `/server/report-review/<training_session_id>` | 报告审核页 |
| `/server/config`、`/server/config/{overview,camera,speech,report,content}` | 配置中心入口/模块页 |
| `/courses` | 课程列表旧入口 |
| `/sequencing`、`/matching` | 互动课程静态页入口，保留 query |
| `/robot`、`/robot/emotion`、`/robot/download` | 机器人控制、表情和 Runtime 下载页 |
| `/static/css/<path:filename>`、`/static/js/<path:filename>`、`/static/resources/<path:filename>` | 旧静态资源 URL，不能改名 |

## 3. HTTP 契约分组

完整方法+路径+实现函数由快照逐条记录；以下是稳定的功能族和当前响应约定。

| 功能族 | 路径范围 | 当前实现/响应约定 |
|---|---|---|
| 服务配置与状态 | `/api/server/config*`、`/api/server/status`、`/api/server/diagnostics`、`/api/server/presets*`、`/api/server/runtime-modes`、`/api/server/child-media-mode`、`/api/child/runtime-config` | 成功通常为 JSON `success`/`ok` 加 config/status/data；校验错误 400；配置读写失败 4xx/500；保留环境变量和 YAML 优先级 |
| 配置文件 | `/api/server/config/camera-analysis`、`/report-scoring` | GET 返回 `success + config`；PUT 校验后写 YAML 并保留备份；错误 400/500 |
| 教师/学生 | `/api/teacher/*`、`/api/students*`、`/api/course-types`、`/api/ability-types` | 登录/注册/创建为 JSON；缺字段 400；查无资源 404；数据库异常 500；字段名以当前代码和前端类型为准 |
| 课程内容 | `/api/config/course-types`、`/courses*`、`/items*`、`/media*`、`/audio/*`、`/content/summary` | 课程/课点/媒体/音频配置直接服务控制端；PATCH/PUT 保留部分更新语义；上传错误 400，冲突/引用保护按实现返回 409/4xx |
| 媒体上行 | `/api/media/<session_id>/frames`、`audio-chunks`、`upload`、`status` | 接受实时帧/音频块、补传 multipart、查询状态；通常返回 `ok/success/accepted/lastSeq` 或错误；认证头 `X-Child-Media-Agent-Key` 继续兼容 |
| 监控与环境摄像头 | `/api/monitor/snapshot`、`remote-preview.jpg`、`ambient/*` | snapshot JSON；图片接口返回 JPEG 或错误；当前 ambient 是单服务/单控制模型，不能把现状误写成 0..N 已实现 |
| 报告 | `/api/report/<training_session_id>*`、`pending-reviews` | 报告生成、刷新、查看、审核、发布、手工修改和回退；失败必须保留旧结果和明确错误 |
| 机器人动作 | `/api/robot/motions*`、`play/*`、`stop`、`sequence/preview` | 动作列表/详情/保存/导入/删除/试播；导入当前只接受单文件；坏 JSON 400，找不到 404，服务异常 500 |
| 机器人映射 | `/api/robot/mapping/*`、`course-event` | 旧 aux 槽和四层优先级必须保留；`aux_type` 当前白名单为 `praise`、`hint`、`question`、`silent`、四个 social 槽；无效类型 400 |
| 表情与鼓励动画 | `/api/robot/emotions*`、`/api/robot/animations*` | 表情与 MP4 动画列表/上传/删除；引用删除 409，文件不存在 404，上传成功为 201；鼓励绑定未指定动画时从默认动画库随机选择 |
| Runtime | `/api/robot/runtime/register`、`heartbeat`、`status`、`version`、`download` | 注册/心跳可带 Runtime key；未授权 401；状态/版本/下载保持当前字段和安装包行为 |
| 旧互动接口 | `/api/getSequencingImages`、`/api/getMatchingImages`、`/api/saveResult` | 旧 camelCase 路径与 payload 必须保留，不因新课程模型改名 |

HTTP 当前没有统一的认证中间件或统一错误 DTO；各 handler 的 `success/error`、状态码和字符串属于兼容内容。第一阶段不统一它们，只把差异记录为后续 contracts adapter 的边界。

## 4. Socket 请求事件（装饰器注册）

### 连接、房间与在线

`connect`、`disconnect`、`client_presence`、`join_session`、`leave_session`、`child_sync_request`、`teacher_enter_control`、`teacher_leave_control`、`child_agent_heartbeat`、`child_media_agent_heartbeat`。

### 训练、资源与录制

`prepare_training`、`cancel_prepare_training`、`readiness_start`、`readiness_cancel`、`readiness_child_report`、`play_resource`、`resource_ready`、`resource_transition_failed`、`video_frame`、`audio_chunk`、`camera_analysis`、`stop_recording`、`finalize_training`、`teacher_rating_submit`、`freeze_course_frame`。

### 互动课程

`matching_set_difficulty`、`matching_start`、`matching_next`、`matching_hint`、`matching_status_update`、`matching_game_end`、`matching_question_ready`、`sequencing_set_config`、`sequencing_start`、`sequencing_next`、`sequencing_hint`、`sequencing_status_update`、`sequencing_game_end`、`sequencing_question_ready`、`interactive_page_context`、`behavior_animation_ended`。

### 语音与对话

`play_audio`、`stop_audio`、`audio_status`、`child_dialogue_text`、`child_dialogue_audio`、`child_dialogue_sleep`、`request_question_speak`、`robot_speak_ended`。

### 机器人

`robot_pose_data`、`robot_start_recording`、`robot_stop_recording`、`robot_play_motion`、`robot_stop_playback`、`robot_emotion_auto_random`、`robot_motion_ack`。

## 5. 服务端输出事件

当前静态代码观察到的输出包括：`connected`、`joined_session`、`play_resource_ack`、`prepare_training_ack`、`cancel_prepare_training_ack`、`readiness_start_ack`、`readiness_cancel_ack`、`readiness_child_report_ack`、`finalize_training_ack`、`teacher_rating_ack`、`child_session_sync`、`play_resource`、`stop_recording`、`training_prepare`、`training_prepare_cancel`、`resource_ready`、`freeze_course_frame`、`interactive_page_context`、`robot_speak_text`、`robot_speak_ended`、`play_audio`、`stop_audio`、`audio_status_update`、`match_result`、`attention_update`、`analysis_result`、`session_summary`、`trigger_action`、`behavior_completed`、`behavior_trigger_rejected`、`robot_motion_command`、`robot_playback_status`、`robot_recording_status`、`robot_emotion_change`、各 matching/sequencing 状态事件和 `child_dialogue_result`/`child_dialogue_wake_state`。

输出必须保持各事件当前实际的 room 规则：儿童资源按精确 child owner SID 或 `session_<id>_child` 投递；无法解析目标儿童时不得广播到全局；`teacher_rating_ack` 当前只回给提交者 `request.sid`，并不广播到其他教师客户端。其余教师反馈是否进入 session/teacher room 必须按事件 fixture 分别确认，不能概括成统一规则。所有行为播放继续使用 `behaviorId`，请求幂等继续使用 `requestId`，训练/媒体/行为分别保留 `trainingSessionId`、`sessionId/mediaSessionId` 和 `behaviorId` 关联。

## 6. 关键时序与幂等

- `prepare_training` 当前会创建 warmup session、目录和录制；重复准备会收尾旧的 warmup/continuous session。
- `play_resource` 当前要求 `action=play`，解析课程类型和 aux；已有连续 session 时复用它；课点切换调用 timeline，不 stop/start 媒体。
- `play_resource` 使用进程内 request cache，TTL 约 300 秒、容量约 2048；重连可重放已缓存的 child content。
- 课程行为系统使用全局互斥/behavior ID；`play_resource` 在 busy 时会在进入资源 handler 前拒绝，测试已证明动作/表情视觉指令不泄漏且不会释放既有 busy。独立的 `robot_emotion_auto_random` 是另一条旧控制事件，不应据此推断其具备同一原子屏障。
- `resource_ready`、`resource_transition_failed` 通过 request/behavior/session 关联，旧 ACK 和错误形态必须保留。
- `cancel_prepare_training`、`stop_recording`、`finalize_training` 要求重复调用可安全收尾；断线、Runtime 掉线和补传不能删除路径 registry。
- TTS/对话期间保留现有 ASR 暂停、唤醒状态清理和课程/题目页面上下文隔离。

## 7. 端口、模式与环境变量

- 后端默认 `http://127.0.0.1:8080`；教师端生产包默认同源 `/teacher/`；voice-service 默认 `http://127.0.0.1:8765`；child media agent 默认端口 19091。Vite 5173 仅用于显式前端开发。
- `CHILD_MEDIA_MODE` 为 `browser|agent`，默认代码路径为 agent；`ROBOT_CONTROL_MODE` 控制 Runtime/OSC；`DIALOGUE_ENABLED`、`DIALOGUE_TTS_MODE`、`AI_CHAT_PROVIDER` 控制语音分支。
- 关键环境变量完整来源为 `app/config.py`、`.env.example`、`docs/ENVIRONMENT.md` 和 Runtime yaml；第一阶段不重命名或清理变量。

## 8. 契约差异处理

新增字段级 fixture 已用 Flask test client 证明以下当前响应：

| 路由 | 成功字段级证据 | 错误/边界证据 | 证据状态 |
|---|---|---|---|
| `GET /api/server/status` | `success/statistics/sessions/modelStatus/globalMode/snapshotCount/historyCount/onlinePresence/robotControlMode/childMediaMode/mediaSessionMeta/robotRuntime` | 既有异常分支仍为 500 + `success:false,error` | fixture 已证明 |
| `GET /api/monitor/snapshot` | `success/data`，data 内保留 ambient | 异常为 500 + `success:false,error` | fixture 已证明 |
| `GET /api/robot/motions` | `success/motions` | 异常为 500 + `success:false,error` | fixture 已证明 |
| `POST /api/robot/motions/import` | `success/message/motionName` | 缺文件为 400 + `success:false,error:file required` | fixture 已证明 |
| `GET /api/robot/emotions` | `success` 与 service payload 原字段展开 | 异常为 500 + `success:false,error` | fixture 已证明 |
| `GET /api/report/<id>` | `success/data` | 未发布 409、未找到 404，保留既有 error/review/publicationStatus 字段 | fixture 已证明 |
| `POST /api/report/<id>/generate` | `success/data`，保留 `autoFinalize/soft` 语义 | `not_finalized` 为 409；其余 ValueError 为 400（后者仍为源码确认） | 主要分支 fixture 已证明 |
| `GET /api/config/course-types` | `success/types[]`，元素为 `id/name/type` | handler 无本地错误 envelope，未捕获异常由 Flask 返回 HTML 500 | fixture 已证明 |

补传 fixture 还证明：正确 SHA-256 写入 `archive_meta.json`；错误 SHA-256 当前仅日志告警、仍返回 200；`source/sessionId/duration/checksums/saved` 结构和已注册 session 目录关联保持不变；重复上传可重复覆盖并保留第一次实时文件备份；finalize 后晚到补传仍被接受。这些是当前行为，不是第一阶段修复建议。

运行时交叉验证由 `tests/test_phase1_runtime_contracts.py` 完成：URL map 为 152 条源码路由 + 1 条隐式 static；装配后 Socket handler 为 58 条并与装饰器集合一致；源码静态 literal emit 为 54 条并与快照一致。差异来源是 Flask 自动 HEAD/OPTIONS 不计入快照，以及服务端输出事件不等于客户端接收装饰器事件，因此两组集合不能简单要求相等。

本阶段维护 characterization/contract tests 和机器索引。关键 HTTP 路由的成功字段与指定错误形态已有 fixture；这不等于全部 152 条业务 route 均完成字段级冻结。Socket payload 全量 fixture、外部 Runtime 实机 payload、三端截图/抓包仍有不可确认项，已在 `00-current-state.md` 标记。
