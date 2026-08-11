# 阶段 D / E / F 详细需求说明

> **用途**：跨对话实现依据（可直接交给新 Agent）。  
> **前置**：阶段 A–C / C2 / R1–R4、**Robot Runtime 部署**、**连续录制方案 B**、**开课就绪门**已完成，见 [`UPGRADE_HANDOFF.md`](UPGRADE_HANDOFF.md)。  
> **历史总规划**：[`PROJECT_UPGRADE_PLAN.md`](archive/planning/PROJECT_UPGRADE_PLAN.md) §4 仅方向级；**以当前架构与契约为准。**  
> **历史参考源**：[`FEATURE_TRANSFER.md`](archive/planning/FEATURE_TRANSFER.md)、[`realtime_monitor_dashboard_prototype_light.html`](archive/prototypes/realtime_monitor_dashboard_prototype_light.html)。  
> **日期**：2026-07-12（2026-07-13 对照现状修订）  
> **状态**：阶段 **D / E / F-IC / F-Algo 已完成**。D 细节见 [`UPGRADE_HANDOFF.md`](UPGRADE_HANDOFF.md) §3.5；E 见 §3.6；F-IC / F-Algo 见对应 PHASE 文档。

---

## 0. 总原则（三阶段共用）

1. **不推倒**现有 Flask + Socket.IO + `teacher_frontend`；监控台挂在 `/server`，报告仍在教师端。
2. **生产媒体**：`CHILD_MEDIA_MODE=agent`；监控预览若做，优先消费 **服务端已收的 agent 上行帧**降采样副本（见 §1.3 / §2.2 E2），**勿**假设 `/child` 本地摄像头，也**勿**把现有配置页依赖的 Socket `video_frame`（browser 路径）当成 agent 生产下的唯一预览实现。
3. **实时策略**：HTTP Snapshot **约 1s 轮询** + **任意相关 Socket 事件触发立即刷新**；断 Socket 时轮询仍须工作。现有 `/api/server/status`（约 5s）**不等于** MonitorSnapshot，不可替代。
4. **不做**：说话人分割、临床诊断措辞、默认外网 LLM 叙事；F 不阻塞 D/E。
5. **文案边界**：凡面向人的分析结论，保留「仅供教育训练参考」。

### 0.1 阶段字母对照（避免误读）

| 字母 | 本文含义 | 说明 |
|------|----------|------|
| **D** | Server 监控台 + Snapshot | **已完成**（预览帧等增强见 E2） |
| **E** | 报告公式打磨 / 监控增强 / 降级 / 测试 | **不是** Robot Runtime 打包部署 |
| **F** | `/server` 配置中心形态升级 | **F-IC + F-Algo 已完成** |
| （已完成，不在本文范围） | Robot Runtime 部署、连续录制 B、就绪门、presence | 见 `UPGRADE_HANDOFF.md` |

### 0.2 实现时必须遵守的已落地架构（勿回退）

| 约定 | 要点 |
|------|------|
| **连续录制（方案 B）** | 整场一个 `mediaSessionId`；切题**不** `/record/stop`→`/record/start`；落盘 `static/recordings/sessions/{姓名-年龄-日期-N}/` + `timeline.csv` |
| **分析** | 切题 `reconfigure_session`（不清 buffer）；首个非 aux 课点才开分析 |
| **行为层** | 仍用 `training_session_id` + `open_window` / `close_window`；报告路径不变 |
| **就绪门** | 选课→控制页前 Gate；`readiness_*` 事件；监控可选展示，**非 D 必做** |
| **agent / browser** | 生产 agent：注意力/情绪走服务端；agent 下儿童端跳过 C2 |

---

## 1. 阶段 D — Server 监控台与实时同步（P2）

### 1.1 目标

在 `/server` 保留现有**配置控制台**的同时，增加**数据可视化（监控台）**视图，训练进行中可约 1s 延迟看到注意力、题目进度、语音/健康状态等。

### 1.2 产品范围（必做 / 刻意不做）

| 必做 | 刻意不做（留给 E 或砍掉） |
|------|---------------------------|
| 顶栏/导航：配置 ↔ 监控 双视图切换 | 完整源项目 Vosk/Piper 六段流水线 UI（可缩成「语音管线摘要」） |
| `MonitorSnapshot` HTTP API | 监控台内「暂停课程 / 人工标注」等运营操作（原型有按钮，D 可只展示或 disabled） |
| 布局对齐浅色原型主结构 | MediaPipe 浏览器采集迁入监控页 |
| 1s poll + Socket 触发刷新 | 高帧率实时视频流（预览帧可选，默认可占位） |
| 绑定当前活跃 `training_session_id` / **整场** media session | 多训练会话并行盯盘（第一版单活跃会话即可） |

### 1.3 UI 信息架构（对齐原型，可裁剪）

历史原型见 `archive/prototypes/realtime_monitor_dashboard_prototype_light.html`，第一版建议四块：

1. **实时摄像头与注意力**  
   - 注意力分数（0–100）、状态文案、数据质量 `VALID|DEGRADED|MISSING`  
   - 本题关注比例 / 样本数（有则显示）  
   - 预览区：无预览 API 时显示「预览未启用 / agent 无本地预览」占位，**不要假视频冒充真实画面**  
   - **注意**：现有 `server.js` 的 `#live` + Socket `video_frame` 仅对 **browser** 联调有效；agent 生产下应占位，直到 E2 接通服务端抽稀预览

2. **双屏状态摘要**  
   - 儿童端：当前课点标题、题序、用时、在线与否（来自 session / play_resource / `client_presence`）  
   - 机器人端：当前动画/播放状态摘要（有则显示；无则「未知」）  
   - 可选只读：本场录像目录名 `humanDirName`（便于口头核对）  
   - 快捷链：打开真实 `/child`、`/robot`（原型已有）

3. **语音与表达性语言摘要**（精简版）  
   - 是否在收声、最近 ASR/匹配文本片段、表达性语言观测最近一条的质量  
   - **不要**照搬源项目完整「脱敏→LLM→安全审核→Piper」步骤，除非本仓已有对应状态机字段

4. **实时分析趋势**  
   - 近 N 秒（建议 60s）注意力曲线  
   - 可选：情绪三色占比迷你条（已有 emotion 观测则接；无则隐藏）

顶栏健康徽章：Socket 连接态、刷新来源 `poll|ws`、分析器 Real/Mock 提示（若易取）、`mediaMode`、可选 readiness 摘要。

### 1.4 `MonitorSnapshot` 契约（本仓适配版）

**建议路由：**

```http
GET /api/monitor/snapshot
GET /api/monitor/snapshot?trainingSessionId=<id>
```

无查询参数时：取当前「活跃训练会话」；若无活跃会话，返回 `success: true` + `data.active: false`（或等价），UI 显示空态。

**建议 JSON 形状（字段可增不可 silently 改名）：**

```json
{
  "success": true,
  "data": {
    "generatedAt": "ISO-8601",
    "active": true,
    "refreshHint": { "pollIntervalMs": 1000 },
    "session": {
      "trainingSessionId": "...",
      "mediaSessionId": "...",
      "runtimeSessionId": "...",
      "humanDirName": "张小明-6-20260713-1",
      "recordingMode": "continuous",
      "studentId": null,
      "startedAt": "...",
      "status": "warmup|active|finalizing|ended"
    },
    "course": {
      "courseType": "mimic|pairing|sequencing|speech|...",
      "courseTypeId": null,
      "courseItemId": null,
      "entryId": "...",
      "title": "...",
      "questionIndex": 0,
      "questionTotal": null,
      "questionElapsedSec": 0,
      "questionId": "..."
    },
    "attention": {
      "currentScore": 84,
      "currentQuality": "VALID",
      "provider": "server|browser",
      "sampleCount": 12,
      "questionAttentionRatio": 0.79,
      "recentSamples": [
        { "t": "...", "score": 80, "quality": "VALID" }
      ]
    },
    "emotion": {
      "available": true,
      "positiveRatio": 0.4,
      "neutralRatio": 0.5,
      "negativeRatio": 0.1,
      "sampleCount": 8
    },
    "voice": {
      "pipelineActive": true,
      "lastTranscript": "...",
      "lastMatchOk": null,
      "expressive": {
        "speechRatio": 0.3,
        "quality": "VALID|DEGRADED|MISSING"
      }
    },
    "robot": {
      "online": true,
      "animation": null,
      "audioPlaying": false
    },
    "health": {
      "socketClients": { "teacher": 1, "child": 1, "server": 1 },
      "mediaMode": "agent|browser",
      "analyzers": { "attention": "real|mock", "speech": "real|mock" },
      "limitations": [],
      "readiness": null
    },
    "events": [
      { "t": "...", "type": "question_opened|attention_update|...", "summary": "..." }
    ],
    "preview": null
  }
}
```

**连续录制语义（组装时务必遵守）：**

- `mediaSessionId` / `runtimeSessionId`：方案 B 下整场通常为**同一** ID（prepare 时创建，切题复用）。  
- `humanDirName`：来自 session metadata / `session_meta.json`；无则 `null`。  
- `recordingMode`：固定期望 `"continuous"`。  
- 切题只更新 `course` / `questionId` 与行为窗口，**不要**按「每题一个 runtime session」去枚举多段 AVI。  
- `status=warmup`：已 `prepare_training`、尚未首个非 aux `play_resource`（此时可无注意力分析）。

**组装数据源（本仓已有）：**

| 块 | 优先来源 |
|----|----------|
| session / course | `BehaviorService` / SessionManager / 最近非 aux `play_resource`；metadata 中 `human_dir_name`、`recording_mode` |
| attention / emotion | behavior store 观测（遵守 mediaMode 选源，与报告一致） |
| voice | AudioPipeline / speech matcher 最近状态 + language 观测 |
| robot | robot_runtime / OSC 状态若已有；否则可空 |
| health | `events.py` presence / status 快照、config_manager analyzer 模式；可选 `readiness_service` 摘要 |
| events | 可选环形缓冲（内存），D1 可先空数组 |
| 媒体路径（只读摘要） | `app/services/recording_timeline.py` / `session_meta.json`（勿在监控台触发停录） |

### 1.5 刷新策略

| 机制 | 行为 |
|------|------|
| HTTP 轮询 | 监控 Tab 可见时每 **1000ms** `GET snapshot` |
| Socket 触发 | 收到与训练相关的事件后**立即**再拉一次（不必等下一轮 poll） |
| 建议监听（已有则复用） | `play_resource`、`attention_update`、`session` 相关、`camera_analysis`（browser）、`training_prepare` / `prepare_training_ack`、`finalize_training` / ack、课点切换/结束；可选 `readiness_update` / `readiness_complete`、`client_presence` |
| 断线 | UI 标「Socket 离线」；轮询继续 |
| 可见性 | `document.hidden` 时可降频或暂停 poll，切回前台立即拉一次 |

实现形态建议：

- **UI**：`templates/server.html` 加 Tab；监控区可用原生 JS（与现有 `static/js/server.js` 一致），或拆 `static/js/server_monitor.js`。  
- **不必**新建 React 应用；教师端继续只管控课/报告。  
- ControlPage 上的实时注意力属于**教师控课 UI**，**不能**代替本阶段 `/server` 运营监控台。

### 1.6 后端落地建议（文件级）

| 步骤 | 建议路径 |
|------|----------|
| D1 Snapshot 服务 | 新建 `app/monitor/snapshot.py` + `app/routes/monitor.py` |
| D2 注册路由 | `app.py` 注册 blueprint |
| D3 Server 双 Tab | `templates/server.html` + CSS；配置区现有逻辑不动 |
| D4 前端刷新 | `static/js/server_monitor.js`：poll + socket.on → fetch |
| D5 样式 | 可从原型抽 CSS 变量/面板结构，保持浅色运营风，勿做成另一套品牌站 |

### 1.7 验收标准（阶段 D）

1. `/server` 可在「配置控制」与「数据可视化」间切换，配置热更新能力不回退。  
2. 上课中打开监控 Tab：注意力分数与质量约 **1s 内**随真实观测变化。  
3. 切换课点后，题目/课型摘要更新（**同一** `mediaSessionId`，仅 course/question 变）。  
4. 断开浏览器 Socket（或停后端 Socket）后，仅靠轮询仍能看到分数变化（后端仍在写观测时）。  
5. `CHILD_MEDIA_MODE=agent` 时不因无本地摄像头而刷假「不专心」；质量应为 `MISSING/DEGRADED` 或占位说明；预览区不假冒画面。  
6. 无活跃训练时监控为空态，不报 500。

### 1.8 建议拆对话

| 子阶段 | 范围 |
|--------|------|
| D1 | Snapshot API + 单测/手工 curl |
| D2 | Server 导航 + 监控静态壳（可绑假数据） |
| D3 | 接真实 Snapshot + poll/ws 刷新 |

**开场白关键词：** `阶段D Server监控台 Snapshot 实时同步` + 读本文 §1。

---

## 2. 阶段 E — 打磨、可配置、降级与测试（P3）

### 2.1 目标

演示稳定、参数可调、缺数据时**说清楚限制**，并补最小自动化测试，清理 A–D 临时。

### 2.2 需求包

#### E1 — 报告公式与叙事可配置（加固）

现状：已有 `config/report_scoring.yaml` + `app/report/scoring.py`。

| 子项 | 状态（2026-07-16） | 仍要做 |
|------|-------------------|--------|
| yaml + scoring 存在 | **已有** | — |
| `formulaVersion` 写入报告快照 | **已有** | — |
| 改 yaml → **新生成**报告用新权重（旧报告保留版本） | **已有** | 见 [`docs/REPORT_SCORING.md`](REPORT_SCORING.md) |
| `narrative_provider: rule\|mock`；LLM 默认关 | **已有**（已真正读配置） | — |
| `dataQuality.limitations[]` 进报告 API/UI | **已有**（含中文 `limitationLabels`） | — |
| 打印横竖屏 | **已有** | 抽检清单见 REPORT_SCORING §6 |
| 权重/阈值含义与调参范围文档 | **已有** | — |
| 「上课中途改权重」策略说明 | **已有** | — |

#### E2 — 监控增强（接在 D 之后）

| 项 | 状态（2026-07-16） |
|----|------|
| 预览帧通道 | **已有**：`MONITOR_PREVIEW_ENABLED` + probe 缓存；TTL/最大字节；仅预览不进评分 |
| 事件列表 | **已有**：课点开闭 / 匹配成功 / 质量降级环形缓冲 |
| 健康徽章 | **已有**：Real/Mock、mediaMode、agent 在线、预览 stale |
| 运营按钮 | **占位**：暂停/静音 disabled + tooltip |

预览数据路径优先：

- **agent（推荐）**：从服务端已收视频帧（media 上行 / probe 缓存）抽稀；**禁止**仅依赖 browser 的 Socket `video_frame` 作为生产预览  
- 或 robot_runtime 另推 preview（本版未做）  
- **browser**：可从 child 另 POST preview（本版未做）

#### E3 — 降级与 limitations 产品规则

| 场景 | 期望 | 状态（2026-07-16） |
|------|------|----------|
| 无人脸 / 摄像头失败 | `quality=MISSING`；**禁止**把孩子标成低注意力 | **已有**（监控 score=null；控课 badge「无有效样本」） |
| 仅 Mock 分析器 | 监控与报告 limitations 明确「演示/占位数据」 | **已有** |
| 无语音活动 | 表达性语言维度降级，不伪造高分 | **已有**（scoring） |
| PARTIAL 报告 | 教师端轮询 + 中文 limitations | **已有** |

#### E4 — 测试与清理

**最小单测（Python）：**

| 用例 | 状态 |
|------|------|
| `compute_dimensions` 权重边界与缺维 | **已有**（`tests/test_report_scoring_v2.py` 等） |
| behavior 聚合选源（prefer_browser vs server） | **已有**（`tests/test_attention_source_selection.py`） |
| `get_monitor_snapshot` 无会话 / 有会话字段存在性 | **已有**（`tests/test_monitor_snapshot.py`，含 MISSING/预览开关） |
| 连续录制切题不 stop/start（可选回归） | **已有**（`tests/test_continuous_recording.py`） |

**清理：**

- `.gitignore` 已覆盖 `temp_asr_*.wav`、`tests/_tmp_*/`  
- 确认 `__pycache__` / 临时 wav 不被提交  

### 2.3 验收标准（阶段 E）

1. 只改 `report_scoring.yaml` 即可改变新生成报告的综合权重（旧报告保留生成时版本）。（**已满足** + 文档）  
2. 关摄像头上课：报告/监控 limitations 可见，注意力不因 MISSING 被算成「差」。（**已满足**）  
3. 监控预览若启用：stale 超时有标识；关闭开关后 UI 回占位。（**已满足**）  
4. 上述最小单测在 CI 或本地 `pytest` 可跑通。  
5. `UPGRADE_HANDOFF.md` / 计划进度日志更新。

**阶段 E 状态：已完成（2026-07-16）。**

### 2.4 建议拆对话

| 子阶段 | 范围 |
|--------|------|
| E1 | 公式文档 + 打印抽检清单 + limitations 文案统一（代码侧大多已有） |
| E2 | 监控预览/事件/健康（可砍预览） |
| E3 | 选源单测 + Snapshot 单测 + 死代码/临时文件清理 |

**开场白关键词：** `阶段E 打磨 公式配置 降级 limitations` + 读本文 §2。

---

## 3. 阶段 F — 配置中心形态升级（P4）

> **F-IC（已完成）：** [`PHASE_F_INTERACTIVE_CONTENT_CONFIG.md`](PHASE_F_INTERACTIVE_CONTENT_CONFIG.md)  
> **F-Algo（已完成）：** [`PHASE_F_ALGO_CONFIG.md`](PHASE_F_ALGO_CONFIG.md) — 概览 / 摄像头与注意力 / 语音 / 报告权重；下文 §3.3 为摘要，以独立文档为准。

### 3.1 目标

把现有 `/server`「分析器 YAML 热更新控制台」升级为更接近 `temp_robot-config-prototype` 的**配置控制面**，并优先补齐**交互内容**可视化（课与机器人演什么），**不阻塞**报告与监控主链路。

### 3.2 与原型的关系

| 原型资产 | 用途 |
|----------|------|
| `temp_robot-config-prototype/CONFIG_CENTER_DESIGN_SPEC.md` | 产品与交互规格（权威参考） |
| `config-center-prototype.html` | 高保真交互示意 |
| `design-*.png` | 视觉参考 |

**本仓必须收缩范围**：原型含五级覆盖、Secret、模型注册、告警等，全部一次做完不现实。

**基线说明：** 现有 `/server`（分析器预设、审计、robot/child media mode）与 `/robot`（动作库、课程映射）是 F 的能力子集；实现时应**迁入/扩展**而非推倒。

### 3.3 本仓 F 切片

#### F-IC — 交互内容（优先，详见独立文档）

课程库、媒资库、动作库、表情库、行为绑定；视觉对齐原型。  
→ [`PHASE_F_INTERACTIVE_CONTENT_CONFIG.md`](PHASE_F_INTERACTIVE_CONTENT_CONFIG.md)

#### F-Algo — 算法与评分配置（后置 → 现为 F 剩余主线）

→ **[`PHASE_F_ALGO_CONFIG.md`](PHASE_F_ALGO_CONFIG.md)**（字段、API、子阶段 F-Algo0→4、开场白）

摘要：侧栏启用概览 / 摄像头与注意力 / 语音与音频 / 报告与评分；复用 `/api/server/config*`（analyzers）；为 `camera_analysis` / `report_scoring` 补写盘；权重和=100；高级 YAML 逃生口。

**明确不做（F 共性）：** 完整五级覆盖 UI、任意 System Prompt、Safety 引擎重做、多角色权限、把教师/儿童业务迁进配置中心。

### 3.4 技术建议

- 路由：`/server/config` + 监控互跳；F-IC 落地 `/server/config/content`。  
- 实现：继续 Jinja + JS；视觉跟原型。  
- 课程写 API 新建；动作/映射尽量复用 `/api/robot/*`。  

### 3.5 验收标准

**F-IC：** 见交互内容文档 §11。  

**F-Algo：** 见 [`PHASE_F_ALGO_CONFIG.md`](PHASE_F_ALGO_CONFIG.md) §8。

### 3.6 建议独立里程碑

- **F-IC：** 已完成（见交互内容文档）。  
- **F-Algo：** 读 [`PHASE_F_ALGO_CONFIG.md`](PHASE_F_ALGO_CONFIG.md) 文首决策，按该文 §9 开场白；**F-Algo0→1→2→3→4**。

**开场白关键词：** `阶段F F-Algo` + 读 `PHASE_F_ALGO_CONFIG.md`。

---

## 4. 依赖与顺序

```text
A–C / R / Runtime部署 / 连续录制B / 就绪门 / **D 监控台**  已完成
    ↓
E1 文档/清单/文案 → E2 监控增强 → E3 测试清理   ← **已完成（2026-07-16）**
    ↘
     F 配置中心 MVP（可调研并行，实现靠后）  ← **下一主线**
```

**硬依赖：**

- D 的正式验收必须接 behavior 真实观测（已具备，且连续录制下注意力不因切题清零）；可用假数据做 UI 壳，但合并前要换真源。  
- E2 预览依赖媒体管线，可整包延期；实现时走 **agent 上行抽稀**，勿回退到 browser-only 预览。  
- F 的「报告与评分」模块依赖 E1 的 formulaVersion 约定更稳妥（version **已写入报告**；UI/文档对齐即可）。

---

## 5. 新对话开场白（复制用）

### 做阶段 D

```text
请阅读 docs/UPGRADE_HANDOFF.md 与 docs/PHASE_DEF_REQUIREMENTS.md §1（阶段 D）。
参考 realtime_monitor_dashboard_prototype_light.html 与 FEATURE_TRANSFER.md 的 MonitorSnapshot。
当前只做阶段 D（可先 D1 Snapshot API）。
约束：生产 agent 路径；1s poll + Socket 触发；保留 /server 配置台；不推倒 app/core。
必须遵守连续录制方案 B：整场一个 mediaSessionId，Snapshot 含 humanDirName/recordingMode；切题不按多段 AVI 建模。
完成后更新 PROJECT_UPGRADE_PLAN.md 进度日志与 UPGRADE_HANDOFF.md。
```

### 做阶段 E

```text
请阅读 docs/PHASE_DEF_REQUIREMENTS.md §2 与现有 config/report_scoring.yaml。
当前做阶段 E【E1/E2/E3 指定一个】。
注意：formulaVersion / limitations / 部分单测已有，优先补文档、监控侧降级与剩余测试。
约束：缺数据用 limitations；禁止 MISSING 当低注意力；LLM 叙事默认关；agent 预览勿仅依赖 video_frame Socket。
```

### 做阶段 F（交互内容 · 已完成时可跳过）

```text
请阅读 docs/PHASE_F_INTERACTIVE_CONTENT_CONFIG.md 与 docs/PHASE_DEF_REQUIREMENTS.md §3。
当前只做 F-IC；不要做 F-Algo 除非明确要求。
```

### 做阶段 F-Algo（配置中心算法/评分）

```text
请阅读 docs/PHASE_F_ALGO_CONFIG.md（优先）与 docs/PHASE_DEF_REQUIREMENTS.md §3、docs/REPORT_SCORING.md。
F-IC 已完成：只做 F-Algo0→1 起（或你指定子阶段）。复用 analyzers 配置 API；为 camera/report yaml 补写盘。
不要做五级覆盖/Secret/模型注册。不要推倒交互内容。先出页面/API 清单确认再写代码。
```

---

## 6. 文档关系

| 文件 | 角色 |
|------|------|
| `PROJECT_UPGRADE_PLAN.md` | 总规划 + 进度勾选 |
| `docs/UPGRADE_HANDOFF.md` | **已落地**事实（含 Runtime、连续录制、就绪门、D/E） |
| **`docs/PHASE_DEF_REQUIREMENTS.md`（本文）** | D/E 已完成；F 总框 |
| `docs/PHASE_F_INTERACTIVE_CONTENT_CONFIG.md` | F-IC 交互内容（已完成） |
| `docs/PHASE_F_ALGO_CONFIG.md` | **F 剩余：算法与评分（F-Algo）** |
| `docs/REPORT_SCORING.md` | 报告公式调参与打印抽检（阶段 E1） |
| `docs/CONTINUOUS_RECORDING_TIMELINE_PLAN.md` | 连续录制方案 B（媒体层已落地） |
| `docs/TRAINING_READINESS_GATE_PLAN.md` | 开课就绪门（已落地） |
| `FEATURE_TRANSFER.md` | 源项目契约与可复用边界 |
| `docs/CAMERA_ANALYSIS_QA.md` | 注意力/情绪验收（D 监控也须遵守） |
