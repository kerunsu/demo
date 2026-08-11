# 升级与修复交接（跨对话）

> **新对话请先读 [`README.md`](README.md) 与当前架构/契约；旧规划已移入 `archive/`。**  
> 总规划在计划文件；**本文件记录已落地改动、契约、验收与未做项**。  
> 行为/报告批次对应 commit：`84f45e8c`；Robot Runtime 发布批次对应：`d0f03089`（其后路径配置/热更新/Socket.IO 本地化等多未单独 commit，以工作区 + 本文为准）。  
> 分支：`backup-bad-code`。

---

## 0. 一句话现状

阶段 **A → B → C / C+ / C2** 与 **Runtime-AV（R1–R4）** 已落地。  
另已落地 **机器人端部署链路**：`robot_runtime` 统一进程、exe 发布包、`/robot/download`、`/ui` 改媒体路径与热更新、后端绑 `0.0.0.0`、儿童/表情页 Socket.IO 改为本机静态资源（修局域网 CDN 证书失败）。

下一主线（计划内）：可选环境兼容（NumPy/sklearn）或其它未列项。  
**D/E/F 详细需求**见 [`PHASE_DEF_REQUIREMENTS.md`](PHASE_DEF_REQUIREMENTS.md)。  
**阶段 D / E 已落地**。  
**阶段 F-IC0 → F-IC4 已落地**（[`PHASE_F_INTERACTIVE_CONTENT_CONFIG.md`](PHASE_F_INTERACTIVE_CONTENT_CONFIG.md)）。  
**阶段 F-Algo0 → F-Algo4 已落地**（[`PHASE_F_ALGO_CONFIG.md`](PHASE_F_ALGO_CONFIG.md)）。  
**旧「高级 YAML」页已下线**（Y1–Y5）：运行时模式/预设/回滚/高级字段迁入配置中心；`/server?view=config` → overview。

---

## 1. 已完成工作总览

| 批次 | 内容 | 状态 |
|------|------|------|
| A | `training_session` + 题目窗口 + finalize；课点切换收尾 | 完成 |
| B | 注意力/表达性语言观测入库；AudioPipeline Registry；配对/排序 metrics | 完成 |
| C / C+ | 报告 scoring/API、`ReportPage`、完成弹窗「查看报告」；数据链路与 PARTIAL 轮询 | 完成 |
| C2 | 浏览器 `camera_analysis`（注意力/情绪）；Socket；报告 KPI 三色条 | 完成 |
| Bugfix | 表扬音频循环；注意力双源跳变；播放状态 `finished`→`ended` | 完成 |
| R1–R4 | agent/browser 分流；服务端写 attention/emotion；Mock 降级；文档 QA | 完成 |
| **Robot Runtime 部署** | 统一 Runtime、exe 包、下载页、路径配置、热更新、LAN bind、Socket.IO 本地化 | **完成（见 §9）** |
| **连续录制方案 B** | 整场一份 AVI/WAV + `timeline.csv` + `姓名-年龄-日期-N`；切题不启停 | **完成（见录制时机表）** |
| **阶段 D** | `/server` 配置/监控双 Tab + MonitorSnapshot 1s poll + Socket 触发 | **完成（见 §3.5）** |
| **阶段 E** | 公式文档、监控预览/事件/徽章、降级文案、选源单测 | **完成（见 §3.6）** |
| **阶段 F-IC0→IC4** | 配置中心交互内容：壳、表情、绑定、动作、媒资、课程、speech_target、工作台 | **完成** |
| **阶段 F-Algo0→4** | 配置概览、摄像头双栈、语音、报告权重；camera/report GET/PUT + `.bak` | **完成** |
| **取消高级 YAML** | Y1–Y5：运行时模式/运维动作/高级字段迁入配置中心；`/server` 仅监控；`?view=config` 重定向 | **完成** |

---

## 2. 关键架构约定（勿在新对话里推翻）

### 2.1 部署拓扑（已确认）

| 角色 | 位置 | 职责 |
|------|------|------|
| 后端 | 主机 Flask（须 `host=0.0.0.0`） | 会话、分析、报告、Socket、发布包托管 |
| 机器人 Windows | DollSer + `RobotRuntime.exe` + 浏览器开服务器 `/child`、`/robot/emotion` | 生产 AV 采集 + OSC；**不要**整仓 git |
| 教师 | Android / Vite 同源 | 控课 + 报告 |

### 2.2 媒体与分析路径

| `CHILD_MEDIA_MODE` | 采流 | 注意力/情绪 | 报告 prefer_browser |
|--------------------|------|-------------|---------------------|
| **`agent`（生产）** | `robot_runtime` 上行 | 服务端 Real + `record_* (provider=server)` | **否**（默认） |
| **`browser`（联调）** | `/child` getUserMedia | 可选 C2 JS | 仅当存在有效 browser 样本时优先 |

**重要冲突（已修）：** agent 下 `#childCam` 无 video track → 旧 C2 会刷 `missing_device`，且 `prefer_browser` 会挡住服务端样本。现已：agent 跳过 C2；`prefer_browser` 仅在 browser 模式动态开启。

**本地落盘（agent）：** Runtime 在机器人机写完整 `video.avi` + `audio.wav`（默认 `%LOCALAPPDATA%\EIArt\child_media\sessions\{姓名-年龄-日期-N}\`，与服务端目录名一致；未传 `humanDirName` 时回退 legacy `{sessionId}/`），并实时上行 + 结束后补传后端；补传成功**不删**本地文件。本地另写轻量 `session_meta.json`（含 mediaSessionId）；**不**在机器人端维护 `timeline.csv`（权威在服务端）。路径可在 Runtime `/ui` 修改（`config.json` → `mediaDataDir`）；`CHILD_MEDIA_DATA_DIR` 环境变量优先。

**录制时机（agent，方案 B 连续录制，2026-07-13）：**

| 段 | 起点 | 终点 | 分析 | 媒体 |
|----|------|------|------|------|
| **整场连续** | `prepare_training`（儿童端 `/record/start` 一次） | `finalize_training` / `cancel_prepare_training` | 首个非 aux 课点起 `reconfigure_session`；切题不清 buffer | **一场一份** `video.avi` + `audio.wav` |
| **时间轴标注** | 每次非 aux `play_resource` | 下一课点或 finalize | — | 写 `timeline.csv` 行；**不** stop/start |

- Socket：`prepare_training` / `prepare_training_ack` / 广播 `training_prepare`（含 `recordingMode: continuous`、`humanDirName`）；选课返回 `cancel_prepare_training` → `training_prepare_cancel` + `stop_recording`。
- 落盘目录：`static/recordings/sessions/{姓名-年龄-YYYYMMDD-N}/`（含 `timeline.csv`、`session_meta.json`）；behavior 仍在 `static/recordings/behavior/{training_session_id}/`。
- 对照表：`python -m tools.export_recording_lookups` → `course_type_lookup.csv` / `course_item_lookup.csv`。
- **禁止**切题时 agent `/record/stop`→`/record/start`；儿童端同 `mediaSessionId` 或 `recordingMode=continuous` 时保持录制句柄。
- 详设见 [`CONTINUOUS_RECORDING_TIMELINE_PLAN.md`](CONTINUOUS_RECORDING_TIMELINE_PLAN.md)。

**页面在线 presence（修复）：**

- 旧逻辑：`teacherOnline` / `childOnline` 仅在 `join_session` 或 `teacher_enter_control` 时写入，选课/就绪门阶段与仅打开 `/child` 时 `/server` 会显示离线；且 30s 无刷新即过期。
- 新逻辑：Socket 事件 `client_presence`（`role: teacher|child`）；儿童端 `common.js`/`child.js` 连接后每 10s 心跳；教师端 `App`/`ControlPage` 同理。Agent heartbeat 同时刷新 `child` 页面 presence。

**开课就绪门（P0，选课→控制页）：**

| 事件 | 方向 | 说明 |
|------|------|------|
| `readiness_start` | 教师→服务器 | `studentId`, `trainingSessionId`, `items[{courseId,itemId,courseType,file?}]`；可选 `moduleId` 单模块重试 |
| `readiness_start_ack` / `readiness_update` / `readiness_complete` | 服务器→教师 | 模块状态 `M1/M2/M5/M6/M7` + 进度 |
| `readiness_prepare` | 服务器→儿童 | `assetUrls` / `audioUrls` / `requireRecording` |
| `readiness_child_report` | 儿童→服务器 | 录制中、coursesReady、preload 计数/失败路径 |
| `readiness_cancel` | 教师→服务器 | 仅取消本轮 Gate，**不**停 warmup |

- 实现：`app/services/readiness_service.py`；音频路径与正式播放同源（`AudioSelector.select_for_course`）；儿童端 `AudioPlayer.preloadAudio` 静默 Promise 预热。
- 教师端：`TrainingReadinessDialog`；`App.handleStartCourse` 先开 Gate，全绿后再 `setPage(control)`。
- 详设见 `docs/TRAINING_READINESS_GATE_PLAN.md`。

### 2.3 配置入口

- `config/analyzers.yaml`：默认 **real**；Mock 保留作回退
- `config/camera_analysis.yaml`：`prefer_browser_for_report: false`；`prefer_browser_when_media_mode_browser: true`
- `.env` / `.env.example`：`CHILD_MEDIA_MODE`、`USE_REAL_ANALYZERS`、`ROBOT_CONTROL_MODE=robot_runtime`
- `config/report_scoring.yaml`：报告权重/公式
- 机器人端：`%LOCALAPPDATA%\EIArt\robot_runtime\config.json`（backendUrl / mediaDataDir 等）

---

## 3. 主要新增/改动模块

### 3.1 行为与报告

| 路径 | 作用 |
|------|------|
| `app/behavior/` | 模型、store、timeline、camera_config、emotion_scoring、service |
| `app/report/` | scoring、narrative、service |
| `app/routes/report.py` | 报告 HTTP API |
| `static/recordings/behavior/{training_session_id}/` | JSON 持久化（按设计） |
| `teacher_frontend/components/ReportPage.tsx` | 报告页；默认横屏 + 横竖切换 + print `@page` |
| `teacher_frontend/components/ControlPage.tsx` | 「查看报告」；注意力显示单源/保底 |

### 3.2 相机分析（C2，联调）

| 路径 | 作用 |
|------|------|
| `static/js/camera_analysis/*` | browser-attention-v2 / browser-emotion-v1 |
| `static/js/child.js` | agent 跳过 C2；browser 才启动 |
| Socket `camera_analysis` 等 | 浏览器描述符上行（见 handlers/events） |

### 3.3 分析管线与触发（Bugfix / Real）

| 路径 | 改动要点 |
|------|----------|
| `app.py` `on_trigger_action` | **跳过**与 ActionExecutor 重复的 praise 播放 |
| `app/core/pipelines/audio_pipeline.py` | reset 时清 speech target；Registry 对齐 |
| `app/audio/controller.py` | `finished` 映射为 `ended` |
| `app/core/matchers/speech_matcher.py` | 匹配冷却加长 |
| `app/core/trigger.py` | 交互课关闭自动 praise 触发（相关） |
| `static/js/audio_player.js` / `child.js` | 避免 legacy 辅音频与 AudioPlayer 双播 |
| `app/core/registry.py` | Real 创建失败 → 回退 Mock + 日志 |
| `app/services/analysis_service.py` | `record_attention` / `record_emotion`（server） |
| `app/core/vision/real_attention_analyzer.py` | Real 窗口分析增强 |

### 3.4 文档与参考

| 路径 | 用途 |
|------|------|
| `archive/planning/PROJECT_UPGRADE_PLAN.md` | 历史总规划 + 进度日志 |
| `archive/planning/FEATURE_TRANSFER.md` | 历史源项目迁移边界 |
| `archive/legacy-guides/EMOTION_ATTENTION_REIMPLEMENTATION_GUIDE.md` | 历史情绪/注意力重实现说明 |
| `docs/CAMERA_ANALYSIS_QA.md` | **生产 agent / 联调 browser 验收清单** |
| `docs/ROBOT_DEPLOY.md` / `ENVIRONMENT.md` / `ROBOT_RUNTIME.md` | **部署、打包、热更新、路径配置**（细节以这三份为准） |
| `archive/prototypes/professional_report_ver2.html` | 历史报告 UI 参考 |
| `archive/prototypes/realtime_monitor_dashboard_prototype_light.html` | 历史监控台参考（阶段 D） |
| `temp_robot-config-prototype/` | 配置中心远期参考（未入库，本地仍有） |

### 3.5 阶段 D — Server 监控台（2026-07-13）

| 路径 | 作用 |
|------|------|
| `app/monitor/snapshot.py` | `get_monitor_snapshot`：聚合 session/course/attention/emotion/voice/robot/health |
| `app/routes/monitor.py` | `GET /api/monitor/snapshot`（可选 `?trainingSessionId=`） |
| `templates/server.html` | 顶栏「配置控制 / 数据可视化」双 Tab |
| `static/js/server_monitor.js` | 1s poll + 相关 Socket 事件立即再拉；断线仍靠轮询 |
| `static/css/server.css` | 监控台浅色运营布局 |
| `tests/test_monitor_snapshot.py` | 无会话空态 + 有会话字段 / 切题同 `mediaSessionId` |

**契约要点（方案 B）：** Snapshot 含 `humanDirName`、`recordingMode: continuous`；整场一个 `mediaSessionId`（通常 = `runtimeSessionId`）；切题只改 `course`/`questionId`。  
**预览：** E2 已接通（见 §3.6）。  
**手工验收：** 上课中打开 `/server` → 数据可视化；注意力约 1s 更新；断 Socket 后轮询仍变；无训练时空态不 500。

### 3.6 阶段 E — 打磨 / 公式 / 降级 / 测试（2026-07-16）

| 路径 | 作用 |
|------|------|
| `docs/REPORT_SCORING.md` | 权重含义、formulaVersion、中途改权重约定、打印抽检清单 |
| `config/report_scoring.yaml` | 分段注释；`narrative_provider` |
| `app/report/narrative.py` | 真正读取 `rule`/`mock`（非法回落 rule） |
| `app/report/limitations_copy.py` | limitations 码→中文 |
| `app/monitor/events.py` | 监控事件环形缓冲 |
| `app/monitor/snapshot.py` | preview / events / MISSING score=null / Mock limitations / agent 徽章 |
| `app/config.py` | `MONITOR_PREVIEW_*` |
| `static/js/server_monitor.js` + `templates/server.html` | 预览帧、事件列表、健康徽章、暂停/静音占位 |
| `tests/test_attention_source_selection.py` | prefer_browser 选源 |
| `tests/test_monitor_snapshot.py` | 扩展 MISSING / 预览关闭 |

**环境变量：** `MONITOR_PREVIEW_ENABLED`（默认开）、`MONITOR_PREVIEW_TTL_MS`、`MONITOR_PREVIEW_MAX_BYTES`。  
**验收：** 关摄像头 → 监控/控课不显示「分散」；预览 stale 有标识；`pytest tests/test_attention_source_selection.py tests/test_monitor_snapshot.py`。

---

## 4. Bugfix 根因速查（避免回退）

### 4.1 表扬音频中途循环

- **双 emit**：Trigger ActionExecutor 已播 praise，`on_trigger_action` 又播一次 → 队列叠两条。
- **speech target 未清**：session reset 后跨课点残留匹配。
- **状态字**：客户端 `finished` vs 服务端枚举 `ended` → 日志「未知的播放状态」。
- **child 双通道**：legacy 辅音频 + AudioPlayer 同播。

### 4.2 教师端注意力 80–90 ↔ 几分跳变

- **双源**：浏览器 C2 高分 + 服务端无脸/0 分都推 `attention_update`。
- **修复方向**：按 mediaMode 单源；服务端推无脸 0 分；教师端实时约 1.2s 近窗；**归一化 agent 毫秒时间戳**（否则 10s/300 帧旧缓冲永不清理，分数拖尾且回升被锁死）。

### 4.3 C2 与 agent 冲突

- agent 下无本地 video → `missing_device`；`prefer_browser` 挡服务端写入。
- **修复**：agent 不启 C2；timeline 按 mediaMode 选择样本源。

### 4.4 局域网打不开后端 / 教师控课儿童端不更新

- **只绑 `127.0.0.1`**：别的设备访问 `http://<局域网IP>:8080` 必失败；`app.py` 已改为 `host="0.0.0.0"`。注释曾写 0.0.0.0 但代码曾是 127.0.0.1——勿再改回。
- **校园网 AP 隔离**：改绑后仍不通时，可能是网络禁止终端互访（与 Flask 无关）。
- **`io is not defined` + `ERR_CERT_AUTHORITY_INVALID`**：儿童/表情页曾从 `https://cdn.socket.io` 拉库，测试机证书/外网失败 → Socket 起不来、教师端操作无响应。已改为 `/static/js/vendor/socket.io.min.js`（**后端静态资源，不需重打 Runtime exe**）。

### 4.5 Runtime 热更新（exe 换不上 / WinError 87）

- **WinError 87**：`subprocess` 不能同时 `CREATE_NEW_CONSOLE | DETACHED_PROCESS`；已改为仅 `CREATE_NEW_CONSOLE`。
- **exe 换不上、README/start.bat/VERSION 能换上（2026-07-13）**：Windows 对刚退出的 `RobotRuntime.exe` 仍短暂加锁；旧 bat 用单次 `copy /Y ... >NUL`，失败被静默吞掉，随后又启动了**旧 exe**。旁路文件未被锁定故“看起来更新成功”。
- **修复**：`updater.py` 改为「先 `move` 旧 exe → `.old`，再 `copy` 新 exe」，最多重试 40 次并写 `%LOCALAPPDATA%\EIArt\robot_runtime\update_restart.log`；失败回滚。
- **注意**：含本修复的包需至少成功装上一次（手动 `/robot/download` 或本修复已进当前 exe）后，后续热更新才稳定。

---

## 5. 手动验收（最短路径）

生产（推荐）：按 [`docs/CAMERA_ANALYSIS_QA.md`](CAMERA_ANALYSIS_QA.md) **agent** 清单。

本地捷径：`CHILD_MEDIA_MODE=browser`，确认 C2 启动且报告可出曲线。

额外：

- 模仿/语音课：praise 只播一次，播完不立刻再播。
- 配对/排序：点对不因旧 trigger 叠表扬循环。
- 报告页：横竖切换与打印方向一致。
- 教师实时注意力：不在高分与 0 之间狂跳。
- **跨机**：测试机打开 `http://<服务器IP>:8080/child` 与 `/robot/emotion`，控制台无 `io is not defined`；教师端操作能驱动儿童端。
- **发布**：`.\scripts\pack_robot_release.ps1` → `/robot/download` 可下；Runtime `/ui` 可改媒体路径、可检查/应用热更新。

---

## 6. 已知问题 / 未做项

| 项 | 说明 |
|----|------|
| **阶段 D** | **已完成** → 见 §3.5 |
| **阶段 E** | **已完成** → 见 §3.6；详情 [`PHASE_DEF_REQUIREMENTS.md`](PHASE_DEF_REQUIREMENTS.md) §2 |
| **阶段 F** | **F-IC + F-Algo 已完成**；旧高级 YAML 页已下线 → 配置中心 + 监控 |
| **NumPy 环境** | 启动日志常见 NumPy 2.x 与 pandas/pyarrow/sklearn（FunASR）告警；现多能跑通，但有真实风险；可 pin `numpy<2` 或升级栈 |
| **说话人分割** | 明确不做；默认人声=儿童 |
| **temp_robot-config-prototype/** | 本地未 commit；需要时可再入库 |
| **计划 plan 文件** | Cursor plan（含 runtime_av / robot_exe / path+update）勿当源码真相；以仓库 md + 代码为准 |
| **热更新验收标记** | `/ui` 上曾留「hotupdate-test-*」文案便于联调；正式交付前可删掉绿字标记 |
| **本对话后续改动未全部 commit** | Runtime 路径/热更新/WinError87/Socket.IO 本地化等可能仍在工作区；新对话开干前建议 `git status` |
| **agent 提前录制** | 已落地 prepare_training 第 0 段；需 agent 在线且儿童端已开 `/child`；改 Runtime 行为后仍须 pack 才进 exe |

---

## 7. 新对话建议开场白

```text
请阅读：
1) docs/UPGRADE_HANDOFF.md（已落地改动与约束；含 §9 机器人端部署）
2) docs/PHASE_DEF_REQUIREMENTS.md（阶段 D/E/F 详细需求）
3) PROJECT_UPGRADE_PLAN.md（总规划与进度日志）
4) 若做相机/注意力：docs/CAMERA_ANALYSIS_QA.md
5) 若做机器人部署/打包/热更新：docs/ROBOT_DEPLOY.md + docs/ROBOT_RUNTIME.md

当前要做：【按产品下一项】；F-IC / F-Algo 已完成，勿无必要重做配置中心

约束：
- 生产 AV 走 robot_runtime + CHILD_MEDIA_MODE=agent；勿再默认开启浏览器 C2 挡服务端样本
- 表达性语言暂不做说话人分割
- 不要无必要推倒 app/core；Real 失败可回退 Mock
- 后端必须监听 0.0.0.0；儿童/表情页 Socket.IO 用本机 /static/js/vendor，勿改回外网 CDN
- 改 robot_runtime 后若要给 exe 测试机用：本机 pack_robot_release.ps1，机器人机 /ui 热更新（或 /robot/download）
- 完成后更新 PROJECT_UPGRADE_PLAN.md 进度日志，并必要时修订 docs/UPGRADE_HANDOFF.md 与 PHASE_DEF_REQUIREMENTS.md
```

---

## 8. 本文维护规则

- 每完成一大块功能或重要 bugfix：更新 §1 表格 + §6 未做项。
- 契约/路径变更：改 §2–§3，避免新对话读到过时分流规则。
- 机器人部署细节变更：改 §9 + `docs/ROBOT_DEPLOY.md` / `ROBOT_RUNTIME.md`。
- 总阶段勾选仍以 `PROJECT_UPGRADE_PLAN.md` §9 为准；细节以本文为准。

---

## 9. Robot Runtime 部署批次（本对话详细记录）

> 细文档：[`ROBOT_DEPLOY.md`](ROBOT_DEPLOY.md)、[`ROBOT_RUNTIME.md`](ROBOT_RUNTIME.md)。此处供跨对话速查。

### 9.1 做了什么

| 项 | 说明 |
|----|------|
| 统一进程 | `robot_runtime/`：媒体采集 + DollSer OSC + 注册心跳 + 运维 `/ui`（端口 **19091**） |
| 兼容入口 | `child_media_agent/agent.py`、`doll/robot_agent.py` 薄包装/弃用提示 |
| 后端模式 | `ROBOT_CONTROL_MODE=robot_runtime`：HTTP 直连已注册 Runtime 的 `/osc/*` |
| 媒体 API | `app/routes/media_upload.py`：帧/音频块上行 + 会话整包补传 |
| 发布包 | `scripts/pack_robot_release.ps1` + `robot_runtime/build_exe.ps1` → `releases/robot/*.zip` + `manifest.json` |
| 下载 | `GET /robot/download`、`GET /api/robot/runtime/version|download` |
| 运维 UI | 后端地址注册；**本地媒体路径**；**检查更新 / 立即更新** |
| 热更新 | 拉 zip，只换 `RobotRuntime.exe`（及 start.bat/README/VERSION），不换 DollSer；旁路 bat 等进程退出再替换 |
| 局域网 | `app.py`：`socketio.run(..., host="0.0.0.0", port=8080)` |
| Socket.IO | 模板改 `/static/js/vendor/socket.io.min.js`，去掉 `cdn.socket.io` |

### 9.2 关键路径

| 路径 | 作用 |
|------|------|
| `robot_runtime/agent.py` | Runtime 主进程；`get_data_dir` / `/config/media-dir` / `/update/*` |
| `robot_runtime/updater.py` | 查版本、下 zip、写 `update_restart.bat` |
| `robot_runtime/register_client.py` | 注册 + `config.json`（含 `mediaDataDir`） |
| `robot_runtime/static/ui.html` | 运维页 |
| `robot_runtime/VERSION` | 打包写入；exe 内嵌 |
| `robot_runtime/packaging/` | 发布用 `start.bat` / `README.txt` |
| `app/robot/release_package.py` | 读 manifest、解析 zip |
| `app/robot/runtime_registry.py` | 后端侧 Runtime 注册表 |
| `templates/robot_download.html` | 下载页 |
| `static/js/vendor/socket.io.min.js` | 本机 Socket.IO 客户端 |
| `releases/robot/` | zip（gitignore）+ 提交 `manifest.json` |

### 9.3 日常工作流（开发机 = 服务器测试机）

1. 改 `robot_runtime/**` 后：仓库根目录执行 `.\scripts\pack_robot_release.ps1`（可 `$env:ROBOT_RELEASE_VERSION="x.y.z"`）。
2. 本机 `python app.py`（zip 已在 `releases/robot/`，后端可直接提供下载）。
3. 机器人 exe 机：`/ui` → 检查更新 → 立即更新；**首次**或热更新器损坏时：浏览器开 `/robot/download` 整包解压。
4. **只改后端模板/静态**（如 Socket.IO 本地化）：重启 `app.py` + 浏览器强刷即可，**不必**重打 Runtime exe。
5. **本机源码调试 Runtime**：`python -m robot_runtime.agent`，改 `.py` 后重启进程即可，不必打包。

### 9.4 热更新语义（勿误解）

- **不是**机器人端 git pull，也不是改 Python 立刻热重载。
- **是**：服务器上有新 zip/新 version → 机器人 exe 自助下载并替换自身后重启。
- 开发机每次要给 exe 机新功能：**仍须 pack 一次**。

### 9.5 联调版本记录（可清理）

曾打过验收包：`hotupdate-test-1`（含 WinError87）→ `hotupdate-test-2`（修复后需手动下）→ `hotupdate-test-3`（热更新链路验证）。`/ui` 上可能仍有绿色验收标记文案。
