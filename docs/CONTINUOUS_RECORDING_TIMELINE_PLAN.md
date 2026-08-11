# 整场连续录制 + 时间轴标注（CSV）设计说明

> **状态**：方案 B 已落地（2026-07-13）  
> **日期**：2026-07-13  
> **前置**：开课就绪门、warmup→课点 session 切换、注意力近窗与毫秒时间戳归一化已落地（见 `UPGRADE_HANDOFF.md`）  
> **现状摘要**：当前为「整次训练一个 `training_session_id` + **多段** runtime `session_id` 分段落盘」；每课点 `play_resource` 会 stop/start Media Agent，易漏录、分析中断、目录难辨认。

---

## 0. 结论（先读）

### 0.1 方案评判

| 方案 | 做法 | 工作量 | 推荐 |
|------|------|--------|------|
| **A. 连续录 + 同步拆分落盘** | 全程一份主文件，同时按切题时刻再写多份 clip | 大：双写、时钟对齐、半截文件、磁盘倍增 | 不推荐作 P0 |
| **B. 连续录 + CSV/JSON 时间轴**（用户倾向） | **优先保留一整份** video/audio；切题只记时间戳标注；需要 clip 时后处理切 | 中：改启停边界 + 写标注文件 + 目录命名 | **推荐** |
| C. 维持分段，仅改善命名 | 仍频繁 stop/start | 小，但不解决漏录与分析中断 | 仅作过渡不可取 |

**采纳 B 的理由：**

1. **优先保证不断录**：与「注意力/情绪连续识别」目标一致；根因上消除课点切换 stop/start。  
2. **工作量更小**：不必做实时双写与 clip 编码器；标注文件即可支撑事后剪辑/质检。  
3. **与现有行为层契合**：已有 `training_session_id` + `open_window/close_window`（题目窗口）；媒体层改为「一场一盘」，分析窗口与标注可共用同一套切题事件。  
4. **可演进**：P2 再加「按 CSV 离线切 clip」工具即可，不必阻塞主路径。

### 0.2 一句话目标

从教师点「开始评估/训练」到 `finalize_training`（或取消），**Media Agent / 服务端只维护一条连续录像**；课点切换只写入时间轴标注；落盘目录人类可读：`姓名-年龄-日期-N/`，内含完整视频、完整音频、本场 `timeline.csv`；根目录维护课程/条目对照表供查阅。

---

## 1. 现状与问题（审查结论）

### 1.1 当前分段模型

| 段 | 起点 | 终点 | 分析 |
|----|------|------|------|
| warmup | `prepare_training` | 首个非 aux `play_resource` | 否 |
| 课点段 | 每个非 aux `play_resource` | 下一课点或 finalize | 是 |

关键路径：

- `app/sockets/handlers.py`：`PrepareTrainingHandler` / `PlayResourceHandler` / `FinalizeTrainingHandler` / `_close_runtime_session`
- `static/js/child.js`：`startRecording` / `stopRecording`（课点切换强制 agent `/record/stop` + `/record/start`）
- `robot_runtime/agent.py`：每次 start 可 `rmtree` 同 session 本地目录
- 落盘：`static/recordings/{uuid}/` → `video.avi` / `audio.wav` / 可选 `archive_meta.json`

### 1.2 痛点

1. **频繁启停**：切题必停录再开，易丢秒级内容，文件碎片多。  
2. **分析绑定分段 session**：注意力/情绪随 runtime session 启停，体感不连续。  
3. **目录名为 UUID**：无法按学生/日期检索；与「第几次」无关。  
4. **事后难对齐**：虽有 behavior `windows/*.json`，但媒体文件按段散落，需人工拼接。

### 1.3 已有可复用资产

- `training_session_id`（behavior 层整场 ID）  
- `open_window` / `close_window`（`opened_at` / `closed_at`）  
- `Student.name` / `Student.age`（`database/models.py`）  
- `CourseType` / `CourseItem` 主键与名称  
- Gate / warmup 采集链路（连续录后 Gate 仍可挂在同一 media session 上）

---

## 2. 详细需求

### 2.1 录制生命周期（必须）

1. **Start（开录）**：`prepare_training` 成功且儿童端 agent/browser 开始采集时，启动**本场唯一**录制会话；此后直到结束**不得**因切题 stop/start。  
2. **Mark（打点，不启停）**：每次非 aux 的 `play_resource`（教师切换课点内容）写入时间轴一行；关闭上一题窗口、打开新题窗口（行为层逻辑可保留）。  
3. **Aux 不打点**：提问/表扬/提示等 aux 操作**不**新建时间轴段、**不**影响录制。  
4. **Stop（停录）**：仅在以下情况停止整场录制并落盘收尾：  
   - `finalize_training`  
   - `cancel_prepare_training`（选课返回，未正式上课）  
   - 异常断线超时策略（P1，见风险）  
5. **分析连续**：整场共用一个分析上下文（或「媒体连续 + 分析窗口随切题重置目标，但不清 buffer」——实现见 §4）；禁止因切题 `end_session` 导致注意力中断。

### 2.2 落盘目录命名（必须）

格式：

```text
{姓名}-{年龄}-{日期}-{N}/
```

约定：

| 字段 | 规则 |
|------|------|
| 姓名 | `Student.name`；文件系统非法字符替换为 `_`；空名用 `student{id}` |
| 年龄 | `Student.age`；缺失用 `NA` |
| 日期 | 本场开录日，本地时区 `YYYYMMDD` |
| N | 同一学生、同一自然日内的第几次**成功开录**（从 1 递增）；以服务端登记为准，避免双端不一致 |

示例：`张小明-6-20260713-2/`

目录建议位置（二选一，实现时定一种并写进 CONTRACT）：

- **推荐**：`static/recordings/sessions/{姓名-年龄-日期-N}/`  
- 兼容期可保留 uuid 软链或 `manifest.json` 里同时写 `legacySessionId`

目录内文件（一场一份）：

```text
{姓名-年龄-日期-N}/
  video.avi          # 或最终选定的容器格式
  audio.wav
  timeline.csv       # 本场时间轴
  session_meta.json  # 可选：studentId、trainingSessionId、startUtc、mediaMode、N、原始 uuid
  archive_meta.json  # agent 补传后保留/合并
```

Behavior 报告数据可仍放在 `static/recordings/behavior/{training_session_id}/`，并在 `session_meta.json` 中交叉引用。

### 2.3 本场 `timeline.csv`（必须）

**推荐列（比用户口述略完整，便于后处理；展示层仍可用课程 id / item id）：**

| 列名 | 说明 |
|------|------|
| `seg_index` | 段序号，从 0 或 1 起，整场唯一递增 |
| `seg_kind` | `warmup` \| `course` \| `gap`（可选） |
| `course_type_id` | DB `course_type.id`；warmup 为空或 0 |
| `course_item_id` | DB `course_item.id`；warmup 为空或 0 |
| `course_id` | DB `course.id`（可选但建议有，避免跨课程 item 歧义） |
| `question_id` | 现有 behavior `question_id` 字符串，便于对接报告 |
| `t_start_sec` | 相对**本场录像起点**的秒（浮点，建议 3 位小数） |
| `t_end_sec` | 相对起点秒；未结束可空，finalize 时回填 |
| `t_start_hms` | 可读 `H:MM:SS` 或 `M:SS`（由秒生成，避免手写不一致） |
| `t_end_hms` | 同上 |
| `wall_start_iso` | 墙钟 ISO（审计用） |
| `wall_end_iso` | 墙钟 ISO |

用户期望的最小形态也可接受为三列：`course_type_id, course_item_id, time_range`，但**实现上建议写宽表**，另提供只含三列的导出视图亦可。

**时间基准（关键）：**

- `t=0` = 本场录像文件第一帧对应的服务端/agent 统一起点（写入 `session_meta.json.recording_started_at`）。  
- 切题打点用**同一时钟**：优先「agent 上报的录制单调时钟 / 帧 timestamp（已归一化为秒）」；若不可用则用服务端 `time.time() - recording_started_at`。  
- **禁止**混用未归一化的毫秒戳（已有教训）。

**段边界语义：**

- 新课点开始：上一行 `t_end_*` = 当前打点；新行 `t_start_*` = 当前打点。  
- finalize：最后一行补 `t_end_*` = 录像总时长。  
- warmup：第一行 `seg_kind=warmup`，从 `t=0` 到首个课点。

### 2.4 根目录对照表（必须）

在音视频保存根目录（建议 `static/recordings/`）放置**可重新生成**的查阅文件，例如：

1. `course_type_lookup.csv`  
   - `course_type_id,name,name_en`  
   - 例：`1,命名,naming` …（以 DB 实际 id 为准，**不要写死假设 1=命名**；文档示例仅示意）

2. `course_item_lookup.csv`（可较大）  
   - `course_item_id,course_id,course_type_id,name,media_file`  

或单文件 `lookup_manifest.csv` + 生成脚本。  

要求：

- 提供管理命令或启动时/导入课程后刷新（如 `python -m tools.export_recording_lookups`）。  
- 对照表与 DB 不一致时，以 DB 为准并提示重新导出。

### 2.5 非目标（本阶段不做）

- 实时生成每题独立 AVI clip（可列为 P2 离线工具）。  
- 说话人分割、多摄像头拼接。  
- 改变教师评分/报告公式（仅增加媒体时间轴引用）。

### 2.6 验收标准

1. 一场完整上课：磁盘上**仅一个**主 video + 一个主 audio（外加 meta/csv）；无「每题一个近空 AVI」。  
2. 切题瞬间 agent **无** `/record/stop`→`/record/start`（可用 Runtime 日志验证）。  
3. 捂脸/正视时注意力在整场过程中连续更新（不因切题清零过久）。  
4. `timeline.csv` 段数 = 1（warmup）+ 非 aux 课点数；时长与 `ffprobe` 总时长误差 &lt; 1s（目标）/ &lt; 2s（底线）。  
5. 同日同生第二次开录目录名为 `…-2`。  
6. 根目录 lookup CSV 能把 timeline 中的 id 反查到中文名。

---

## 3. 前端设计

> 原则：教师主流程少打断；命名与 CSV 对教师近乎无感，对教研/质检可查。

### 3.1 教师端（`teacher_frontend`）

| 位置 | 改动 |
|------|------|
| 控制页结束/报告入口 | 可选展示「本场录像目录名」只读文案（`张小明-6-20260713-1`），便于口头核对 |
| 选课/学生信息 | 无需为录制单独改交互；开录仍走现有「开始评估 → Gate → 控制页」 |
| 开发/运维页（若有 `/server`） | 列出最近 sessions：目录名、时长、段数、是否已补传 |

**不需要**在切题弹窗里让老师填 CSV。

### 3.2 儿童端

- `training_prepare`：start 一次录制（整场）。  
- `play_resource`：**不再**因新 `sessionId` stop/start；若服务端仍下发 mediaSessionId，仅更新「标注用 id」，录制句柄保持。  
- `finalize` / `cancel`：唯一 stop。  
- UI 无新增，除非调试开关显示「连续录制中」。

### 3.3 质检/后处理（可后做简易页或脚本）

- 输入：一场目录 + `timeline.csv`  
- 输出：按行切出的 clip 列表（P2）  
- 前端若做：表格预览 `t_start–t_end` + 课程名（join lookup）

### 3.4 文案与提示

- 失败时：「整场录制未启动，请检查 Runtime」——比「某一课点录制失败」更准确。  
- 取消选课：明确「将丢弃/保留 warmup 连续段」策略（建议 cancel 仍保存已录片段 + 不完整 timeline，目录仍按命名规则落盘并标 `status=cancelled`）。

---

## 4. 技术实现规划

### 4.1 目标架构

```text
prepare_training
  → 创建 training_session_id
  → 分配 human_dir_name = 姓名-年龄-日期-N
  → 创建 media_session（整场唯一）
  → Media Agent /record/start(media_session_id) 一次
  → analysis_service.start_session(media_session_id) 一次（或 Gate 后再开分析，但媒体已连续）
  → timeline 写入 warmup 行 t_start=0

play_resource（非 aux）
  → 关闭上一 question window / 打开新 window（behavior 不变）
  → timeline：结束上一行，开始新行（仅打点）
  → 更新语音/姿态目标等（分析目标切换，不清空媒体）
  → 不调用 agent stop/start

finalize_training
  → 回填 timeline 最后 t_end
  → agent /record/stop → 补传整场文件到 human_dir
  → analysis end_session
  → 写 session_meta.json
```

### 4.2 模块改动清单（按优先级）

#### P0（打通连续录 + CSV + 命名）

| 模块 | 改动要点 |
|------|----------|
| `handlers.PrepareTrainingHandler` | 生成目录名与 N；创建整场 media session；写 `session_meta` 骨架；timeline 开 warmup |
| `handlers.PlayResourceHandler` | **删除**「关旧 runtime + 新 start_recording」媒体切换；改为 timeline mark + behavior window；分析只切目标不切媒体 session |
| `handlers.Finalize` / `CancelPrepare` | 停整场录制；finalize timeline；补传路径指向 human_dir |
| `static/js/child.js` | `startRecording`：同 mediaSessionId 或「整场模式」直接 return；切题不 stop |
| `robot_runtime/agent.py` | 支持长录；**禁止**同场中途 rmtree；可选上报 `recording_elapsed_ms` 供打点 |
| `media_service` / `media_upload` | 落盘到 `sessions/{human_dir}/`；补传整场一份 |
| 新建 `app/services/recording_timeline.py`（名可议） | 负责 CSV 追加、回填 end、导出 lookup |
| 测试 | 无切题 stop；timeline 行数；命名 N 递增；毫秒戳不影响 offset |

#### P1

| 项 | 说明 |
|----|------|
| 断线重连 | 儿童页刷新后如何附着同一 media_session（token / trainingSessionId 查询） |
| 时钟校准 | agent 心跳带 `elapsed_ms`，服务端打点优先用它 |
| Gate | 明确 Gate 期间已在连续录制中；探针不另开录制 |
| 目录名冲突 | 同秒并发（极少）时 N 原子递增加文件锁 |

#### P2

| 项 | 说明 |
|----|------|
| 离线切 clip 脚本 | 读 timeline + ffmpeg |
| 双写可选 | 配置开关 `RECORD_ALSO_SPLIT_CLIPS=0` 默认关 |
| 旧 UUID 目录迁移说明 | 文档即可 |

### 4.3 分析层策略（与连续录对齐）

**推荐：媒体 session 不断；题目窗口仍按课点开闭。**

- `analysis_service`：整场一个 `session_id`（= media_session_id）。  
- 切题：`set_speech_target` / `set_pose_target` / behavior `open_window`；**不要** `end_session`+`start_session`。  
- 注意力 buffer 连续，符合「高低能及时变化」的产品诉求。  
- 报告仍按 `question_id` 窗口聚合观测（现有 behavior 路径）。

### 4.4 ID 体系（避免再混）

| ID | 含义 | 出现位置 |
|----|------|----------|
| `training_session_id` | 整场行为/报告 | behavior JSON、timeline meta |
| `media_session_id` | 整场录制与分析 | agent、上行 URL、可选写入 meta（可与旧 uuid 同形） |
| `human_dir_name` | 人类可读目录 | 文件系统 |
| `course_type_id` / `course_item_id` | DB 主键 | timeline.csv、lookup |
| `question_id` | `{courseId}_{itemId}_{index}` | behavior、timeline |

### 4.5 CSV 与 Lookup 生成伪流程

```text
on_prepare:
  N = count_dirs(student, date) + 1
  human = sanitize(f"{name}-{age}-{date}-{N}")
  mkdir recordings/sessions/{human}
  write session_meta.json
  append timeline: warmup, t_start=0

on_play_non_aux:
  close previous timeline row (t_end = now_offset)
  open new row (course_type_id, course_item_id, ...)

on_finalize:
  last row t_end = duration
  flush timeline.csv
  ensure lookups up to date (or lazy)
```

### 4.6 与就绪门 / 注意力的关系

- Gate 期间已在连续录制 → 无需为探针另起 session。  
- 切题不再 stop → 消除「空课点 AVI / 帧进错 session」类问题。  
- 实时注意力近窗逻辑保持；连续媒体使教师端分数不会因切题重置。

### 4.7 风险与对策

| 风险 | 对策 |
|------|------|
| 长录文件过大 / 中断丢全场 | agent 本地持续写 + 心跳；可选周期性 flush；失败保留本地路径提示 |
| 补传超时 | 仍后台补传；meta 标 `uploadState`；教师端可提示「本地已有完整片」 |
| 目录名 PII | 仅局域网/受控磁盘；文档注明隐私；可选配置 `RECORD_DIR_USE_STUDENT_ID=1` 降敏 |
| 姓名特殊字符 / 重名 | sanitize + meta 内保留 studentId；重名靠日期-N 区分 |
| DB course_type id 非「1=命名」 | lookup 以 DB 为准；禁止文档写死映射当运行时常量 |
| 旧客户端仍切 session | 协议加 `recordingMode: continuous`；旧逻辑兼容开关一个版本 |

### 4.8 建议实现顺序（新对话可直接当 TODO）

1. 定目录根路径与 `session_meta` / `timeline.csv` schema（先写 CONTRACT 小节）。  
2. 实现 `recording_timeline` + lookup 导出。  
3. 改 `PrepareTraining` / `PlayResource` / `Finalize` 媒体边界。  
4. 改 `child.js` + 确认 Runtime 长录不 rmtree。  
5. 分析层改为整场单 session。  
6. 自动化测试 + 一场手工验收清单（§2.6）。  
7. 回写 `UPGRADE_HANDOFF.md` 录制时机表。

---

## 5. 方案对比小结（给决策用）

| 维度 | 连续 + 拆分双写 (A) | **连续 + CSV (B)** |
|------|---------------------|---------------------|
| 漏录风险 | 低（主文件不断） | **低** |
| 实现复杂度 | 高 | **中** |
| 磁盘 | 约 2× | **约 1×** |
| 事后按题取片 | 现成 | 需 ffmpeg/脚本（可接受） |
| 注意力连续 | 需同样改分析边界 | **同改，一次到位** |
| 与用户偏好 | 次选 | **一致** |

**最终建议：按方案 B 实施**；目录命名采用 `姓名-年龄-日期-N`；timeline 用 DB id + 根目录 lookup；P0 不做实时拆文件。

---

## 6. 附录：关键现有文件（实现时打开）

```
app/sockets/handlers.py
app/sockets/events.py
app/services/media_service.py
app/routes/media_upload.py
app/session/session_model.py
app/behavior/timeline.py
static/js/child.js
robot_runtime/agent.py
teacher_frontend/App.tsx
teacher_frontend/components/ControlPage.tsx
database/models.py          # Student, CourseType, CourseItem
docs/UPGRADE_HANDOFF.md
docs/CONTRACT.md
```

---

## 7. 新对话启动提示（可复制）

请按 `docs/CONTINUOUS_RECORDING_TIMELINE_PLAN.md` 实现方案 B（整场连续录制 + timeline.csv + 目录名「姓名-年龄-日期-N」）。优先改 PlayResource 媒体边界与 child/agent 启停，再接通 timeline 与 lookup；不要做实时按题拆 AVI。验收以本文 §2.6 为准，并回写 UPGRADE_HANDOFF 录制时机表。
