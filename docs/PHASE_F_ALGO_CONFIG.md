# 阶段 F · 算法与评分配置（F-Algo）— 设计说明

> **状态：** 已完成（F-Algo0→4）；旧 `/server?view=config` 高级 YAML 页已下线（能力迁入配置中心）  
> **范围：** 配置中心侧栏：概览 / 摄像头与注意力 / 语音与音频 / 报告与评分  
> **不做：** 五级覆盖、Secret、模型注册、告警中心、任意 System Prompt、多角色权限（见原型全量规格，本仓收缩）  
> **入口：** `/server/config` → `/server/config/overview`；交互内容 `/server/config/content`；监控 `/server`

---

## 0. 已确认决策（开工前勿再发散）

| # | 决策 | 结论 |
|---|------|------|
| 1 | 壳 | **复用** F-IC 的 `templates/server/config.html` + `config_center.css`；侧栏「规划中」改为可点模块，**不推倒**交互内容 |
| 2 | 与旧控制台 | 现有 `/server?view=config`（analyzers YAML 热更新）能力**迁入/封装**，不是重写一套配置栈 |
| 3 | 草稿/发布 | 影响训练的默认「**下一 Session 生效**」；映射现有 `save` / `apply` / `rollback` / `history` 语义，勿另造平行状态机 |
| 4 | 报告权重 | 表单编辑 `report_scoring.yaml`；**五维 weights 和≠100 不可发布**；`formulaVersion`/`schema_version` 约定见 `REPORT_SCORING.md` |
| 5 | 视觉 | 对齐 `temp_robot-config-prototype`；字段级「五级覆盖来源标签」**第一版不做** |
| 6 | 开工顺序 | **F-Algo0 → 1 → 2 → 3 → 4**（见 §6） |

---

## 1. 目标

让运维/教研在配置中心用**表单**改注意力/语音分析器关键项与报告权重，并走校验→发布；不会 YAML 也能调参。  
完整原始 YAML 仍保留为「高级」逃生口。

---

## 2. 与现有资产的关系

| 资产 | 角色 |
|------|------|
| F-IC 配置中心壳 | 侧栏已占位「配置概览 / 摄像头… / 语音… / 报告…」+「高级 / 原始 YAML」链到 `/server?view=config` |
| `/api/server/config*` + `AnalyzerConfigManager` | **仅管** `config/analyzers.yaml`（含 matchers/global）；草稿、历史、apply、reload pipelines |
| `config/camera_analysis.yaml` + `app/behavior/camera_config.py` | 当前**只读加载**，无写 API → F-Algo 需补 |
| `config/report_scoring.yaml` + `app/report/scoring.py` | 当前**只读加载**，无写 API → F-Algo 需补 |
| `docs/REPORT_SCORING.md` | 权重含义与运营约定（权威） |
| `CONFIG_CENTER_DESIGN_SPEC.md` | 产品愿景参考；**禁止**按原型一次做完五级覆盖等 |

---

## 3. 信息架构与路由

```text
顶栏：实时监控 | 配置中心
侧栏：
  · 交互内容              ← 已有 /server/config/content
  · 配置概览              ← F-Algo0  /server/config/overview
  · 摄像头与注意力        ← F-Algo1  /server/config/camera
  · 语音与音频            ← F-Algo2  /server/config/speech
  · 报告与评分            ← F-Algo3  /server/config/report
（旧「高级 / 原始 YAML」已下线；运维状态见 /server 监控）
```

**已落地：** 同一套壳模板，按 path 切换主区；交互内容子导航仅在 content 模块显示。  
`/server/config` **重定向到概览** `/server/config/overview`。

---

## 4. 各模块字段（MVP，可表单化）

### 4.1 配置概览

只读摘要 + 跳转：

- 全局分析器模式：`analyzers.global.mode`（Real/Mock）及各 analyzer/matcher 覆盖  
- `CHILD_MEDIA_MODE` / 运行时 mediaMode（只读展示即可）  
- `camera_analysis.enabled`、报告 `schema_version`  
- 最近一次 analyzers **发布/历史**摘要（复用 history API）  
- 链到各子模块与「高级 YAML」

### 4.2 摄像头与注意力

**来自 `camera_analysis.yaml`（需写 API）：**  
`enabled`、`fps`、`width`/`height`、`prefer_browser_for_report`、`prefer_browser_when_media_mode_browser`、`attention_incomplete_factor`、`emotion_min_samples`

**来自 `analyzers.yaml`（复用现有 API）：**  
`analyzers.attention.*`、`analyzers.face.*`、`analyzers.pose.*`、`matchers.pose.*`（表单只暴露常用：enabled、mode、threshold、window_size、confidence；路径类可只读或放高级）

文案注明：生产 agent 上行帧 vs browser 联调差异（勿暗示「本页能开机器人本地摄像头预览」）。

### 4.3 语音与音频

**来自 `analyzers.yaml`：**  
`analyzers.speech.*`、`matchers.speech.*`（enabled、mode、language、threshold、accumulation_duration 等）

不做：音频媒资库（已在 F-IC）、完整 ASR 模型上传 UI。

### 4.4 报告与评分

**来自 `report_scoring.yaml`（需写 API）：**

| 区块 | MVP |
|------|-----|
| `weights` 五维 | 数字输入 + 实时和校验（必须 =100 才可发布） |
| `interactive_course` | accuracy/response、objective/teacher、ideal/slow_sec |
| `dimension_weights` / `course_weights` | 可第二优先级；至少五维 + interactive 先做 |
| `narrative_provider` | `rule` \| `mock` 单选 |
| `schema_version` / `grade_thresholds` | 只读展示或高级；**勿轻易改 schema_version 文案而不懂后果** |

发布后：新报告用新权重；已落盘报告不回写（见 REPORT_SCORING.md）。

---

## 5. API 建议

### 5.1 已有（analyzers）— 复用

`GET/PUT /api/server/config`、`save`、`apply`、`apply-preview`、`rollback`、`history`、`reset-defaults`  
表单模块应对**结构化字段**读写，最终仍落到同一 `analyzers.yaml` 草稿/发布流；避免页面直接拼整文件字符串（高级页可继续）。

### 5.2 新建（camera / report）

建议对称、简单（历史可 v1 不做，或文件旁 `.bak` 一次）：

```text
GET  /api/server/config/camera-analysis
PUT  /api/server/config/camera-analysis          # 校验后写盘；说明「下一场/下次加载生效」
GET  /api/server/config/report-scoring
PUT  /api/server/config/report-scoring           # 校验 weights 和=100 等；写盘
```

或统一：

```text
GET/PUT /api/server/config/file/<name>
```

`name ∈ {camera_analysis, report_scoring}`，带 schema 校验。  
**不要**把这两份文件硬塞进 `AnalyzerConfigManager` 除非愿意大改；独立读写更清晰。

校验失败返回 400 + 中文 `error`，与现有 config API 风格一致。

---

## 6. 分阶段交付

| 子阶段 | 交付 | 验收要点 | 状态 |
|--------|------|----------|------|
| **F-Algo0** | 侧栏启用「配置概览」；路由/壳打通；摘要只读；高级 YAML 横幅引导 | 互跳不破坏 F-IC；概览数字来自真 API | ✅ |
| **F-Algo1** | 摄像头与注意力表单 + camera 写 API + analyzers 视觉相关字段 | 改 fps/prefer_* 落盘；改 attention 走现有 apply 语义 | ✅ |
| **F-Algo2** | 语音与音频表单（analyzers/matchers speech） | 改 threshold/mode 可预览/发布 | ✅ |
| **F-Algo3** | 报告与评分表单 + report 写 API；和≠100 禁发 | 改权重后新报告 `formulaVersion`/分数符合预期 | ✅ |
| **F-Algo4** | 打磨：未保存提示、发布确认文案、旧 `/server?view=config` 与配置中心关系说明、单测/验收、更新 HANDOFF | 文档与状态勾选 | ✅ |

**建议顺序：** 严格 0→1→2→3→4；若时间紧，Algo3（报告权重）可与 Algo1 对调优先级（教研更常调权重），但须在开场白写明。

---

## 7. 明确不做

- 原型五级覆盖 UI、Secret、模型路径注册向导、告警与服务、儿童安全引擎重做  
- 把 F-IC 课程/媒资再搬一遍  
- 训练中热改权重并自动重算**已生成报告**  
- LLM 叙事默认打开  
- React 重写配置中心（继续 Jinja + 静态 JS）

---

## 8. 验收清单（F-Algo 总体）

1. [x] 侧栏原「规划中」四项均可进入真实页（或概览+三编辑页），无假接通。  
2. [x] 可改注意力/语音常用项并经现有 analyzers 发布流生效（或明确「下一 Session」）。  
3. [x] 可改 `camera_analysis` / `report_scoring` 并落盘；权重和≠100 不可保存/发布。  
4. [x] 监控台 ↔ 配置中心 ↔ 交互内容互跳正常。  
5. [x] 高级 YAML 能力已迁入配置中心；旧页已下线（`?view=config` → overview）。  
6. [x] 更新 `UPGRADE_HANDOFF.md` 与本文状态。  

**落地要点：** `app/routes/server_config_files.py`；`static/js/config_algo.js`；单测 `tests/test_algo_config_files.py`。

---

## 9. 新对话开场白（复制用）

```text
请阅读：
1) docs/PHASE_F_ALGO_CONFIG.md（已确认决策见文首表）
2) docs/PHASE_DEF_REQUIREMENTS.md §3（F-Algo）
3) docs/REPORT_SCORING.md
4) 现有 /api/server/config*、app/core/config_manager.py、templates/server/config.html
5) config/analyzers.yaml、camera_analysis.yaml、report_scoring.yaml

F-IC 已完成，不要改交互内容业务除非壳/侧栏接线需要。
当前做阶段 F「算法与评分」：按 F-Algo0 → F-Algo1 开工（顺序见 PHASE_F_ALGO_CONFIG §6）。
复用 analyzers 的草稿/发布 API；为 camera_analysis / report_scoring 补写盘 API。
不要做五级覆盖、Secret、模型注册、告警。不要推倒 F-IC。
先列出本子阶段页面与 API 清单，我确认后再写代码。
```

---

## 10. 文档关系

| 文档 | 用途 |
|------|------|
| 本文 | F-Algo 切片规格与开场白 |
| `PHASE_DEF_REQUIREMENTS.md` §3 | F 总框 |
| `PHASE_F_INTERACTIVE_CONTENT_CONFIG.md` | F-IC（已完成，勿重做） |
| `REPORT_SCORING.md` | 报告公式权威说明 |
| `CONFIG_CENTER_DESIGN_SPEC.md` | 原型愿景；本仓已收缩 |
| `UPGRADE_HANDOFF.md` | 跨对话交接 |
