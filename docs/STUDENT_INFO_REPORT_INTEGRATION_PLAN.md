# 儿童信息页 × 训练报告数据打通 — 需求与实现规划

> 状态：规划文档（**先不改代码**）  
> 范围：教师端「儿童信息 / 学生档案」页展示优化 + 训练结束后报告/能力/训练记录的持久化与回查  
> 关联页面：`teacher_frontend/components/StudentInfoPage.tsx`、`ReportPage.tsx`  
> 关联后端：`app/report/*`、`app/behavior/*`、`database/models.py`、`app.py` 学生 API

---

## 1. 需求理解（摘要）

| # | 用户诉求 | 一句话目标 |
|---|----------|------------|
| 1 | 能力分析、训练记录改为真实数据 | 训练结束落库，档案页读真实历史 |
| 1b | 「模仿」能力暂无独立算法 | 统一占位 **60 分**，后续再替换 |
| 2 | 课程训练结束后的报告数据应被保存 | 与档案页所需字段同源，可按儿童回查 |
| 3 | 训练记录柱状图可点进对应评估报告 | 可感知可点击 + 跳转 `ReportPage` |
| 4 | 「初步筛查」支持与「最新干预建议」切换 | 有训练则默认干预建议，并提供跳最新报告 |
| 5 | 能力分析 / 训练记录改同一行左右布局 | 更紧凑，降低纵向占位 |

---

## 2. 现状审查：描述是否符合项目？想法是否合理？

### 2.1 结论（先给判断）

**用户对问题本质的判断基本正确，方案方向合理，值得做。**  
但有几处需要修正或细化，否则按字面「点某一段柱子」实现时会对不上数据模型。

| 用户说法 | 与现状对照 | 判定 |
|----------|------------|------|
| 档案页能力分析 / 训练记录还不是「真实训练结果」 | 前端已接真实 REST；但 DB 的 `training_session` / `ability_item` / `training_detail` **仅样例脚本写入**，live 训练不写 | **正确** |
| 项目已能产出报告与分析结果，缺保存方式 | 报告已落盘为 JSON（`static/recordings/behavior/{uuid}/report.json`），**不是「完全没保存」**；缺的是 **与学生档案 DB 的索引/同步**，以及按儿童列表查询 | **部分正确，需修正表述** |
| 「模仿」能力暂时没有 | 报告五维无独立「模仿」；有课型分 `courseScores.mimic`（教师评分）。DB 六维字典里已有「模仿」，但 live 从不写入 | **正确**；占位 60 合理作过渡 |
| 报告数据与档案要展示的数据同源 | 报告含 `dimensions`、课型窗口、`narrative.recommendations`；档案页读另一套 DB 表，**两套 ID 未关联** | **正确** |
| 柱状图点击跳转对应报告 | 当前无点击；且前端按 **日期聚合** 后丢弃 `session.id`，无法 1:1 对报告 | **方向合理，交互模型需调整**（见 2.3） |
| 筛查区切换「最新干预建议」+ 跳最新报告 | 干预建议只在 `ReportPage` 的 `narrative`；档案页无 UI/API | **合理且缺口清晰** |
| 能力分析与训练记录左右并排 | 当前 `space-y-6` 上下堆叠，两块图高均为 400px，纵向过长 | **合理** |

### 2.2 关键架构事实（实现前必须对齐）

```
┌─────────────────────────────────────────────────────────────────┐
│ Live 训练链路（已有）                                              │
│ ControlPage → finalize_training → behavior JSON 落盘              │
│ → ReportService.generate → report.json（UUID trainingSessionId） │
└─────────────────────────────────────────────────────────────────┘
                              ✗ 未连接
┌─────────────────────────────────────────────────────────────────┐
│ 学生档案链路（已有 UI + API，数据源割裂）                           │
│ StudentInfoPage → GET /api/students/{id}                        │
│                 → GET .../abilities                             │
│                 → GET .../training-sessions                     │
│ 读 SQLite：training_session(id=整数) + ability_item + training_detail │
│ 写入路径：几乎只有 database/generate_sample_data.py               │
└─────────────────────────────────────────────────────────────────┘
```

- **报告不是「没保存」**：文件持久化 + behavior store 可加载；PRD 中「结束训练写入数据库训练记录」仍为未完成项。
- **两套会话 ID**：behavior / 报告用 **UUID 字符串**；DB `training_session.id` 为 **自增整数**。档案页跳转报告必须以 UUID 为准（现有 `App.handleViewReport(trainingSessionId)` / `ReportPage` 已按此设计）。
- **能力维度不一致**：
  - DB / 雷达图：注意力、模仿、配对、排序、表达性语言、接收性语言（6）
  - 报告：`attention` / `expressiveLanguage` / `receptiveLanguage` / `matching` / `ordering`（5）+ 课型 `mimic`
- **同一天多次训练**：当前柱图按日合并，丢失单次会话身份；与「点哪次训练进哪份报告」冲突。

### 2.3 对用户交互设想的细化建议（合理，但建议改一点）

1. **柱状图粒度：建议改为「一次训练一根柱」，不要继续按日合并。**  
   - X 轴标签：`MM/DD` 或 `MM/DD HH:mm`（同日多次时必须带时间）。  
   - 点击整根柱（或 tooltip 内「查看报告」）→ 对应 `behavior_session_id`。  
   - 若坚持「按日堆叠」，同日多会话时必须二次选择，体验更差，不推荐作为默认。

2. **「点柱状图某一段（某一课型）」跳转报告**  
   - 课型色块是堆叠系列，语义上更像「当天/该次的课型次数」，不是独立报告。  
   - **推荐：整柱可点 = 进该次训练报告**；hover 提示「点击查看评估报告」。  
   - 若产品坚持点色块，也应落到**同一次会话的报告**（各色块共用同一 session），而不是按课型拆报告。

3. **「有训练就默认显示干预建议」**  
   - 以「该儿童至少有一次 `report.status` 可用的报告（READY 优先，其次 PARTIAL）」为准。  
   - 无训练 / 仅有未完成会话：仍显示「初步筛查」，干预 Tab 可禁用或空态。

4. **「模仿」统一 60**  
   - 短期可接受，需在 UI 或数据层标记为占位，避免教师误读为算法分。  
   - 中期可用 `courseScores.mimic`（映射到 0–100）替换占位。

### 2.4 总体合理性

| 维度 | 评价 |
|------|------|
| 产品价值 | 高：档案页当前「看起来有能力/训练图」，实则与真实训练脱节 |
| 技术可行性 | 高：报告字段已够用；缺同步钩子、DB 桥接字段、列表 API、前端导航 |
| 风险点 | ID 桥接、按日聚合、维度映射、历史样例数据与真实数据混杂 |
| 建议决策 | **采用「报告 JSON 继续落盘 + SQLite 建索引/摘要」**，而不是把整份报告只塞进 DB 或只依赖扫盘 |

---

## 3. 详细需求说明

### 3.1 用户故事

1. 作为教师，完成一次儿童训练并生成报告后，回到该儿童档案页，应能看到本次训练出现在「训练记录」中，且「能力分析」反映本次（或最新）能力分。  
2. 作为教师，在训练记录图上点击某次训练，应直接打开该次评估报告。  
3. 作为教师，在档案右上「筛查 / 干预」区域，默认可阅读最新干预建议，并可一键打开最新报告；也可切回查看建档时的初步筛查文本。  
4. 作为教师，在常见笔记本分辨率下，无需大幅滚动即可同时看到能力分析与训练记录概览。

### 3.2 功能需求（验收口径）

#### R1. 训练结束 / 报告生成后持久化档案所需数据

当某次训练报告生成成功（`ReportService.generate` 或 `refresh` 写出 `report.json`）后，系统应保证：

1. SQLite 中存在对应该次训练的 `training_session` 行（或更新已有行），并保存 **`behavior_session_id`（UUID）**。  
2. 写入 / 更新 `training_detail`：各课型次数（从报告 `windows[]` 的 `course_type` 统计，或从 session_summary 等价字段统计）。  
3. 写入 / 更新 `ability_item`：六维分数映射见 §5.3；其中「模仿」**暂固定 60**。  
4. 可查询的干预建议摘要可用：至少保存 `narrative.recommendations`（及建议同步保存 `narrative.analysis`），来源为该次报告。  
5. 幂等：同一 UUID 重复 generate/refresh **不产生重复训练行**。

#### R2. 儿童信息页展示真实数据

1. **能力分析**  
   - 当前能力：最新一次已同步的训练能力项（无数据则空态，勿用全 0 伪装成已评估，除非产品明确要求）。  
   - 发展趋势：按训练时间序列展示历史能力。  
2. **训练记录**  
   - 展示该儿童真实训练次数/课型分布；**每一根柱对应一次训练会话**。  
3. 数据范围：默认最近 N 次（建议 15–30，与现 API `per_page` 对齐）。

#### R3. 训练记录 → 评估报告跳转

1. 柱图区域可点击；指针为 `pointer`；标题旁或图下方有辅助文案，例如：「点击柱状图可查看该次评估报告」。  
2. Hover：tooltip 除课型次数外，增加「点击查看报告」或会话时间。  
3. 点击后进入现有 `ReportPage`，传入该次 `behavior_session_id`；返回键回到儿童信息页（保持当前选中儿童）。  
4. 若该次尚无报告文件：提示「报告生成中 / 暂无报告」，可选触发 `GET /api/report/{id}?generate=1`（需产品确认是否自动生成）。

#### R4. 初步筛查 / 最新干预建议

1. 右上卡片支持两个视图切换：`初步筛查` | `最新干预建议`。  
2. **默认规则**：该儿童存在至少一次已同步训练/报告 → 默认 `最新干预建议`；否则默认 `初步筛查`。  
3. 干预建议内容：取**最新一次**报告的 `narrative.recommendations`（列表展示 title + body）；可附简短 `analysis`。  
4. 提供主按钮：「查看最新评估报告」→ 跳转最新报告对应 UUID。  
5. 无干预数据时空态文案：「完成一次完整训练并生成报告后，将在此显示干预建议」。  
6. 初步筛查仍读 `students.screening`（本阶段可不做编辑 API，除非顺手需要）。

#### R5. 布局紧凑化

1. 「能力分析」「训练记录」同一行两列：左能力、右训练。  
2. 图表高度下调（建议 260–320px，随断点可再降）。  
3. 窄屏（如 `<1024px`）允许折行上下排列，避免挤压不可用。  
4. 保持现有整体视觉语言（白卡片、indigo 点缀、info 页既有风格），本阶段不做品牌级视觉重做。

#### R6. 「模仿」占位

1. 每次同步能力项时，「模仿」写入 **60**。  
2. 雷达图/趋势中正常显示该维。  
3. 规划备注：后续用 `courseScores.mimic` 或独立算法替换；替换时只改同步映射，不改前端图表结构。

### 3.3 非目标（本阶段不做）

- 不重做报告页内容与评分公式。  
- 不强制把完整 `report.json` 整包迁入 SQLite（可选存摘要）。  
- 不改造儿童端互动课。  
- 不要求回溯重算历史未关联的旧 JSON（可做可选迁移脚本，见 §5.6）。  
- 不实现「模仿」真实能力算法。

### 3.4 数据字段映射（档案页需要什么）

| 档案模块 | 主要字段 | 报告侧来源 |
|----------|----------|------------|
| 能力分析 | 六维 score | `dimensions.*` + 模仿占位 60 |
| 训练记录 | 课型 count、日期时间、session 标识 | `windows[].course_type` 计数 + `trainingSessionId` + 训练起止时间 |
| 最新干预建议 | recommendations[], analysis | `narrative.recommendations` / `narrative.analysis` |
| 跳转报告 | behavior UUID | `trainingSessionId` |

建议映射（报告 → DB 能力中文名）：

| DB `ability_type.name` | 报告字段 | 本阶段规则 |
|------------------------|----------|------------|
| 注意力 | `dimensions.attention.score` | 直接取整；不可用则跳过或记 0（需统一策略，建议「available=false 则不写/不参与最新雷达」） |
| 模仿 | — | **固定 60** |
| 配对 | `dimensions.matching.score` | 同上 |
| 排序 | `dimensions.ordering.score` | 同上 |
| 表达性语言 | `dimensions.expressiveLanguage.score` | 同上 |
| 接收性语言 | `dimensions.receptiveLanguage.score` | 同上 |

课型中文名与现有字典对齐：命名 / 拟声 / 模仿 / 配对 / 排序（与 `course_type` 表及前端硬编码系列一致）。

---

## 4. 前端设计修改说明

### 4.1 信息架构（改后）

```
┌─ 左栏：学生列表 ─┬─ 右栏：档案详情 ────────────────────────────────┐
│                  │  {姓名} - 学生档案                               │
│                  │  ┌──────────────┬─────────────────────────────┐ │
│                  │  │ 基础信息      │  [初步筛查|最新干预建议] Tab   │ │
│                  │  │              │  正文…                        │ │
│                  │  │              │  [查看最新评估报告]（干预时）   │ │
│                  │  └──────────────┴─────────────────────────────┘ │
│                  │  ┌──────────────────┬─────────────────────────� │ │
│                  │  └──────────────┴─────────────────────────────┘ │
│                  │  ┌──────────────────┬─────────────────────────┐ │
│                  │  │ 能力分析（左）     │ 训练记录（右）            │ │
│                  │  │ 雷达/趋势 Tab     │ 堆叠柱图（按次）           │ │
│                  │  │ 高度约 280px      │ 可点击 + 辅助说明文案      │ │
│                  │  └──────────────────┴─────────────────────────┘ │
│                  │  右下：开始评估 / 开始训练                         │
└──────────────────┴────────────────────────────────────────────────┘
```

### 4.2 模块级 UI 规格

#### A. 右上卡片：筛查 / 干预

- 标题行：左侧图标 + 动态标题；右侧 **分段控件**（与能力分析 Tab 同款：`bg-gray-100` + 白底选中）。  
- Tab 文案：`初步筛查`、`最新干预建议`。  
- 干预内容区：  
  - 每条建议：`title`（加粗）+ `body`（次级正文）。  
  - 列表间距紧凑；超出区域 `max-h` + 内部滚动，避免把下方图表顶出屏。  
- 底部操作（仅干预 Tab）：次要链接或主色小按钮「查看最新评估报告」。  
- 空态 / 无训练：禁用「最新干预建议」或允许进入但显示空态（推荐允许进入 + 空态，避免教师找不到入口）。

#### B. 能力分析（左列）

- 保留「当前能力 / 发展趋势」切换。  
- 图表高度：`280`（原 400）。  
- 可选：在雷达图下方一行小字「模仿能力暂为参考占位分」，仅当后端标记 `imitationPlaceholder: true` 时显示（推荐做，成本低）。

#### C. 训练记录（右列）

- 标题行右侧辅助文案（灰色 12px）：`点击柱状图查看该次评估报告`。  
- 柱图：`cursor-pointer`；`Bar` 增加 `onClick`（或 `BarChart` 的 `onClick`）。  
- Hover 增强：tooltip 增加会话时间、综合分（若 API 提供 `overall`）、「点击查看报告」。  
- 视觉可感知性（任选组合，建议至少 2 项）：  
  1. 标题旁辅助文案（必须）  
  2. hover 时柱体亮度/描边变化  
  3. tooltip CTA 文案  
- **不再按日合并**；数据点携带 `behaviorSessionId`（前端状态保留，勿在聚合时丢弃）。

#### D. 响应式

- `xl/lg`：`grid-cols-2` 并排。  
- `md` 及以下：上下堆叠，图表高度可再降至 240。

### 4.3 导航与状态（App 层）

现有：

```text
studentInfo → courseSelection → control → report
report.onBack → studentInfo
```

需补充：

```text
studentInfo --(点击训练柱 / 查看最新报告)--> report
report.onBack --> studentInfo（保留 selectedStudent）
```

实现要点：

- `StudentInfoPage` 新增 props：`onViewReport: (trainingSessionId: string) => void`。  
- `App.tsx` 复用已有 `handleViewReport`。  
- 从档案进报告时，`ReportPage` 的 `studentName` 继续传当前选中儿童标识（与现逻辑一致）。

### 4.4 交互状态表

| 状态 | 能力分析 | 训练记录 | 右上默认 Tab | 「查看最新报告」 |
|------|----------|----------|--------------|------------------|
| 无训练 | 空态 | 空态 | 初步筛查 | 隐藏或禁用 |
| 有训练、报告 READY | 最新能力 | 按次柱图可点 | 最新干预建议 | 可用 |
| 有训练、仅 PARTIAL | 显示已同步分 | 可点；报告页按现有 PARTIAL UI | 最新干预建议（若 narrative 已有） | 可用 |
| 报告文件缺失 | 若未同步则空 | 柱可点但 toast 错误 | 筛查 | 禁用 |

### 4.5 文案清单（中文）

- 辅助：`点击柱状图查看该次评估报告`  
- Tooltip CTA：`点击查看评估报告`  
- 干预空态：`完成一次完整训练并生成报告后，将在此显示干预建议`  
- 占位说明（可选）：`「模仿」暂为占位参考分（60）`  
- 跳转失败：`暂无法打开该次报告，请稍后重试`

---

## 5. 技术实现规划

### 5.1 推荐总体方案

**「文件存全文 + 数据库存索引与档案摘要」**

| 层 | 职责 |
|----|------|
| 继续 | `report.json` / `session_summary.json` 存完整报告与过程数据 |
| 新增/扩展 | SQLite：训练会话桥接 UUID、课型次数、能力分、干预摘要（或独立报告摘要表） |
| API | 学生维度列表/最新干预；档案页少改即可消费 |
| 前端 | 布局、Tab、点击跳转、按次柱图 |

备选（不推荐作主路径）：仅扫 `static/recordings/behavior/*` 按 `studentId` 聚合——实现快但列表性能、筛选、与现有学生 API 不一致，难维护。

### 5.2 数据库变更（建议）

#### 方案 A（推荐，改动适中）

扩展 `training_session`：

| 字段 | 类型 | 说明 |
|------|------|------|
| `behavior_session_id` | String(64), unique, nullable | 对应报告 UUID；历史样例数据可为空 |
| `overall_score` | Integer, nullable | 可选，方便 tooltip |
| `report_status` | String(16), nullable | READY / PARTIAL |
| `report_generated_at` | DateTime, nullable | |

新增表 `training_report_summary`（或把 JSON 挂在 session 上）：

| 字段 | 说明 |
|------|------|
| `training_session_id` | FK |
| `student_id` | FK，冗余便于查询 |
| `behavior_session_id` | UUID |
| `narrative_analysis` | Text, nullable |
| `recommendations_json` | Text/JSON：`[{title,body}]` |
| `dimensions_json` | 可选，调试/对账 |
| `updated_at` | |

继续使用现有：

- `training_detail`：课型次数  
- `ability_item`：六维分  

#### 方案 B（更轻）

只扩 `behavior_session_id` + 写 `training_detail` / `ability_item`；干预建议列表时 **读最新 UUID 再打开 report.json**。  
优点：表少。缺点：档案页多一次文件 IO；部署路径依赖更强。

**建议首期用方案 A 的精简版**：`behavior_session_id` + detail/ability 必写；`recommendations_json` 至少落库（干预 Tab 零文件依赖）。

### 5.3 后端同步时机与逻辑

**触发点（单一真相）：** `ReportService.generate` / `refresh` 在 `save_report` 成功之后调用 `sync_student_archive_from_report(report)`。

伪流程：

```text
1. 解析 studentId、trainingSessionId、dimensions、courseScores、windows、narrative、status、overall
2. Upsert training_session by behavior_session_id
   - date/start/end 从 training.json 或 summary 取
3. Replace training_detail for that session（先删后插或 upsert）
4. Replace ability_item：
   - 五维从 dimensions 映射
   - 模仿 = 60
5. Upsert training_report_summary（recommendations + analysis）
6. 事务提交；失败打日志，不影响报告 JSON 已成功（可后续补偿任务）
```

课型计数：遍历 `windows`，按 `course_type`（需与中文名/英文 key 做映射表，与 scoring 配置保持一致）累加 `count`。

### 5.4 API 规划

#### 复用并增强

| 接口 | 变更 |
|------|------|
| `GET /api/students/{id}` | abilities 仍来自最新 session；可附带 `latest_report` 摘要字段（可选） |
| `GET /api/students/{id}/abilities` | 仅包含已同步真实/样例 session；有 `behavior_session_id` 的排在可信数据前（或过滤无 UUID 的样例——产品决定） |
| `GET /api/students/{id}/training-sessions` | **每条必须返回** `behavior_session_id`、`overall_score?`、`report_status?`；**前端停止按日合并** |

#### 新增（推荐）

| 接口 | 说明 |
|------|------|
| `GET /api/students/{id}/latest-intervention` | 返回最新建议 + `behavior_session_id` + `generated_at`；无则 404/空 success |
| `GET /api/students/{id}/reports?limit=20` | 历史报告索引列表（可选，供未来列表 UI） |

响应示例（latest-intervention）：

```json
{
  "success": true,
  "data": {
    "behavior_session_id": "uuid...",
    "generated_at": "2026-07-17T08:00:00Z",
    "report_status": "READY",
    "analysis": "...",
    "recommendations": [
      { "title": "...", "body": "..." }
    ]
  }
}
```

### 5.5 前端改动清单

| 文件 | 改动 |
|------|------|
| `App.tsx` | 向 `StudentInfoPage` 传入 `onViewReport` |
| `StudentInfoPage.tsx` | 布局两列；筛查/干预 Tab；拉 latest-intervention；训练数据保留 UUID；柱图点击；图表高度；辅助文案 |
| （类型）本地 interface | `TrainingSession` 增加 `id`、`behavior_session_id`、时间字段等 |
| `ReportPage.tsx` | 原则上不改；确认从档案进入时返回路径正确即可 |

### 5.6 历史数据与样例数据

1. **样例脚本数据**：无 UUID，柱图不可跳转报告 → UI 上点击时提示「该记录无关联报告」（或隐藏点击）。  
2. **可选迁移脚本**：扫描 `static/recordings/behavior/*/report.json`，按 `studentId` 回填 DB（一次性工具，放 `database/` 或 `tools/`）。  
3. 不自动删除样例数据；可在文档中说明「演示库与真实库混用时的表现」。

### 5.7 实施阶段建议

| 阶段 | 内容 | 产出验收 |
|------|------|----------|
| **P0** | DB 字段/表 + `sync_student_archive_from_report` + 幂等 | 跑完一次真实训练，DB 出现 UUID 会话、detail、ability（模仿=60） |
| **P1** | 增强 training-sessions API + latest-intervention API | Postman/前端可拉到真实列表与建议 |
| **P2** | StudentInfoPage 布局 + 干预 Tab + 柱图跳转 | 完整用户故事 1–4 |
| **P3** | 可选：扫盘迁移、占位说明文案、tooltip 显示 overall | 体验打磨 |

建议严格按 P0→P2 顺序；**无 P0 时改前端只能继续显示样例/空数据**。

### 5.8 测试计划（实现阶段用）

1. 新儿童、无训练：默认筛查；两图空态；无跳转按钮。  
2. 完成一次含多课型训练并生成 READY 报告：  
   - DB 有一行 session + UUID；  
   - 雷达六维有值且模仿=60；  
   - 柱图多一根；点击进入正确报告。  
3. 同一天两次训练：两根柱，分别进不同报告。  
4. refresh 报告后：能力分/建议更新，不产生重复 session。  
5. 窄屏下两模块可折行且可点。  
6. 仅有样例数据无 UUID：不崩溃，点击有明确提示。

### 5.9 风险与决策点（实现前需产品确认）

| # | 问题 | 建议默认 |
|---|------|----------|
| 1 | 柱图按「次」还是按「日」？ | **按次** |
| 2 | 无报告的 session 是否显示在柱图？ | 显示，点击再提示 |
| 3 | PARTIAL 是否算「有干预」并默认 Tab？ | narrative 有 recommendations 即算 |
| 4 | dimensions.available=false 时如何入库？ | 该维不写或写 null；最新雷达只用 available 维（模仿仍 60） |
| 5 | 样例数据是否过滤？ | 列表保留；无 UUID 不可进报告 |
| 6 | 同步失败是否阻断报告返回？ | **不阻断**；打错误日志 + 可手动补偿 |

---

## 6. 与现有文档/代码的对齐

- PRD（`docs/PRD.md` §5.1 步骤 8）：「结束训练……写入数据库训练记录（若启用）」——本规划即落地该勾选项的具体设计。  
- 报告协议：`docs/REPORT_SCORING.md`、`app/report/service.py`（`professional-report-v2`）保持不变，档案侧只做投影。  
- 教师端页面状态机：`teacher_frontend/App.tsx` 的 `report` 页已具备，档案入口属于增量。

---

## 7. 建议的文档后续动作

1. 评审本规划中的 **决策点 §5.9**（尤其柱图粒度、PARTIAL 默认 Tab）。  
2. 确认后按 **P0 → P2** 开工；开写代码时以本文件为验收清单。  
3. 实现完成后可另补短文：`STUDENT_INFO_REPORT_INTEGRATION_SUMMARY.md`（变更文件列表 + 迁移说明）。

---

## 8. 一页纸结论

- **现状**：档案页 UI/API 已就绪，但 live 训练结果在 behavior/报告 JSON；DB 训练/能力表未接入，故「真实结果」无法稳定出现在儿童信息页。  
- **需求**：合理；核心是 **UUID 桥接 + 报告生成后同步摘要 + 档案页左右布局与跳转/干预 Tab**。  
- **模仿**：短期统一 60 分占位，可接受。  
- **交互**：整次训练一柱一点进报告，并加文案/hover 提示；干预区默认展示最新建议并提供进最新报告的按钮。  
- **下一步**：评审决策点后开始 P0，**当前阶段不改代码**。
