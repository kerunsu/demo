# Server 实时监控画面升级 × 报告审核推送门禁 — 需求与实现规划

> 状态：规划文档（**先不改代码**）  
> 范围 A：`/server` 实时监控 —「实时画面」双路预览、远端预览降延迟、环境摄像头、趋势图改位  
> 范围 B：训练结束后报告须经 `/server` 审核/推送，教师端才可查看；支持可视化改报告  
> 关联：`templates/server.html`、`static/js/server_monitor.js`、`static/css/server.css`、`app/monitor/*`、`app/routes/media_upload.py`、`robot_runtime/agent.py`、`teacher_frontend/components/ControlPage.tsx`、`ReportPage.tsx`、`app/report/*`

---

## 1. 需求理解（摘要）

### 1.1 Server 实时监控

| # | 诉求 | 目标 |
|---|------|------|
| A1 | 左侧整列改名「实时画面」 | 容纳上下两路画面 |
| A2 | 上方保留远端 agent 注意力预览 + 分数等 | 已有能力；**优先把端到端延迟压到 &lt;2s**（现状约 7–8s） |
| A3 | 下方新增「环境摄像头」 | 显示 **Flask 所在电脑** 本机摄像头；多摄像头可选 |
| A4 | 环境摄像头开关规则 | 无活跃训练：可开/关；有活跃训练：**强制开启不可关**，仍可切换摄像头 |
| A5 | 「近 60s 注意力趋势」横向压缩 | 挪到中间列下方（红框 2 区域），不再跨左+中拉宽 |

### 1.2 教师端报告显示逻辑

| # | 诉求 | 目标 |
|---|------|------|
| B1 | 训练结束弹窗「查看报告」暂不可点 | 后缀「正在处理中」 |
| B2 | `/server` 弹出审核窗 | 「查看并修改」「直接推送」 |
| B3 | 直接推送 | 推送后教师端按钮可点查看 |
| B4 | 查看并修改 | 进可编辑报告页：改数据/文字、保存、撤回、再推送教师端 |

---

## 2. 现状审查：描述是否符合项目？想法是否合理？

### 2.1 总判断

**产品方向合理，值得做；但对现状有几处需要修正，否则按字面实现会对不上布局与延迟根因。**

| 用户说法 | 与现状对照 | 判定 |
|----------|------------|------|
| 左侧红框整列叫「实时注意力」，含画面+趋势 | 左列 `.mon-camera` 标题是「实时注意力」，**只有**远端预览+分数 gauge；「近 60s 趋势」在 **第二行跨左+中两列** `.mon-analytics`，并不在左列内部 | **部分正确**：要扩展的是左列；趋势本来就不在左列里，是「跨栏拉伸」的视觉效果 |
| 中间下方空区刚好给趋势用 | 第二行左+中被 `.mon-analytics` 占满；中间下方并非独立空卡片，而是趋势图跨栏的一部分 | **意图正确**：把趋势从跨栏改为 **仅中列下方** |
| 远端画面延迟约 7–8s，可降帧率/清晰度换 &lt;2s | 预览不是连续视频流：agent HTTP 上行最后一帧 + **1s Snapshot 轮询** 嵌 base64；有效刷新约 ≤1fps，再叠加上行排队，延迟可到数秒 | **方向正确，但根因主要是传输/刷新架构，不只是「太清晰」** |
| 服务端本机环境摄像头 | Flask 进程 **无** 本机 `VideoCapture`；摄像头在儿童/机器人机的 `robot_runtime/agent` | **缺口真实存在** |
| 训练结束即可点「查看报告」 | ControlPage 仅 `finalizing` 时禁用；文案可显示「正在加载」但仍可点 | **正确** |
| `/server` 弹窗审核再推送 | **不存在** 报告审核/推送 UI 与 published 门禁 | **缺口真实** |
| 报告可可视化修改、保存、撤回 | ReportPage **只读**；仅有 generate/refresh；refresh 会按算法重算覆盖 | **缺口真实**；编辑需与「算法 refresh」分离 |

### 2.2 关键架构事实

#### A. 监控预览链路（远端）

```
robot_runtime/agent (儿童/机器人 Windows)
  OpenCV 采集 → JPEG → POST /api/media/{session}/frames
  → 内存 probe 缓存（仅最后一帧）
  → GET /api/monitor/snapshot（约 1s 轮询）内嵌 jpegBase64
  → server_monitor.js → <img>
```

- Socket.IO **不推帧**，只触发再拉 Snapshot。  
- Agent 本地另有 `/preview.mjpeg`（~15fps），**不供 `/server` 使用**。  
- 文档（`docs/PHASE_DEF_REQUIREMENTS.md`）明确：生产预览应消费 agent 上行抽稀副本，勿当连续高清视频。

#### B. 报告链路（教师）

```
训练结束弹窗 → finalize_training（只聚合 summary）
  → POST /api/report/{id}/generate|refresh → report.json
  → ReportPage 只读展示
档案页柱图也可直接进 ReportPage（无推送门禁）
```

- 状态仅有评分侧 `PARTIAL` / `READY`，**无** `DRAFT` / `PUBLISHED`。  
- `/server` 仅有报告**权重配置**，无报告内容审核。

### 2.3 对用户设想的细化建议

#### 关于延迟 &lt;2s（合理，但要改刷新路径）

仅「降低清晰度」帮助有限。建议分层：

| 层 | 建议 |
|----|------|
| 上行 | agent 为监控预览单独抽稀：如 2–4 fps、320×240、JPEG 40–55；与录制/分析分辨率解耦（若录制仍需更高质量） |
| 下发 | **预览专用通道**（优先）：`GET /api/monitor/preview.mjpeg` 或 Socket 推 preview 事件；避免整包 Snapshot 1s 才带一帧 |
| Snapshot | 继续 1s 拉分数/趋势等元数据；预览与 Snapshot 解耦 |
| 验收 | 端到端：帧采集时间戳 → 监控页显示时间 &lt;2s（P95）；允许偶尔 stale |

若不做独立预览通道，仅把 poll 调到 200–300ms 也能改善，但 Snapshot JSON 变大、CPU/带宽压力上升，不如 MJPEG/专用轻量端点干净。

#### 关于环境摄像头（合理）

- 采集进程跑在 **Flask 所在主机**（与 agent 机分离）。  
- 用 OpenCV 枚举设备；Windows 下索引 0/1/…；UI 下拉选择。  
- 建议独立 MJPEG 或短 TTL 的 JPEG 轮询（0.5–2 fps 即可，监控用途）。  
- **设备占用冲突**：若本机摄像头同时被其他软件占用，需明确错误态文案。  
- 「有活跃训练强制开启」：以 `MonitorSnapshot` / session 是否有 `active` training 为准。

#### 关于趋势图改位（合理，主要是前端布局）

目标布局示意：

```
┌──────────────────┬─────────────────────┬─────────────────┐
│ 实时画面          │ 双屏状态摘要         │ 语音与表达性语言  │
│ ├ 远端注意力预览  │                     │                 │
│ │ + 分数参数      │                     │                 │
│ ├ 环境摄像头      │ 近 60s 注意力趋势     │ 健康与限制       │
│ │ + 开关/选设备   │ （横向压缩到中列宽）  │                 │
└──────────────────┴─────────────────────┴─────────────────┘
```

情绪占比条：建议仍挂在趋势面板底部，或保留底栏；实现时二选一并写验收口径。

#### 关于报告门禁 + 可编辑（合理，需定边界）

1. **门禁范围**（必须产品确认）：  
   - 仅「训练刚结束的 ControlPage 弹窗」？  
   - 还是 **档案页点击历史报告** 也同样要求已推送？  
   - **建议默认**：新生成报告默认未推送，教师端任意入口（弹窗 / 档案）均需 `published`；未推送时档案柱图可灰显或提示「尚未推送」。  
2. **「直接推送」**：推当前算法生成的最新 `report.json`（可先 ensure generate）。  
3. **「查看并修改」**：进入 **Server 侧编辑页**（建议挂在 `/server` 体系，勿与教师只读 ReportPage 混用同一可写态）。  
4. **撤回**：至少「撤销未保存编辑」；可选「恢复到上次推送版 / 算法初版」。  
5. **与 refresh 冲突**：教师评分晚到触发的 `refresh` **不得静默覆盖人工修改**；已编辑报告应标记 `manualOverride`，refresh 只更新未覆盖字段或需二次确认。

### 2.4 合理性总表

| 维度 | 评价 |
|------|------|
| 产品价值 | 高：监控运维需要本机环境画面；报告需人工把关再给教师 |
| 技术可行性 | 中高：布局/趋势易；低延迟预览与本机摄像头中等；可编辑报告+门禁中等偏复杂 |
| 主要风险 | 摄像头独占、预览带宽、人工改分与算法 refresh 冲突、门禁与档案页历史报告一致性 |
| 建议决策 | **双路预览解耦传输**；报告增加 `publicationStatus`；Server 编辑页与教师只读页分离 |

---

## 3. 详细需求说明

### 3.1 用户故事

1. 作为运维/督导，在 `/server` 左侧「实时画面」同时看到远端儿童注意力预览与本机环境摄像头，延迟体感在 2 秒内。  
2. 作为运维，无训练时可关掉环境摄像头省资源；训练进行中环境摄像头自动保持开启，仍可换摄像头。  
3. 作为运维，在中列下方紧凑查看近 60s 注意力趋势，不再被横向拉得过扁。  
4. 作为运维，训练结束后在 `/server` 审核报告：可直接推送，或修改后再推送。  
5. 作为教师，结束训练后看到「查看报告（正在处理中）」不可点；收到推送后可点并打开只读报告。

### 3.2 功能需求 — 监控画面（验收口径）

#### M1. 区域改名与结构

1. 左列面板总标题改为 **「实时画面」**。  
2. 上子区标题 **「远端注意力」**（或保留「实时注意力」作子标题）：现有预览 + 注意力 0–100、本题关注比例、样本数、Provider、状态。  
3. 下子区标题 **「环境摄像头」**：本机画面 + 开关 + 摄像头下拉。

#### M2. 远端预览延迟

1. 目标：P95 端到端显示延迟 **&lt; 2s**（有活跃 agent 上行时）。  
2. 允许降低分辨率/帧率/JPEG 质量；**不要求**电影级流畅。  
3. Stale 提示保留；超时文案勿把占位当真实画面（现有原则延续）。  
4. 提供可配置项（环境变量或 config）：预览 max fps、宽高、jpeg quality、TTL。

#### M3. 环境摄像头

1. API 可列出本机摄像头设备（id + 名称/索引）。  
2. 用户可选择设备；选择持久化到 localStorage 或服务端偏好（建议 localStorage + 服务端当前选择）。  
3. **无活跃训练**：可关闭采集（停止占用摄像头）。  
4. **有活跃训练**：UI 开关强制为开且 disabled；若关闭态下进入训练，自动开启。  
5. 切换摄像头在强制开启期间仍允许。  
6. 无设备 / 占用失败：明确错误态，不影响远端预览与其它监控模块。

#### M4. 近 60s 趋势布局

1. 趋势面板仅占 **中列下方**（约等于现红框 2 宽度）。  
2. 图表高度保持可读，避免过度压扁；横向不再跨左列。  
3. 左列垂直扩展后，趋势不再与左列抢第二行跨栏。

### 3.3 功能需求 — 报告门禁与编辑（验收口径）

#### R1. 生成后默认未推送

1. 报告 generate 成功后：`publicationStatus = "pending_review"`（命名可定）。  
2. 教师端「查看报告」：`disabled`，文案 **「查看报告（正在处理中）」**（或「等待服务端推送」——建议与产品文案统一）。  
3. 未推送时，教师端即使持有 `trainingSessionId` 调 GET 报告，也应返回 **403/409** 或 payload 带 `published:false` 且前端拒绝展示正文（防绕过）。

#### R2. `/server` 审核弹窗

1. 触发时机：检测到训练 finalize 且报告已生成（或 PARTIAL 达到可审阈值）时弹出；也可从监控事件手动打开。  
2. 展示：学生名、会话短 ID、综合分、状态、生成时间。  
3. 按钮：  
   - **直接推送**：将当前报告标为已推送 → 通知教师端。  
   - **查看并修改**：进入编辑页（不自动推送）。  
4. 弹窗可关闭但不等于推送；关闭后提供入口再次打开（事件列表或顶栏徽章）。

#### R3. 编辑页能力

1. 可视化编辑至少覆盖：  
   - `overall` / `grade`（若 grade 由 overall 推导可只改 overall）  
   - `dimensions.*.score`（及可选 available）  
   - `courseScores.*`  
   - `kpi` 关键字段（可分期）  
   - `narrative.analysis`、`recommendations[]`（增删改 title/body）  
2. **保存**：写入报告文件（建议另存 `report.edited.json` 或在原 JSON 增加 `edits`/`manualOverride` 元数据，避免无法回滚）。  
3. **撤回**：  
   - 未保存：恢复到进入编辑页时的快照  
   - 已保存未推送：可恢复到「算法初版」或「上一保存点」（首期至少支持恢复算法初版）  
4. **推送教师端**：以**当前已保存内容**为准发布；未保存变更应提示先保存或提供「保存并推送」。  
5. 编辑页只在 Server 控制台可达；教师 ReportPage 保持只读。

#### R4. 教师端解锁

1. 推送成功后：ControlPage 弹窗按钮启用，文案恢复「查看报告」。  
2. 通知方式建议：Socket 事件 `report_published` + 教师端短轮询兜底。  
3. 打开后展示**已推送版本**（若推送后服务端又编辑未再推送，教师仍看上次推送快照——建议推送时固化 `publishedSnapshot`）。

#### R5. 与档案页一致性

1. 档案「最新干预建议 / 柱图进报告」：仅对 **已推送** 报告开放正文；未推送显示「报告审核中」。  
2. DB `sync_student_archive_from_report`：可在推送时再同步对外可见摘要，或同步时带 `published` 标志（实现阶段定一种）。

### 3.4 非目标（本阶段不做）

- 不把 `/server` 监控改成 React。  
- 不要求环境摄像头参与注意力评分。  
- 不做 WebRTC 双向通话。  
- 不做完整「版本管理系统」；撤回以快照级即可。  
- 不在教师端开放编辑。

### 3.5 待产品确认的决策点

| # | 问题 | 建议默认 |
|---|------|----------|
| 1 | 档案历史报告是否一律要 published？ | **是** |
| 2 | PARTIAL 报告能否「直接推送」？ | 允许，但弹窗警告数据不完整 |
| 3 | 推送后算法 refresh 能否覆盖？ | **不能**自动覆盖已推送或已人工编辑字段 |
| 4 | 环境摄像头默认开还是关（无训练时）？ | **关**（省资源）；有训练强制开 |
| 5 | 远端预览优先 MJPEG 还是加快 Snapshot？ | **专用 preview 通道（MJPEG 或 WS）** |
| 6 | 编辑页 URL | `/server/report-review/{trainingSessionId}` |

---

## 4. 前端设计修改说明

### 4.1 `/server` 监控页布局

**技术栈保持**：Jinja `server.html` + `server.css` + `server_monitor.js`。

#### 4.1.1 Grid 调整（建议）

```
grid-template-columns: 1.05fr 1.4fr 1.05fr;
grid-template-rows: auto 1fr;  /* 或 auto auto，由内容撑开 */

.mon-live-video   → col1, row1 / row-span 2   /* 原 mon-camera 扩展 */
.mon-screens      → col2, row1
.mon-voice        → col3, row1
.mon-analytics    → col2, row2               /* 不再 span 两列 */
.mon-health       → col3, row2
```

左列内部结构：

```
.mon-live-video
  header: 实时画面
  .mon-remote-block
    subhead: 远端注意力
    preview img + badges
    metrics grid（分数等）
  .mon-ambient-block
    subhead: 环境摄像头
    controls: [开/关] [摄像头 ▾]
    ambient preview img / video
```

#### 4.1.2 视觉规格

- 远端与环境预览区各保留 16:9 或 4:3 容器，`object-fit: cover`，避免「被拉伸」感。  
- 环境摄像头关闭时：占位「已关闭」+ 一键开启。  
- 强制开启时：开关灰显，tooltip「训练进行中，环境摄像头需保持开启」。  
- 趋势 SVG：适应中列宽度；Y 轴刻度可略减；空态文案不变。

#### 4.1.3 报告审核弹窗（新增）

- 居中 modal，与现有监控浅色体系一致。  
- 标题：「训练报告待审核」。  
- 主按钮：「直接推送」（实心）；次按钮：「查看并修改」（描边）。  
- 第三操作：「稍后处理」（关闭）。  
- 顶栏可增加徽章：未推送报告数量。

#### 4.1.4 报告编辑页（新增）

- 布局：左侧可编辑表单/内联字段，右侧或下方实时预览（可复用 ReportPage 只读组件思路，但在 server 静态页实现，或抽共享渲染）。  
- 工具栏：`保存` | `撤回` | `推送教师端` | `返回监控`。  
- 字段分组：综合分 / 能力维度 / 课型分 / 叙事与建议。  
- 修改过的字段视觉标记（左侧色条或「已改」角标）。

### 4.2 教师端 ControlPage

- 完成弹窗按钮：  
  - `publicationStatus !== 'published'` → `disabled`，文案 `查看报告（正在处理中）`。  
  - published → 可点，走现有 `handleViewReport`（仍可 finalize + 拉取已推送快照）。  
- 监听 `report_published`：立即解锁；保留 2–3s 轮询兜底。  
- 若用户点「确定返回」离开弹窗：回档案后仍应不能看未推送报告。

### 4.3 教师端 ReportPage

- 保持只读。  
- 加载时若未推送：展示「报告尚未由服务端推送」空态，不渲染分数正文。

### 4.4 交互状态表

| 场景 | 环境摄像头开关 | 教师查看报告 | /server 弹窗 |
|------|----------------|--------------|--------------|
| 无训练 | 可关 | — | — |
| 训练中 | 强制开 | — | — |
| 刚结束、报告生成中 | 可关 | 处理中 | 可显示「生成中」 |
| 报告可审未推送 | 可关 | 处理中 | 弹出审核 |
| 已推送 | 可关 | 可查看 | 可关弹窗；可再进编辑但需「重新推送」才更新教师所见 |

---

## 5. 技术实现规划

### 5.1 模块拆分

| 模块 | 内容 |
|------|------|
| P-Monitor-Layout | CSS/HTML 左列双画面 + 趋势改中列下 |
| P-Remote-Latency | 远端预览专用通道 + agent 抽稀参数 |
| P-Ambient-Cam | 本机摄像头枚举/采集/开关策略 |
| P-Report-Gate | publication 状态 + 教师门禁 + Socket 通知 |
| P-Report-Edit | Server 编辑 UI + 保存/撤回/推送 API |

建议实施顺序：**Layout → Ambient → Remote latency（可并行）→ Report Gate → Report Edit**。  
Gate 可先做「直接推送」无编辑；Edit 紧随其后，避免教师长期卡在处理中却无法人工改错。

### 5.2 远端预览降延迟

#### 方案（推荐）

1. **Agent 侧**：增加 `preview` 上行或复用 frames 但服务端抽稀入库；参数：`MONITOR_UPLINK_MAX_FPS=3`、`WIDTH=320`、`JPEG=50`（名称可定）。  
2. **服务端**：`GET /api/monitor/remote-preview.mjpeg?trainingSessionId=` 或按 mediaSession 推送 multipart JPEG。  
3. **前端**：`<img src="/api/monitor/remote-preview.mjpeg?...">` 或独立 `EventSource`/WS；Snapshot 不再内嵌大图（或降为可选）。  
4. **兼容**：`MONITOR_PREVIEW_ENABLED` 保留；无活跃会话时占位。

#### 备选（更快落地、效果较差）

- Snapshot poll 改为 300ms，且 preview 单独 compact endpoint `GET /api/monitor/preview-frame` 只返回 jpeg。

### 5.3 环境摄像头

#### 后端

- 新模块：`app/monitor/ambient_camera.py`  
  - `list_devices()`  
  - `start(device_id)` / `stop()` / `get_jpeg()`  
  - 单例采集线程，避免多客户端重复开摄像头  
- API：  
  - `GET /api/monitor/ambient/devices`  
  - `POST /api/monitor/ambient/control` `{ enabled, deviceId }`  
  - `GET /api/monitor/ambient/preview.mjpeg`（或 jpeg 轮询）  
- Snapshot 增加：`ambient: { enabled, deviceId, forcedByTraining, error }`（可不内嵌帧）

#### 强制开启逻辑

```
if has_active_training and not ambient.enabled:
    ambient.start(last_selected_or_default)
    ambient.forced = True
```

前端根据 `forcedByTraining` 禁用关闭按钮。

#### 依赖

- Windows 服务器需安装可用的 OpenCV 后端与摄像头驱动。  
- 若部署在无摄像头的云主机：功能降级为「无可用设备」。

### 5.4 趋势图改位

- 改 `server.html` DOM 顺序/包裹。  
- 改 `server.css`：`.mon-analytics { grid-column: 2; grid-row: 2; }`；左列 `.mon-live-video { grid-row: 1 / span 2; }`。  
- `server_monitor.js` 图表 resize：在容器宽度变化时重绘 SVG。

### 5.5 报告 publication 模型

#### 状态机

```
(none) → generating → pending_review → published
                 ↘ failed
published → pending_review（若重新编辑后未推送，教师仍看旧 publishedSnapshot）
```

#### 存储建议

在 `report.json` 同级增加：

| 文件/字段 | 用途 |
|-----------|------|
| `report.json` | 算法当前版（可继续 refresh） |
| `report.manual.json` | 人工编辑版（可选） |
| `report.published.json` | **推送快照**（教师只读源） |
| 字段 `publicationStatus`, `publishedAt`, `publishedBy` | 索引 |

或单文件内：

```json
{
  "publicationStatus": "pending_review",
  "algorithm": { ... },
  "manual": { ... },
  "published": { ... }
}
```

首期推荐 **published 独立快照文件**，教师 GET 只读 published；Server 编辑读写 manual/algorithm。

#### API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/report/<id>` | 教师：仅 published；Server：可带 `?view=manual|algorithm` |
| POST | `/api/report/<id>/generate` | 不变；结果进入 pending_review |
| PUT | `/api/report/<id>/manual` | 保存人工编辑 |
| POST | `/api/report/<id>/revert` | 撤回至算法版或上次保存 |
| POST | `/api/report/<id>/publish` | 固化 published 快照并广播 |
| GET | `/api/report/<id>/review-status` | 供教师轮询：published? |

#### Socket

- `report_ready_for_review` → `/server` 弹窗  
- `report_published` → 教师端解锁  

### 5.6 教师端改动点

| 文件 | 改动 |
|------|------|
| `ControlPage.tsx` | 按钮门禁 + 监听 published |
| `ReportPage.tsx` | 未推送空态；拉取 published |
| `StudentInfoPage.tsx` | 未推送不可进正文 |
| `App.tsx` | 可能无需大改 |

### 5.7 `/server` 改动点

| 文件 | 改动 |
|------|------|
| `templates/server.html` | 双画面结构、趋势改位、审核 modal |
| `static/css/server.css` | grid 与子区样式 |
| `static/js/server_monitor.js` | ambient 控制、preview 源、弹窗、resize |
| 新：`templates/server_report_edit.html` + JS | 编辑页 |
| `app/routes/monitor.py` | ambient + preview 路由 |
| `app/monitor/*` | ambient 采集、snapshot 字段 |
| `app/routes/report.py` + `app/report/*` | manual/publish |
| `robot_runtime/agent.py` | 预览抽稀参数（远端延迟） |

### 5.8 测试计划（实现阶段）

**监控**

1. 无摄像头机器：环境区错误态，远端仍可用。  
2. 多摄像头切换成功。  
3. 无训练时关闭后进程释放设备（可被其它应用打开）。  
4. 开始训练后自动开启且无法关闭。  
5. 延迟：打日志比较 agent 帧 timestamp 与浏览器显示时间，P95 &lt;2s。  
6. 趋势仅中列宽，左列可上下滚动/扩展。

**报告**

1. 结束后教师按钮禁用。  
2. `/server` 收到审核弹窗。  
3. 直接推送 → 教师可看且内容正确。  
4. 查看并修改 → 改叙事保存 → 推送 → 教师看到修改后内容。  
5. 撤回恢复算法版。  
6. 未推送时直接打开 ReportPage URL 无法看正文。  
7. 档案柱图对未推送会话有提示。

### 5.9 风险与缓解

| 风险 | 缓解 |
|------|------|
| OpenCV 占摄像头导致 agent 同机冲突 | 文档说明：环境摄像头是 **Server 主机**；儿童摄像头在儿童机 |
| MJPEG 增加带宽 | 低分辨率 + 限流；仅监控页打开时拉流 |
| 人工改分被 refresh 覆盖 | `manualOverride` / 停用自动 refresh 覆盖 |
| 教师绕过门禁 | API 层强制 published 校验 |
| 弹窗打断运维 | 可稍后处理 + 徽章入口 |

---

## 6. 与现有文档对齐

- `docs/PHASE_DEF_REQUIREMENTS.md`：监控预览定位为抽稀快照；本规划在保持该原则下引入专用低延迟通道，不改为评分视频源。  
- `FEATURE_TRANSFER.md`：提到未实现的 preview API / 域事件 publish；本规划中的 `report_published` 属于有意新增。  
- `docs/STUDENT_INFO_REPORT_INTEGRATION_PLAN.md`：档案页读报告；落地门禁后需同步「仅 published 可见」。

---

## 7. 实施阶段建议

| 阶段 | 内容 | 验收 |
|------|------|------|
| **S0** | 布局：左列「实时画面」双区结构占位 + 趋势改中列下 | 视觉与红框意图一致（环境区可先占位） |
| **S1** | 环境摄像头枚举/预览/开关/训练强制开 | 本机可见画面，规则正确 |
| **S2** | 远端预览降延迟专用通道 + agent 抽稀 | P95 &lt;2s（有网络前提） |
| **S3** | 报告 `pending_review`/`published` + 教师按钮门禁 + `/server` 弹窗「直接推送」 | 推送前不可看，推送后可看 |
| **S4** | 「查看并修改」编辑页：保存/撤回/推送 | 教师看到人工修订版 |

---

## 8. 一页纸结论

- **现状**：监控左列是远端注意力预览；趋势跨左+中显得被拉宽；预览靠 1s Snapshot，延迟易到数秒；无本机环境摄像头；教师结束训练即可看报告，报告只读且无审核推送。  
- **需求**：整体合理。关键修正：趋势本就不在左列内部；降延迟要改传输/刷新路径，不能只靠降清晰度。  
- **做法**：左列改为「实时画面」= 远端 + 环境摄像头；趋势收进中列下；报告增加审核推送与 Server 编辑，教师只读已推送快照。  
- **下一步**：评审 §3.5 决策点后按 S0→S4 开工；**当前阶段不改代码**。
