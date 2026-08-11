# server_demo 项目升级计划

> 文档性质：跨对话接力用的总规划（非实现细节说明书）  
> 依据：`FEATURE_TRANSFER.md`、`professional_report_ver2.html`、`realtime_monitor_dashboard_prototype_light.html`、`temp_robot-config-prototype/`，以及对当前仓库的只读核实  
> 日期：2026-07-10  
> 约束：本阶段**只规划、不改业务代码**；后续对话按本计划分阶段落地

---

## 0. 一句话目标

在现有 Flask + Socket.IO + 教师端 React 架构上，补齐并打通：

1. **实时注意力观测与分析**
2. **实时表达性语言分析**（暂不做说话人分割，默认人声=儿童）
3. **行为观测 → 结构化报告**（教师端「查看报告」）
4. **Server 双视图**：配置控制 + 数据可视化监控台
5. **监控台实时同步**（Snapshot 轮询 + Socket 事件触发刷新）

远期（本计划标注为 P4，不阻塞当前）：配置中心升级为 `temp_robot-config-prototype` 风格。

---

## 1. 需求理解（本项目口径，非源项目照搬）

### 1.1 表达性语言（当前阶段简化假设）

| 项 | 本项目约定 |
|----|------------|
| 采集 | 机器人端定向麦（约 60°）朝向儿童，流式传到服务端 |
| 说话人 | **暂不做 diarization**；默认「有人声 = 儿童声」 |
| 分析时机 | 服务端收到音频后**同步实时**做表达性语言相关分析 |
| 非目标 | 临床诊断、精确说话人分离、百分位常模 |

> 与源项目差异：源项目偏「浏览器 STT 文本特征 + Web Audio 声学特征」；本项目应以**服务端已有音频流**为主路径，算法可借鉴源项目评分思路，采集路径不必照搬浏览器 MediaPipe/Web Audio。

### 1.2 注意力

- 训练过程中**实时同步**分析（本项目已有 Type B 窗口 + `attention_update` 推送雏形）。
- 报告侧需要按题序/时间聚合为注意力曲线与维度分。
- 可继续走**服务端吃视频帧**路径（不必强制迁浏览器 descriptor），但评分契约与监控/报告字段应对齐。

### 1.3 报告

- 指标与版式以 `professional_report_ver2.html` 为准：
  - 五维：注意力 / 表达性语言 / 接受性语言 / 配对 / 排序
  - 综合得分、KPI（正确率、响应时长、情绪）、注意力曲线、叙事建议
- 分数公式可先按可改的占位实现，**权重与公式集中配置**，便于后续调参。
- 报告边界文案：**仅供教育训练参考**，禁止临床诊断措辞。
- 呈现位置：**教师端**；课程结束弹窗新增「查看报告」。

### 1.4 Server 界面

- **短期必做**：`/server` 增加导航，切换「配置控制」与「数据可视化（监控台）」。
- 监控台视觉参考：`realtime_monitor_dashboard_prototype_light.html`。
- **长期目标**：配置控制升级为 `temp_robot-config-prototype` 风格配置中心（P4）。

### 1.5 监控实时同步

- 推荐沿用源项目已验证模式：**HTTP Snapshot 约 1s 轮询 + 任意相关 Socket 事件触发立即刷新**。
- WS/Socket 断线时轮询仍须兜底。

---

## 2. 现状核实（对照你的描述）

| 你的描述 | 核实 | 说明 |
|----------|------|------|
| child 启动就开始录音并回传 | **部分不属实** | 页面加载只 `getUserMedia` 初始化；真正上行发生在教师 `play_resource` 之后（`static/js/child.js`） |
| 定向麦 + 默认人声=儿童，流式到服务端再分析 | **目标合理；现状未达** | 已有 `audio_chunk` / agent HTTP 上行；`AudioPipeline` 仍硬编码 Mock，无表达性语言特征体系 |
| 注意力实时同步分析 | **部分属实** | 有 Type B（约 1s 调度）+ 教师端 `attention_update`；默认 Mock；未进报告/监控 Snapshot |
| 报告指标以 professional_report_ver2 为准，教师端弹窗加「查看报告」 | **需求明确；能力缺失** | 结束弹窗在 `ControlPage.tsx` 属实；无报告 API/页；弹窗目前只有取消/确定 |
| Server 偏配置，需加导航切到可视化 | **属实** | `templates/server.html` 是配置台；监控原型未接入 |
| 配置中心终极形态参考 temp_robot-config-prototype | **属实（远期）** | 原型在仓库内，未集成 |
| 监控台需要实时同步 | **属实（缺口）** | 无 MonitorSnapshot；现有 status 轮询不足以支撑仪表盘 |

### 2.1 本项目已有、可复用

- 三端骨架：`/child`、`/server`、`/robot` + 教师 React SPA
- Socket.IO 课程控制、音视频上行、录制落盘
- `app/core` 分析框架（Type A/B/C、Registry、Vision 侧 Mock/Real）
- 注意力 Real 实现与教师端推送雏形
- `/server` 配置热更新能力
- 静态原型：报告 / 监控台 / 配置中心 HTML

### 2.2 关键结构性缺口（迁移前必须正视）

1. **会话边界与源项目不兼容**：本项目常「一课点一 session」，切换课点未必 `stop_recording` / finalize；报告需要「整次训练一个逻辑会话 + 题目窗口」。
2. **无行为观测仓储 / 题目时间窗 / SessionBehaviorSummary**。
3. **无报告生成 API 与报告页**。
4. **无 MonitorSnapshot + 监控 UI**。
5. **AudioPipeline 未接 Registry**，表达性语言链路不存在。
6. **课程结束未规范化 finalize**（教师弹窗直接回学生页）。

### 2.3 后端是否需要简化？

**结论：需要「有针对性的对齐与瘦身」，不需要推倒重写 `app/core`。**

建议在升级过程中顺带做（穿插在各阶段，而非单独大重构）：

| 动作 | 原因 |
|------|------|
| 让 `AudioPipeline` 对齐 Vision（Registry + config） | 否则表达性语言无法切 Real/Mock |
| 统一「训练会话」与「课点/题目窗口」模型 | 否则报告与监控会碎裂 |
| 删除或停用明显死路径（旧 `analyzer_config`、未用 PipelineManager 等） | 降低后续改动的认知负担 |
| 收敛 session 结束：finalize → 聚合 → 可生成报告 | 教师端「查看报告」的前置条件 |

**不建议**本阶段大拆 Trigger/Action、重写整个 AnalysisService；先打通垂直切片。

---

## 3. 功能范围与优先级总表

优先级说明：

- **P0**：不做则后续全堵（地基）
- **P1**：核心业务闭环（分析 → 报告）
- **P2**：运营可见性（监控台）
- **P3**：体验与可运维增强
- **P4**：远期形态（可另开专项）

| 优先级 | 能力包 | 交付物（验收口径） |
|--------|--------|-------------------|
| **P0** | 训练会话与题目窗口模型 | 一次完整上课 = 一个 `trainingSessionId`；课点切换开/关观测窗；结束可 finalize |
| **P0** | 观测存储最小契约 | Attention / Language 观测可入库；可按 session/question 查询 |
| **P1** | 实时注意力（服务端路径加固） | 训练中持续产出分数/质量；可推教师端；可进聚合 |
| **P1** | 实时表达性语言（简化假设） | 音频流 → 人声活动/ASR 文本代理特征 → Language 观测；无 diarization |
| **P1** | 报告生成 + 教师端查看 | `generate/get report`；五维+曲线+叙事占位；结束弹窗「查看报告」 |
| **P2** | MonitorSnapshot API | 注意力、语音管线、题目进度、健康状态等聚合视图 |
| **P2** | Server 双 Tab：配置 / 监控 | 导航切换；监控台布局对齐浅色原型；1s poll + Socket 触发刷新 |
| **P3** | 监控预览帧、降级与 limitations | 预览 TTL；无摄像头/无语音时质量降级可见 |
| **P3** | 报告公式可配置、规则叙事完善 | 权重 YAML/配置项；叙事 rule/mock；打印友好 |
| **P4** | 配置中心视觉与信息架构升级 | 对齐 `temp_robot-config-prototype`（不阻塞 P0–P2） |
| **延后** | 说话人分割 / 临床级指标 / 外网 LLM 默认开启 | 明确非本阶段 |

---

## 4. 分阶段升级计划（建议实施顺序）

> 每一阶段应是可独立验收的垂直切片；跨对话时以阶段为单位接力。

### 阶段 A — 地基：会话边界与观测契约（P0）

**目标：** 让「整次训练」成为可聚合、可报告的单位。

**做什么（方向级）：**

- 引入或明确 `trainingSessionId`（或等价：学生一次上课贯穿多课点）
- 课点 / 题目切换时：关闭上一观测窗、打开新窗（对齐源项目「下一题才关窗」思路，按本项目课点模型适配）
- 课程结束：规范化 `finalize`（停录、关窗、会话摘要）
- 最小观测模型与存储（内存 + 文件/SQLite 皆可，优先可查询）

**刻意不做：** 完整报告 UI、监控台 UI。

**验收：** 跑完一套课，能查出按题窗口的注意力/语言观测列表与会话摘要骨架。

**建议对话提示词关键词：** `阶段A 会话边界 观测契约 finalize`

---

### 阶段 B — 实时分析加固：注意力 + 表达性语言（P1 前半）

**目标：** 流式数据进入观测，而不是只做课程目标文本比对。

**做什么：**

- 注意力：沿用服务端帧路径；统一分数/质量字段；保证实时写入观测存储
- 表达性语言：
  - AudioPipeline 接 Registry/config（顺带消除 Vision/Audio 不对称）
  - 默认假设人声=儿童
  - 产出可评分特征（如语音活动比、时长、ASR 词数/置信度代理等；公式可改）
- 教师端可继续收 `attention_update`；语言侧可增加轻量事件或仅入库供 Snapshot

**刻意不做：** 说话人分割；浏览器 MediaPipe 全量迁入（除非后续证明服务端路径不够）。

**验收：** 训练中观测持续增长；关麦/无人脸时质量降级可见。

**建议对话提示词关键词：** `阶段B 注意力 表达性语言 AudioPipeline`

---

### 阶段 C — 报告闭环 + 教师端入口（P1 后半）

**目标：** 课程结束可生成并查看结构化报告。

**做什么：**

- 报告评分服务（五维 + 综合分）；公式集中配置、先占位可改
- `POST/GET` 报告 API；持久化
- 报告页（可先静态模板数据绑定，样式对齐 `professional_report_ver2.html`）
- `ControlPage` 完成弹窗：新增「查看报告」；结束流程触发 finalize + generate
- 叙事：默认 rule/mock，禁止诊断措辞

**验收：** 最后一课点「下一个」→ 弹窗可见「查看报告」→ 打开报告含五维与注意力曲线（允许部分维度因缺数据降级并标注）。

**建议对话提示词关键词：** `阶段C 报告生成 教师端查看报告`

---

### 阶段 D — 监控台与实时同步（P2）

**目标：** `/server` 可运营盯盘。

**方向摘要：** Snapshot API、配置/监控双 Tab、1s poll + Socket 刷新；预览帧可放到 E。

> **详细需求（契约、UI 块、验收、拆分）：** [`docs/PHASE_DEF_REQUIREMENTS.md`](docs/PHASE_DEF_REQUIREMENTS.md) §1

**建议对话提示词关键词：** `阶段D Server监控台 Snapshot 实时同步`

---

### 阶段 E — 打磨与可配置（P3）

**目标：** 可演示、可调参、可降级说明。

**方向摘要：** 公式版本与 limitations、监控增强、单测与清理。

> **详细需求：** [`docs/PHASE_DEF_REQUIREMENTS.md`](docs/PHASE_DEF_REQUIREMENTS.md) §2

**建议对话提示词关键词：** `阶段E 打磨 公式配置 降级 limitations`

---

### 阶段 F — 配置中心形态升级（P4，**已完成**）

**目标：** 将现有配置台升级为 `temp_robot-config-prototype` 信息架构（模块导航、草稿/发布、健康概览等）。

**已落地：** F-IC（交互内容）+ F-Algo（概览 / 摄像头双栈 / 语音 / 报告权重）；入口 `/server/config` → overview。

> **详细需求：** [`docs/PHASE_DEF_REQUIREMENTS.md`](docs/PHASE_DEF_REQUIREMENTS.md) §3；[`PHASE_F_ALGO_CONFIG.md`](docs/PHASE_F_ALGO_CONFIG.md)

---

## 5. 依赖关系（实施时勿颠倒）

```text
A 会话/窗口/观测存储
    ↓
B 实时注意力 + 表达性语言写入观测
    ↓
C 聚合 → 报告 API/UI → 教师端入口
    ↓
D Snapshot → Server 监控 Tab + 实时刷新
    ↓
E 打磨 / 可配置 / 测试
    ↘
     F 配置中心视觉升级（可并行调研，但实现靠后）
```

**硬依赖提醒：**

- 没有 A 的统一会话与 finalize，C/D 会建立在碎裂 session 上。
- 没有 B 的真实观测写入，C 的五维与 D 的仪表盘只能是假数据。
- D 的实时同步可以先做「轮询假 Snapshot」，但正式验收必须接 B 的数据源。

---

## 6. 与源项目（FEATURE_TRANSFER）的刻意差异

| 点 | 源项目 | 本项目应采用 |
|----|--------|--------------|
| 注意力采集 | 浏览器几何特征 HTTP ingress | **优先服务端视频帧分析**（已有管线） |
| 表达性语言 | 浏览器 STT + Web Audio | **服务端音频流 + 默认儿童声**；评分思路可借鉴 |
| 实时通道 | 原生 WS DomainEvent | **沿用 Socket.IO**；Snapshot 轮询模式可复用 |
| 报告入口 | 儿童端 `#report` | **教师端弹窗「查看报告」**（按你的产品要求） |
| Server | 监控为主 | **配置 + 监控双视图**；配置中心远期升级 |
| 技术栈 | Express/TS/React | **Flask/Python + 现有前端形态**；算法移植而非整仓复制 |

---

## 7. 后端改动策略（给后续实现 Agent）

1. **先打通垂直切片，再清理框架**；避免一上来大重构 `app/core`。
2. **必做对齐：** `AudioPipeline` ↔ Registry/config；训练会话 ↔ 题目窗口。
3. **可顺手删：** 确认无引用的旧 config、未用 PipelineManager / ImitationAudioPipeline 等。
4. **分数与权重：** 单独模块 + 配置文件，禁止散落魔法数。
5. **安全与伦理：** 默认不外发儿童原始音视频；报告禁止诊断措辞；LLM 叙事默认关闭。

---

## 8. 后续对话如何接力（操作手册）

### 8.1 每个新对话建议粘贴的最小上下文

```text
请阅读本仓库 docs/UPGRADE_HANDOFF.md、PROJECT_UPGRADE_PLAN.md 与 FEATURE_TRANSFER.md。
当前要做：【阶段 X：标题】。
约束：
- 按计划优先级，不要提前做后续阶段的大功能
- 生产 AV 默认 agent（robot_runtime）；勿用浏览器 C2 覆盖服务端样本
- 表达性语言暂不做说话人分割，默认人声=儿童
- 报告呈现在教师端完成弹窗「查看报告」
- Server 需保留配置控制，并逐步加监控 Tab
- 需要简化后端时可以简化，但不要无必要推倒 app/core
完成后更新 PROJECT_UPGRADE_PLAN.md 底部「进度日志」，并必要时修订 docs/UPGRADE_HANDOFF.md。
```

### 8.2 推荐对话切分（防上下文爆炸）

| 对话 | 范围 |
|------|------|
| 对话 1 | 阶段 A |
| 对话 2 | 阶段 B |
| 对话 3 | 阶段 C |
| 对话 4 | 阶段 D |
| 对话 5 | 阶段 E（或拆成「测试+公式配置」与「UI 打磨」） |
| 对话 6+ | 阶段 F 或专项 bugfix |

若单阶段仍过大（尤其 C 或 D），可再拆：

- C1：报告 API + 评分；C2：报告页；C3：教师端按钮与 finalize 接线
- D1：Snapshot API；D2：Server 导航 + 监控静态壳；D3：实时刷新接线

### 8.3 每阶段结束时 Agent 应留下的交接物

1. 改动文件列表  
2. 新增 API / Socket 事件契约  
3. 如何手动验收  
4. 已知降级与未做项  
5. 更新下方进度日志  

---

## 9. 进度日志（跨对话维护）

| 日期 | 阶段 | 状态 | 备注 |
|------|------|------|------|
| 2026-07-10 | 规划 | 完成 | 本文件创建；代码未改 |
| 2026-07-11 | A | 完成 | training_session + 题目窗口 + finalize；课点切换规范收尾；child 录制切换 |
| 2026-07-11 | B | 完成 | 注意力观测入库 + Real analyze_window；AudioPipeline Registry；表达性语言观测；配对/排序 metrics |
| 2026-07-11 | C | 完成 | report scoring/API；教师端 ReportPage + 完成弹窗「查看报告」 |
| 2026-07-11 | C+ | 完成 | 报告数据链路修复：配对/排序 Session 复用、game_end 带 trainingSessionId、metrics 补丁窗、soft finalize 后 refresh；PARTIAL + 1.5s 轮询渐进加载（最多 45s）；按钮「查看报告（正在加载）」可点 |
| 2026-07-11 | C+fix | 完成 | 根因修复：① MockAttentionAnalyzer 不接受 mode 导致注意力分析器创建失败；② 语音 match 的 receptive 覆盖 pairing matching type；③ behavior store 按需从磁盘回填，避免 refresh 清空 |
| 2026-07-12 | C2 | 完成 | 浏览器端注意力 browser-attention-v2 + 情绪 browser-emotion-v1；camera_analysis Socket；EmotionObservation；报告 KPI 三色条；优先浏览器描述符、跳过 Mock 污染；注意力刻度统一 0–100 |
| 2026-07-12 | Bugfix | 完成 | 表扬音频双播/循环；speech target 残留；`finished`→`ended`；教师端注意力双源跳变；报告横竖屏 |
| 2026-07-12 | R1–R4 | 完成 | 生产 `agent` 跳过 C2；服务端 `record_attention/emotion`；timeline 按 mediaMode 选源；analyzers 默认 real + Mock 回退；文档见 `docs/CAMERA_ANALYSIS_QA.md` |
| 2026-07-12 | 交接 | — | **详细已落地说明**：[`docs/UPGRADE_HANDOFF.md`](docs/UPGRADE_HANDOFF.md)（新对话优先读此文件） |
| 2026-07-13 | D | 完成 | MonitorSnapshot API；`/server` 配置/监控双 Tab；1s poll + Socket 触发；方案 B 字段（`humanDirName`/`recordingMode`/`mediaSessionId`）；单测 `tests/test_monitor_snapshot.py`；预览留给 E2 |
| 2026-07-16 | E | 完成 | REPORT_SCORING 文档；narrative rule/mock；监控 probe 预览+事件+徽章；MISSING score=null；`test_attention_source_selection`；gitignore temp_asr |
| 2026-07-16 | F-IC | 完成 | 配置中心交互内容：壳、表情、绑定、动作、媒资、课程 |
| 2026-07-16 | F-Algo | 完成 | 概览/摄像头双栈/语音/报告权重；`camera-analysis`/`report-scoring` API；`tests/test_algo_config_files.py` |
| 2026-07-16 | YAML下线 | 完成 | 高级 YAML 页 Y1–Y5：运行时模式/运维/高级字段迁入配置中心；`/server` 仅监控；`?view=config`→overview |

---

## 10. 参考文件索引

| 文件 | 用途 |
|------|------|
| `docs/UPGRADE_HANDOFF.md` | **跨对话已落地改动/约束/验收**（接力首选） |
| `docs/PHASE_DEF_REQUIREMENTS.md` | 阶段 D/E/F 详细需求（D/E/F 已完成） |
| `FEATURE_TRANSFER.md` | 源项目能力与迁移边界 |
| `professional_report_ver2.html` | 报告 UI / 指标呈现参考 |
| `realtime_monitor_dashboard_prototype_light.html` | 监控台布局参考 |
| `temp_robot-config-prototype/` | 配置中心终极形态参考 |
| `app/services/analysis_service.py` | 分析编排插入点 |
| `app/core/pipelines/audio_pipeline.py` | 语音链路必改点 |
| `app/sockets/handlers.py` | 课点/会话生命周期 |
| `teacher_frontend/components/ControlPage.tsx` | 完成弹窗 +「查看报告」 |
| `templates/server.html` + `static/js/server.js` | Server 双视图改造点 |

---

## 11. 总裁决

- 你的产品方向清晰；对「录音从 child 打开就回传」的表述需修正为「**教师开课后流式回传**」，但不影响你设定的定向麦简化假设。
- 迁移不是照搬源项目前端采集，而是**在本仓库现有流媒体与分析框架上，补观测—聚合—报告—监控闭环**。
- 工作量确实无法单对话完成；**严格按 A→B→C→D→E（F 可选）** 接力，是完成全部升级的最稳路径。
)
